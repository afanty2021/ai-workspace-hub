# tools/planted-benchmark/run_check.py
"""planted 合成对照检查：把真实验证管道跑在合成市场上，程序化判定三态。

定位（2026-11-25 max 评审 r4 定口径）：固定种子回归基线——单实现、非校准。
它回答的问题只有一个：在这一个合成市场上，这条管道能否检出已知尺寸的边、是否对
无边的配对对照市场保持沉默。用途是防回归（管道被改坏或改松时变红）。
它不回答「误报率多少、多弱的边检得出」：阈值是市场定版后按同一组种子标定的，没有
独立标定集；换种子重跑，各「过松」判据都有名义量级的误报概率（2σ 判据约 5%）。
要下那种结论须另做多种子校准（未实现，挂 review-queue）。

三态：
- 埋边被检出 且 对照市场未通过 → 量具正常（仅就本市场、本尺寸而言）；
- 埋边没检出 → 过严或bug：负结果不可信，先修管道；
- 对照市场也通过 → 过松：正结果不可信；
- 对照样本不足 → 无法判定。

与 sector_rotation.permtest 的关系：置换检验是噪声侧对照（无优势的策略不应显著
跑赢随机持仓）；本模块是信号侧镜像（埋进去的优势必须被检出）。两者合起来才是
完整的量具校验。

覆盖的是三条管道的部分部件，不是整条管道（清单见 README「未覆盖部件」）。本检查
还会报出两处出厂 rps 管道与自身口径不符的地方，修不修由 review-queue 拍板：
- tools/rps/validity.py 臂 C 的 RankIC t 是重叠窗口径（fwd 逐日重叠），在全噪声
  对照市场上就会「显著」——本检查的判定用去重叠 t，并把出厂口径单独报一行；
- rps_core 的上市年数门槛实际是 500 根而非 docstring 的 250 根（预热契约偏差）。

用法：
    python tools/planted-benchmark/run_check.py all
    python tools/planted-benchmark/run_check.py sr --n-perm 200
    python tools/planted-benchmark/run_check.py rps --real-bundle data/research/R20261110-04/rps_bundle.pkl

对现有管道零修改：stage-bottom/jinniu 经 importlib 按文件路径加载，进程内改模块级
CACHE 常量指向合成缓存；rps 进程内改 rps_core.DATA_DIR。写入一律先过 synth.guard_root。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth  # noqa: E402

sys.path.insert(0, str(REPO / "tools" / "sector-rotation"))

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk  # noqa: E402
from sector_rotation.cost import CostModel  # noqa: E402
from sector_rotation.data import build_weekly_frame  # noqa: E402
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402
from sector_rotation.walkforward import coverage_start, run_walkforward  # noqa: E402

DEFAULT_SR_ROOT = REPO / "data" / "planted-benchmark" / "sr"
DEFAULT_CACHE_ROOT = REPO / "data" / "planted-benchmark" / "cache"
ALPHA = 0.1                      # SR 矩阵判定阈值，与 backtest.py 默认档一致
K = 3                            # momentum_topk 持仓数

VERDICT_OK = "量具正常"
VERDICT_STRICT = "过严或bug（埋边未检出）——负结果不可信"
VERDICT_LOOSE = "过松（对照市场也通过）——正结果不可信"
VERDICT_INSUFF = "样本不足——无法判定"
SR_ROWS = ("vs随机", "vs等权", "vs沪深300")
TIERS = ("base", "stress")

# ---- 判据阈值（固定种子回归基线；非预注册、非校准）----
# 来源：市场定版后在本市场实测，留余量取整；各行注释的「出厂实测」即标定依据。
# 没有独立标定集——改生成器参数或换种子后必须重测重标（r4 I-2）。
EVENT_H = 5                      # 事件研究主判定前瞻窗（反弹注入 10 日，h=5 落在注入段内）
EVENT_H_REPORT = (1, 3, 10, 20)  # 其余窗只报告不判定
EDGE_ALPHA_MIN = 0.007           # 埋边票 chuji 事件 alpha 下限（出厂实测 +1.441%，约取半）
EDGE_T_MIN = 5.0                 # 埋边票横截面 t 下限（出厂实测 8.22，约取六成；12 只反弹票为独立单元）
EDGE_POS_MIN = 0.9               # 埋边票 alpha>0 占比下限（出厂实测 100%）
EDGE_NSIG_MIN = 300              # 埋边票合计信号数下限（出厂实测 737，约取四成）
NOISE_NEFF_MIN = 10              # 对照臂有效票数下限（不足=无法判定，不得算干净）
NOISE_ALPHA_MAX = 0.005          # 对照票 |alpha| 上限（出厂实测 chuji +0.029% / jinniu +0.032%）
NOISE_T_MAX = 2.0                # 对照票 |t| 上限（出厂实测 0.31 / 0.69）——2σ 判据，名义误报约 5%/臂
RPS_SPREAD_MIN = 0.05            # 埋边市场 RPS250 十分位 D9−D0（fwd20）价差下限（出厂实测 +16.47pp，约取 30%）
RPS_IC_MEAN_MIN = 0.03           # 埋边市场 RankIC 日均下限（出厂实测 +12.99%，约取 23%）
RPS_IC_T_MIN = 3.5               # 埋边市场去重叠 t（相位 0）下限（出厂实测 8.65，全相位 7.15~9.03，约取四成）
RPS_NOISE_SPREAD_MAX = 0.01      # 对照市场 |D9−D0| 上限（出厂实测 +0.32pp）
RPS_NOISE_T_MAX = 2.0            # 对照市场 |去重叠 t| 上限（出厂实测 0.02）——2σ 判据
RPS_MIN_WINDOWS = 20             # 去重叠窗口数下限（出厂实测 75；不足=无法判定）
RPS_NAIVE_T_FLAG = 2.0           # 对照市场出厂 naive t 口径的「过松」报告线（只报告）
RPS_PERIODS = (50, 120, 250)
RPS_DOCUMENTED_MIN_BARS = 250    # rps_core docstring 声称的上市年数门槛
SR_MIN_OOS = 100                 # SR 样本外周数下限（不足=无法判定）
JINNIU_FWD_WINDOW = 6            # 点火日 t 的 [t, t+6)：与 h=5 前瞻窗（次日开盘进）对齐


def _gt(a, b) -> bool:
    """NaN 安全的比较：None/NaN 一律 False（缺数据不能悄悄算通过）。"""
    try:
        return bool(np.isfinite(a) and a > b)
    except TypeError:
        return False


def _lt(a, b) -> bool:
    try:
        return bool(np.isfinite(a) and a < b)
    except TypeError:
        return False


def _verdict(planted: bool, leaked: bool, sufficient: bool = True) -> str:
    if not sufficient:
        return VERDICT_INSUFF
    if not planted:
        return VERDICT_STRICT
    if leaked:
        return VERDICT_LOOSE
    return VERDICT_OK


def _t(x: np.ndarray) -> float:
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 else float("nan")


_MODULES: dict[str, object] = {}


def _load_module(name: str, path: Path):
    """按文件路径加载管道脚本并缓存（stage-bottom 与 jinniu 的 run_backtest.py 同名，
    sys.path 注入会二义，importlib 直连文件）。缓存后同进程重复调用不再重执行，
    脚本头部的 sys.path.insert 也不会累加（r4 M-3）。"""
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod          # 脚本内部 from jinniu import ... 需要常规注册
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


SB_NAME, JN_NAME = "sb_run_backtest", "jinniu_run_backtest"
SB_PATH = REPO / "tools" / "stage-bottom" / "run_backtest.py"
JN_PATH = REPO / "tools" / "jinniu" / "run_backtest.py"


# ---------------------------------------------------------------- SR 检验矩阵

def _sr_spec() -> UniverseSpec:
    members = [Member(synth.SR_IDX(i), f"行业{i:02d}", (synth.SR_ETF(i),), 0.10)
               for i in range(synth.SR_N)]
    return UniverseSpec(members, {})


def _l0(wf, t):
    return momentum_topk(wf, t, lookback=1, k=K)


def _sr_matrix(wf, *, n_perm: int) -> tuple[dict, dict]:
    """复算 backtest.py L0 检验矩阵的 3 行 × 2 档（vs L0 行仅 L1+，不涉及）。
    返回 (rows, series)；series 保留两行 bootstrap 的输入序列，供测试逐行对拍接线。"""
    start = coverage_start(wf, min_universe=synth.SR_N)
    rows: dict[str, dict] = {}
    series: dict[str, dict] = {}
    for tier, cost in (("base", CostModel.base()), ("stress", CostModel.stress())):
        main_res = run_walkforward(wf, _l0, cost=cost, start=start)
        eq_res = run_walkforward(wf, EqualWeightAnnual(), cost=cost, start=start)
        bench = np.array([wf.bench_300[t] for t in main_res.t_rows])
        series[tier] = {"vs等权": main_res.weekly - eq_res.weekly,
                        "vs沪深300": main_res.weekly - bench}
        rows[tier] = {
            "vs随机": perm_test_vs_random(wf, cost, k=K, n=n_perm, strategy=_l0,
                                          start=start)["p_value"],
            "vs等权": paired_block_bootstrap(series[tier]["vs等权"]),
            "vs沪深300": paired_block_bootstrap(series[tier]["vs沪深300"]),
            "cagr": main_res.metrics["cagr"], "n_oos": int(len(main_res.weekly)),
        }
    return rows, series


def _matrix_all_pass(rows: dict) -> bool:
    return all(_lt(rows[t][r], ALPHA) for t in TIERS for r in SR_ROWS)


def check_sr(sr_root: Path, *, n_perm: int = 1000, noise_writer=None) -> dict:
    """SR 检验矩阵：埋边宇宙 3 行 × 2 档全过；同种子、去掉动量项的对照宇宙不得全过。
    对照判据偏弱——只在六格全过时才报「过松」，部分格假阳性不会报（见 README）。"""
    sr_root = Path(sr_root).resolve()
    write_noise = noise_writer or (lambda r: synth.write_sr_market(r, noise_only=True))
    wf_p = build_weekly_frame(synth.write_sr_market(sr_root / "planted"), _sr_spec(),
                              bench_symbol=synth.SR_BENCH, pick_bypass_single=True)
    wf_n = build_weekly_frame(write_noise(sr_root / "noise"), _sr_spec(),
                              bench_symbol=synth.SR_BENCH, pick_bypass_single=True)
    planted, series = _sr_matrix(wf_p, n_perm=n_perm)
    noise, _ = _sr_matrix(wf_n, n_perm=n_perm)
    planted_passed = bool(_matrix_all_pass(planted))
    noise_leaked = bool(_matrix_all_pass(noise))
    sufficient = all(rows[t]["n_oos"] >= SR_MIN_OOS for rows in (planted, noise) for t in TIERS)
    return {"target": "sr", "planted_passed": planted_passed, "noise_leaked": noise_leaked,
            "planted": planted, "noise": noise, "planted_series": series,
            "verdict": _verdict(planted_passed, noise_leaked, sufficient)}


# ---------------------------------------------------------------- 事件研究族（stage-bottom + jinniu）

def _alpha_rows(per_stock: list[dict], prefix: str, h: int) -> list[dict]:
    """per_stock 行 → summarize 入参（alpha = 信号前瞻均值 − 同票基础率，与两脚本的 agg 同式）。"""
    rows = []
    for r in per_stock:
        s, b = r.get(f"{prefix}_{h}_sig"), r.get(f"{prefix}_{h}_base")
        if s is None or b is None:
            continue
        rows.append({"alpha": s - b, "n_sig": r.get(f"{prefix}_{h}_n", 0)})
    return rows


def _stat(fn, rows: list[dict]) -> dict:
    return fn(rows) if rows else {}


def _noise_arm_state(s: dict) -> tuple[bool, bool]:
    """对照臂状态 → (干净?, 样本充足?)。空样本/有效票不足/t 为 NaN 一律「不足」，
    不得判成干净（r4 M-1）。"""
    if s.get("n_eff", 0) < NOISE_NEFF_MIN:
        return True, False
    a, t = s.get("alpha_mean", float("nan")), s.get("alpha_t", float("nan"))
    if not (np.isfinite(a) and np.isfinite(t)):
        return True, False
    return bool(abs(a) < NOISE_ALPHA_MAX and abs(t) < NOISE_T_MAX), True


def _judge_event(sb_stats: dict, jn_stats: dict, sb_noise: dict, jn_noise: dict) -> dict:
    """阳性只挂 chuji 臂；jinniu buy 臂只判阴性（阳性未验证）。"""
    planted_passed = bool(
        _gt(sb_stats.get("alpha_mean"), EDGE_ALPHA_MIN)
        and _gt(sb_stats.get("alpha_t"), EDGE_T_MIN)
        and _gt(sb_stats.get("pos_ratio"), EDGE_POS_MIN)
        and sb_stats.get("n_sig", 0) >= EDGE_NSIG_MIN)
    ok_sb, suf_sb = _noise_arm_state(sb_noise)
    ok_jn, suf_jn = _noise_arm_state(jn_noise)
    noise_leaked = not (ok_sb and ok_jn)
    return {"planted_passed": planted_passed, "noise_leaked": noise_leaked,
            "sufficient": bool(suf_sb and suf_jn),
            "edge_chuji": sb_stats, "edge_jinniu": jn_stats,
            "noise_chuji": sb_noise, "noise_jinniu": jn_noise,
            "jinniu_positive": "未验证（jinniu 臂只判阴性）",
            "verdict": _verdict(planted_passed, noise_leaked, suf_sb and suf_jn)}


def _closes(cache_root: Path, sym: str) -> np.ndarray:
    return np.array([json.loads(ln)["close"]
                     for ln in (cache_root / f"{sym}.jsonl").read_text().splitlines()])


def _jinniu_expected_n(mod, cache_root: Path, sym: str, h: int = 1) -> int:
    """独立推 d_buy_<h>_n：buy 信号由本模块另行调用 icon_signals 得到，过滤走管道自己的
    event_returns。只锁「标着 buy 的行确实由该票的 buy 信号算出」——读错臂（换成 sell）
    或读错票都会不符。不锁信号公式本身，也不锁过滤口径（后者见 event_filter_retention）。"""
    from jinniu import icon_signals
    di, o, c = mod.load_symbol(cache_root / f"{sym}.jsonl")
    ib, _ = icon_signals(c)
    ib[:mod.WARMUP] = False
    return int(mod.event_returns(di, o, ib, h, mod.GAP_DAYS)[0].size)


def _check_jinniu_wiring(consumed: int, expected: int) -> None:
    """接线核对：本次判定实际消费到的 jinniu 信号样本数，必须等于由 buy 信号独立推得的样本数。
    只验管道输出的行不够——还得验消费的是哪一行：读错臂（换成 sell）或漏票都会不符。"""
    if consumed != expected:
        raise ValueError(
            f"jinniu 接线核对失败：消费到的信号样本数 {consumed} 与独立推得的 buy 信号样本数 "
            f"{expected} 不符——检查读错了臂或票，判定不可用")


EVENT_FILTER_RETENTION_MIN = 0.99    # 零停牌合成市场上 event_returns 的最低保留率


def event_filter_retention(cache_root: Path, syms, *, hs=(1, 3, 5, 10, 20)) -> dict:
    """两条事件研究管道各自那份 event_returns 的「停牌跳空过滤」在零停牌合成市场上的保留率。

    合成日历连续（相邻交易日的日历日差 ≤3），该过滤不应剔除任何样本，保留率不足 100%
    的部分就是误删。2026-11-25 首测约 70%（h=5）：过滤用 YYYYMMDD 整数差当天数
    （跨月 1201−1130=71 > 阈值 10），前瞻窗跨月的样本全被当成停牌。这是既有管道的缺陷，
    修不修由 review-queue 拍板，本检查只报告。"""
    out = {}
    for name, mod in (("stage-bottom", _load_module(SB_NAME, SB_PATH)),
                      ("jinniu", _load_module(JN_NAME, JN_PATH))):
        kept = {h: 0 for h in hs}
        dom = {h: 0 for h in hs}
        for sym in syms:
            loaded = mod.load_symbol(cache_root / f"{sym}.jsonl")
            di, o = loaded[0], loaded[1]
            n = len(o)
            base = np.ones(n, dtype=bool)
            for h in hs:
                kept[h] += int(mod.event_returns(di, o, base, h, mod.GAP_DAYS)[0].size)
                dom[h] += max(n - 2 - h, 0)      # idx ≥ 1 且 idx+1+h < n 的索引个数
        out[name] = {h: kept[h] / dom[h] for h in hs}
    return out


def var19_enrichment(cache_root: Path, tickers: dict[str, dict],
                     *, window: int = JINNIU_FWD_WINDOW) -> dict:
    """VAR19（jinniu buy）点火日与反弹注入窗的富集比——README 所引数字的仓库内出处。

    口径：hit = 点火日的 [t, t+window) 含注入日的比例；base = 同一索引域内
    （warmup 之后）任意一日的该比例。base 恒高于单日注入占比，首版拿单日占比当
    基准是错的（r4 I-4）。富集比≈1 即点火与注入窗无关。只关于合成市场，
    不构成对真实 A 股 VAR19 的断言。"""
    jn = _load_module(JN_NAME, JN_PATH)
    from jinniu import icon_signals  # noqa: E402  脚本已把 tools/jinniu 注入 sys.path
    warm = jn.WARMUP
    fires = hits = base_days = base_hits = inj_days = all_days = 0
    for sym in synth.EDGE_BOUNCE:
        kw = tickers[sym]
        n = kw["n"]
        mask = synth.bounce_mask(kw["seed"], n)
        ib, _ = icon_signals(_closes(cache_root, sym))
        ib[:warm] = False
        win = np.array([mask[t:t + window].any() for t in range(n)])
        fire = np.flatnonzero(ib)
        fires += len(fire)
        hits += int(win[fire].sum())
        base_days += n - warm
        base_hits += int(win[warm:].sum())
        inj_days += int(mask.sum())
        all_days += n
    hit_rate, base_rate = hits / fires, base_hits / base_days
    return {"window": window, "fires": fires, "hit_rate": hit_rate, "base_rate": base_rate,
            "enrichment": hit_rate / base_rate,
            "single_day_injection_share": inj_days / all_days}


def check_event(cache_root: Path, *, n_bars: int = synth.N_EVENT_BARS, tickers=None,
                verbose: bool = False) -> dict:
    """事件研究族：阳性挂 stage-bottom chuji 臂（EDGE_BOUNCE 上 alpha 显著为正）；
    jinniu buy 臂只判阴性。对照 = NOISE（35 只）；EDGE_MOM 不判（动量票不是超卖修复
    信号的优势族）。d_buy 行与独立重数的 buy 信号逐票对拍，不符直接抛错。"""
    cache_root = Path(cache_root).resolve()
    tickers = tickers or synth.event_market_tickers(n_bars)
    synth.write_cache(cache_root, tickers)
    out_root = cache_root / "event-out"            # 产物落 cache 根内部，不往外层目录写
    sb = _load_module(SB_NAME, SB_PATH)
    jn = _load_module(JN_NAME, JN_PATH)

    def _run(mod, outdir: Path) -> list[dict]:
        outdir.mkdir(parents=True, exist_ok=True)  # 两管道都写 per_stock.jsonl，分目录
        old = mod.CACHE
        mod.CACHE = cache_root
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                mod.main(["--out", str(outdir)])
        finally:
            mod.CACHE = old
        if verbose:
            print(buf.getvalue())
        return [json.loads(ln) for ln in (outdir / "per_stock.jsonl").read_text().splitlines()]

    sb_rows = _run(sb, out_root / "stage-bottom")
    jn_rows = _run(jn, out_root / "jinniu")

    noise_syms, edge_syms = set(synth.NOISE), set(synth.EDGE_BOUNCE)

    def split(rows):
        return ([r for r in rows if r["sym"] in edge_syms],
                [r for r in rows if r["sym"] in noise_syms])

    sb_edge, sb_noise_rows = split(sb_rows)
    jn_edge, jn_noise_rows = split(jn_rows)
    rep: dict = {"h_main": EVENT_H, "chuji": {}, "jinniu_buy": {}}
    for h in (EVENT_H,) + EVENT_H_REPORT:
        rep["chuji"][h] = {"edge": _stat(sb.summarize, _alpha_rows(sb_edge, "chuji", h)),
                           "noise": _stat(sb.summarize, _alpha_rows(sb_noise_rows, "chuji", h))}
        rep["jinniu_buy"][h] = {
            "edge": _stat(lambda rows: jn.summarize("buy", rows),
                          _alpha_rows(jn_edge, "d_buy", h)),
            "noise": _stat(lambda rows: jn.summarize("buy", rows),
                           _alpha_rows(jn_noise_rows, "d_buy", h))}
    res = _judge_event(rep["chuji"][EVENT_H]["edge"], rep["jinniu_buy"][EVENT_H]["edge"],
                       rep["chuji"][EVENT_H]["noise"], rep["jinniu_buy"][EVENT_H]["noise"])
    # h=1 的样本数不受前瞻窗截尾影响，接线核对用它（EDGE_MOM 两边都不判，不计入）
    consumed = sum(rep["jinniu_buy"][1][k].get("n_sig", 0) for k in ("edge", "noise"))
    _check_jinniu_wiring(consumed, sum(_jinniu_expected_n(jn, cache_root, r["sym"])
                                       for r in jn_edge + jn_noise_rows))
    retention = event_filter_retention(cache_root, synth.EDGE_BOUNCE[:4], hs=(EVENT_H,))
    notes = []
    for name, per_h in retention.items():
        if per_h[EVENT_H] < EVENT_FILTER_RETENTION_MIN:
            notes.append(f"{name} 的 event_returns 停牌过滤在零停牌合成市场上只保留 "
                         f"{per_h[EVENT_H]:.1%}（h={EVENT_H}）——YYYYMMDD 整数差被当天数用，"
                         f"跨月窗被误删（既有管道缺陷，挂 review-queue 待拍板）")
    res.update({"target": "event", "report": rep, "jinniu_wiring_ok": True,
                "enrichment": var19_enrichment(cache_root, tickers),
                "retention": retention, "notes": notes})
    return res


# ---------------------------------------------------------------- rps 横截面

def _row_ic(x, y):
    """逐日横截面 spearman（rank-rank pearson 向量化）——tools/rps/validity.py row_ic 同式
    （该文件是带副作用的顶层脚本，import 即写 output/research，不可 import；公式按原文
    复制，改动须对拍原文）。"""
    a, b = x.rank(axis=1), y.rank(axis=1)
    am = a.sub(a.mean(axis=1), axis=0)
    bm = b.sub(b.mean(axis=1), axis=0)
    cov = (am * bm).mean(axis=1)
    return cov / (am.std(axis=1) * bm.std(axis=1))


def _ic_block(ic: np.ndarray, h: int) -> dict:
    phases = [_t(ic[ph::h]) for ph in range(h)]
    return {"ic_mean": float(ic.mean()) if len(ic) else float("nan"),
            "ic_t": phases[0],                       # 相位 0 的去重叠 t：判定用
            "ic_t_overlap": _t(ic),                  # 出厂 validity.py 的 naive t：只报告
            "ic_t_phase_min": float(np.nanmin(phases)), "ic_t_phase_max": float(np.nanmax(phases)),
            "n_days": int(len(ic)), "n_windows": int(len(ic[0::h]))}


def _rps_arms(bundle: dict) -> dict:
    """validity.py 臂 A（RPS250 十分位 D9−D0 价差）与臂 C（RankIC）的复算，fwd20 主判定。
    臂 C 的 t 有三个口径，见 _ic_block：fwd 窗逐日重叠（相邻日共享 h−1 天），naive t
    假设逐日独立，有效样本约膨胀 h 倍——全噪声对照市场上 naive t 就能到 2 以上。"""
    close_adj, rps250 = bundle["close_adj"], bundle["rps250"]
    out = {}
    for h in (20, 60):
        fwd = close_adj.shift(-h) / close_adj - 1.0
        elig = rps250.notna()
        f, r = fwd.where(elig), rps250.where(elig)
        deciles = []
        for lo in range(0, 100, 10):
            vals = f[(r >= lo) & (r < lo + 10)].stack()
            deciles.append(float(vals.mean()) if len(vals) else float("nan"))
        out[f"fwd{h}"] = {"decile_mean": deciles,
                          "d9_d0_spread": float(deciles[9] - deciles[0]),
                          **_ic_block(_row_ic(rps250, fwd.where(elig)).dropna().to_numpy(), h)}
    return out


def _warmup_contract(bundle: dict) -> dict:
    """rps_core 上市年数门槛的实际行为 vs docstring。docstring 称「≥250 根 bar 才入横截面」；
    rps_from_ret 把 close_count 作用在 ret 帧上（ret 本身晚 N 根），实际门槛是 N+250 根
    （r4 I-8）。本函数只报告，first_bar 是各周期首个非空 RPS 所在的 bar 序号（从 1 起）。"""
    first = {}
    for n in RPS_PERIODS:
        idx = np.flatnonzero(bundle[f"rps{n}"].notna().any(axis=1).to_numpy())
        first[f"rps{n}"] = int(idx[0]) + 1 if len(idx) else None
    ok = all(v is not None and v <= RPS_DOCUMENTED_MIN_BARS + 1 for v in first.values())
    return {"documented_min_bars": RPS_DOCUMENTED_MIN_BARS, "first_bar": first, "ok": bool(ok)}


def _judge_rps(p: dict, n: dict) -> dict:
    planted_passed = bool(
        _gt(p["d9_d0_spread"], RPS_SPREAD_MIN)
        and _gt(p["ic_mean"], RPS_IC_MEAN_MIN)
        and _gt(p["ic_t"], RPS_IC_T_MIN))
    sufficient = bool(n["n_windows"] >= RPS_MIN_WINDOWS
                      and np.isfinite(n["ic_t"]) and np.isfinite(n["d9_d0_spread"]))
    noise_leaked = bool(abs(n["d9_d0_spread"]) > RPS_NOISE_SPREAD_MAX
                        or abs(n["ic_t"]) > RPS_NOISE_T_MAX)
    return {"planted_passed": planted_passed, "noise_leaked": noise_leaked,
            "sufficient": sufficient,
            # 出厂 validity.py 臂 C 口径在同一对照市场上的结论（只报告）：naive t 过 2
            # 即「噪声也显著」= 该口径过松（r4 I-3）。出厂种子下该市场的 naive t 恰好很小，
            # 不触发——这不代表口径没问题：膨胀是公式性质，见 naive_inflation
            "validity_naive_leaked": bool(abs(n["ic_t_overlap"]) > RPS_NAIVE_T_FLAG),
            "naive_inflation": (abs(p["ic_t_overlap"]) / abs(p["ic_t"])
                                if np.isfinite(p["ic_t"]) and p["ic_t"] != 0 else float("nan")),
            "verdict": _verdict(planted_passed, noise_leaked, sufficient)}


def _load_rps_bundle(data_dir: Path) -> dict:
    if str(REPO / "tools" / "rps") not in sys.path:
        sys.path.insert(0, str(REPO / "tools" / "rps"))
    import rps_core
    old = rps_core.DATA_DIR
    rps_core.DATA_DIR = data_dir
    try:
        return rps_core.rps_main()
    finally:
        rps_core.DATA_DIR = old


def check_rps(cache_root: Path, *, n_bars: int = synth.N_EVENT_BARS, noise_writer=None,
              real_bundle: Path | None = None) -> dict:
    """rps 横截面：埋边市场（12 只动量票）的 RPS250 应钉出正的 D9−D0 价差与显著为正的
    去重叠 RankIC；同种子去边的对照市场两臂应沉默。verdict 只管 rps_core 排名 + 去重叠
    t；出厂 validity.py 的 naive t 口径与 rps_core 预热契约各自单独报在 notes 里。
    臂 B（月度组合）/ 臂 D（崩溃段）不在判定内。"""
    cache_root = Path(cache_root).resolve()
    planted_dir = synth.write_cache(cache_root, synth.event_market_tickers(n_bars))
    write_noise = noise_writer or (lambda r: synth.write_cache(r, synth.noise_market_tickers(n_bars)))
    noise_dir = write_noise(cache_root / "noise-market")
    bundles = {tag: _load_rps_bundle(d) for tag, d in (("planted", planted_dir), ("noise", noise_dir))}
    arms = {tag: _rps_arms(b) for tag, b in bundles.items()}
    res = _judge_rps(arms["planted"]["fwd20"], arms["noise"]["fwd20"])
    contract = _warmup_contract(bundles["planted"])
    notes = []
    if res["validity_naive_leaked"]:
        notes.append(f"出厂 validity.py 臂 C naive t 口径：过松（对照市场 |t|="
                     f"{abs(arms['noise']['fwd20']['ic_t_overlap']):.1f}，本检查判定用的是去重叠 t）")
    if not contract["ok"]:
        notes.append(f"rps_core 预热契约偏差：首个 RPS250 在第 {contract['first_bar']['rps250']} 根"
                     f"（docstring 称 ≥{RPS_DOCUMENTED_MIN_BARS} 根）")
    res.update({"target": "rps", "arms": arms, "warmup_contract": contract, "notes": notes})
    if real_bundle:
        res["real"] = real_bundle_overlap(Path(real_bundle))
    return res


def real_bundle_overlap(bundle_path: Path) -> dict:
    """真实 RPS bundle（只读）上臂 A / 臂 C 的 naive t 与去重叠 t——README 所引真实数据
    数字的仓库内出处。validity.py 臂 C 的 t=-15~-17 是重叠窗口径。"""
    import pandas as pd
    b = pd.read_pickle(bundle_path)
    close_adj = b["close_adj"]
    fwd20 = close_adj.shift(-20) / close_adj - 1.0
    r = b["rps250"]
    elig = r.notna()
    f, rr = fwd20.where(elig), r.where(elig)
    dec = [float(f[(rr >= lo) & (rr < lo + 10)].stack().mean()) for lo in range(0, 100, 10)]
    out = {"source": str(bundle_path), "arm_a_fwd20_d9_d0": dec[9] - dec[0]}
    for n in RPS_PERIODS:
        sig = b[f"rps{n}"]
        out[f"rps{n}"] = _ic_block(_row_ic(sig, fwd20.where(sig.notna())).dropna().to_numpy(), 20)
    return out


# ---------------------------------------------------------------- 汇总 CLI

def _fmt_stat(s: dict, unit: str) -> str:
    if "alpha_mean" not in s:
        return "无信号样本"
    return (f"alpha={s['alpha_mean'] * 100:+.2f}%/{unit} t={s['alpha_t']:.1f} "
            f"正率={s.get('pos_ratio', 0):.0%} 信号数={s.get('n_sig', 0)} 有效票={s.get('n_eff', 0)}")


def render(v: dict) -> str:
    t = v["target"]
    lines = [f"== planted[{t}] → {v['verdict']} "
             f"(埋边{'过' if v['planted_passed'] else '未过'} / "
             f"对照市场{'泄漏' if v['noise_leaked'] else '未泄漏'})"]
    if t == "sr":
        for tag in ("planted", "noise"):
            for tier in TIERS:
                r = v[tag][tier]
                cells = ", ".join(f"{k}={r[k]:.3f}" for k in SR_ROWS)
                lines.append(f"  [{tag}] {tier}: {cells}  cagr={r['cagr']:+.1%} 样本外={r['n_oos']}周")
    elif t == "event":
        h = v["report"]["h_main"]
        lines.append(f"  chuji 埋边 h={h}: {_fmt_stat(v['edge_chuji'], f'{h}日')}")
        lines.append(f"  chuji 对照 h={h}: {_fmt_stat(v['noise_chuji'], f'{h}日')}")
        lines.append(f"  jinniu buy 对照 h={h}: {_fmt_stat(v['noise_jinniu'], f'{h}日')}")
        lines.append(f"  jinniu buy 埋边 h={h}: {_fmt_stat(v['edge_jinniu'], f'{h}日')}"
                     f"（{v['jinniu_positive']}）")
        e = v["enrichment"]
        lines.append(f"  VAR19 点火富集比：点火日前瞻窗含注入 {e['hit_rate']:.1%} vs "
                     f"同域任意日 {e['base_rate']:.1%} → {e['enrichment']:.2f}"
                     f"（{e['fires']} 次点火；单日注入占比 {e['single_day_injection_share']:.1%}）")
        lines.append("  接线核对：消费到的 jinniu 信号样本数与独立推得的 buy 信号样本数一致")
        for name, per_h in v["retention"].items():
            lines.append(f"  停牌过滤保留率（零停牌合成市场）{name}: h={h} {per_h[h]:.1%}")
        lines += [f"  ⚠ {n}" for n in v.get("notes", [])]
    elif t == "rps":
        for tag in ("planted", "noise"):
            a = v["arms"][tag]["fwd20"]
            lines.append(f"  [{tag}] D9−D0={a['d9_d0_spread'] * 100:+.2f}pp IC={a['ic_mean'] * 100:+.2f}% "
                         f"去重叠t={a['ic_t']:.2f}（全相位 {a['ic_t_phase_min']:.2f}~{a['ic_t_phase_max']:.2f}）"
                         f" naive={a['ic_t_overlap']:.2f}（{a['n_windows']}窗/{a['n_days']}日）")
        lines.append("  口径：naive = 出厂 validity.py 臂 C 的重叠窗 t；去重叠t = 本检查的判定口径。"
                     f"埋边市场上 naive/去重叠 = {v['naive_inflation']:.1f}（≈√20）"
                     "——naive t 的零分布同比膨胀，2σ 线对它是偏松的")
        lines += [f"  ⚠ {n}" for n in v.get("notes", [])]
        for k, a in v.get("real", {}).items():
            if k == "source":
                lines.append(f"  [真实 bundle] {a}")
            elif k.startswith("arm_a"):
                lines.append(f"  [真实 bundle] 臂A fwd20 D9−D0={a * 100:+.2f}pp")
            else:
                lines.append(f"  [真实 bundle] {k}: IC={a['ic_mean'] * 100:+.2f}% "
                             f"naive t={a['ic_t_overlap']:.2f} 去重叠 t={a['ic_t']:.2f}"
                             f"（全相位 {a['ic_t_phase_min']:.2f}~{a['ic_t_phase_max']:.2f}）")
    return "\n".join(lines)


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("置换数须 ≥1")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planted 合成对照检查（固定种子回归基线）")
    ap.add_argument("target", choices=["sr", "event", "rps", "all"])
    ap.add_argument("--n-perm", type=_positive, default=1000,
                    help="SR vs随机 的置换数，默认 1000；单测用 100（p 值分辨率 1/(n+1)）")
    ap.add_argument("--sr-root", type=Path, default=DEFAULT_SR_ROOT,
                    help="SR 合成宇宙根目录（须在 data/planted-benchmark 或仓库 data/ 之外）")
    ap.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT,
                    help="事件族 / rps 合成缓存根目录（同上；指向真实缓存会被写守卫拒绝）")
    ap.add_argument("--real-bundle", type=Path, default=None,
                    help="rps：可选，真实 RPS bundle 路径（只读，报 naive t 与去重叠 t）")
    ap.add_argument("--verbose", action="store_true", help="透传底层管道的完整表格输出（默认静默）")
    ap.add_argument("--strict", action="store_true",
                    help="把「既有管道契约偏差」注记也算失败（默认只报不算，exit code 只看三态判定）")
    args = ap.parse_args(argv)
    runs = {"sr": lambda: check_sr(args.sr_root, n_perm=args.n_perm),
            "event": lambda: check_event(args.cache_root, verbose=args.verbose),
            "rps": lambda: check_rps(args.cache_root, real_bundle=args.real_bundle)}
    targets = ["sr", "event", "rps"] if args.target == "all" else [args.target]
    ok = True
    for t in targets:
        v = runs[t]()
        print(render(v))
        ok &= v["verdict"] == VERDICT_OK
        if args.strict:
            ok &= not v.get("notes")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
