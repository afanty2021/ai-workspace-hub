# tools/planted-benchmark/run_check.py
"""planted 合成对照检查：把真实验证管道跑在合成市场上，程序化判定三态。

定位（2026-11-25 max 评审 r4 定口径 + Q-20261125-02 同日升格）分两档：

- `sr|event|rps|all`：固定种子回归基线。它回答的问题只有一个：在这一个合成市场上，
  这条管道能否检出已知尺寸的边、是否对无边的配对对照市场保持沉默。用途是防回归
  （管道被改坏或改松时变红）。它不回答「误报率多少、多弱的边检得出」——阈值是市场
  定版后按同一组种子标定的，没有独立标定集。
- `calibrate`：多种子校准量具（Q-20261125-02）。对照侧 ≥N 个独立噪声市场测各判据的
  实测误报率；埋边侧把边强度从弱到出厂扫档测检出率。测量工具不是闸门（exit 恒 0），
  口径声明见 README「多种子校准」节。

三态：
- 埋边被检出 且 对照市场未通过 → 量具正常（仅就本市场、本尺寸而言）；
- 埋边没检出 → 过严或bug：负结果不可信，先修管道；
- 对照市场也通过 → 过松：正结果不可信；
- 对照样本不足 → 无法判定。

与 sector_rotation.permtest 的关系：置换检验是噪声侧对照（无优势的策略不应显著
跑赢随机持仓）；本模块是信号侧镜像（埋进去的优势必须被检出）。两者合起来才是
完整的量具校验。

覆盖的是三条管道的部分部件，不是整条管道（清单见 README「未覆盖部件」）。本检查曾
报出两处出厂 rps 管道与自身口径不符（validity.py 臂 C 重叠窗 naive t、rps_core
上市年数门槛 250+N 根≠docstring 250 根），2026-11-25 当日修根（Q-20261125-03/05）；
对应的报告位转为修根的回归哨兵——修法被改回时 ⚠ 注记重新出现、--strict 重新变红。

用法：
    python tools/planted-benchmark/run_check.py all
    python tools/planted-benchmark/run_check.py sr --n-perm 200
    python tools/planted-benchmark/run_check.py rps --real-bundle data/research/R20261110-04/rps_bundle.pkl
    python tools/planted-benchmark/run_check.py calibrate --n-markets 50 --n-perm 200 \
        --out-json data/planted-benchmark/calib.json

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


def _event_edge_pass(sb_stats: dict) -> bool:
    """chuji 阳性判据（四条全过）：alpha / t / 正率 / 信号数。calibrate 埋边扫档复用
    同一谓词——校准测的检出率就是回归基线判定的通过率，两处不得各写一份。"""
    return bool(_gt(sb_stats.get("alpha_mean"), EDGE_ALPHA_MIN)
                and _gt(sb_stats.get("alpha_t"), EDGE_T_MIN)
                and _gt(sb_stats.get("pos_ratio"), EDGE_POS_MIN)
                and sb_stats.get("n_sig", 0) >= EDGE_NSIG_MIN)


def _judge_event(sb_stats: dict, jn_stats: dict, sb_noise: dict, jn_noise: dict) -> dict:
    """阳性只挂 chuji 臂；jinniu buy 臂只判阴性（阳性未验证）。"""
    planted_passed = _event_edge_pass(sb_stats)
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


def _jinniu_wiring_ok(jn, cache_root: Path, rows: list[dict]) -> None:
    """整批接线核对（h=1 的样本数不受前瞻窗截尾影响）：判定消费到的 d_buy_1_n 合计
    必须等于由 buy 信号独立推得的合计。rows 只含被判定/对拍的票（EDGE_MOM 不判不计入，
    与 check_event 口径一致）。check_event 与 calibrate 共用——校准跑批若读错臂，
    误报率/检出率统计直接作废，必须在每个市场上拦住。"""
    consumed = sum(r.get("d_buy_1_n", 0) for r in rows)
    expected = sum(_jinniu_expected_n(jn, cache_root, r["sym"]) for r in rows)
    _check_jinniu_wiring(consumed, expected)


EVENT_FILTER_RETENTION_MIN = 0.99    # 零停牌合成市场上 event_returns 的最低保留率


def event_filter_retention(cache_root: Path, syms, *, hs=(1, 3, 5, 10, 20)) -> dict:
    """两条事件研究管道各自那份 event_returns 的「停牌跳空过滤」在零停牌合成市场上的保留率。

    合成日历连续（相邻交易日的日历日差 ≤3），该过滤不应剔除任何样本，保留率不足 100%
    的部分就是误删。2026-11-25 首测约 70%（h=5）：过滤曾用 YYYYMMDD 整数差当天数
    （跨月 1201−1130=71 > 阈值 10），前瞻窗跨月的样本全被当成停牌——当日已修
    （civil_days，Q-20261125-04），本指标转为该修法的回归哨兵。"""
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
        mask = synth.bounce_mask(kw["seed"], n, bounce=kw.get("bounce", synth.BOUNCE))
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


def _run_event_pipes(cache_root: Path, *, verbose: bool = False):
    """两条事件管道在 cache_root 上各跑一遍 main（进程内改模块级 CACHE，try/finally
    还原；产物落 cache 根内部的 event-out/），返回 (sb, jn, sb_rows, jn_rows)。
    check_event 与 calibrate_event 共用——两边的跑批路径必须同一条，校准才校得到
    回归基线真正跑的东西。"""
    out_root = cache_root / "event-out"
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

    return sb, jn, _run(sb, out_root / "stage-bottom"), _run(jn, out_root / "jinniu")


def check_event(cache_root: Path, *, n_bars: int = synth.N_EVENT_BARS, tickers=None,
                verbose: bool = False) -> dict:
    """事件研究族：阳性挂 stage-bottom chuji 臂（EDGE_BOUNCE 上 alpha 显著为正）；
    jinniu buy 臂只判阴性。对照 = NOISE（35 只）；EDGE_MOM 不判（动量票不是超卖修复
    信号的优势族）。d_buy 行与独立重数的 buy 信号逐票对拍，不符直接抛错。"""
    cache_root = Path(cache_root).resolve()
    tickers = tickers or synth.event_market_tickers(n_bars)
    synth.write_cache(cache_root, tickers)
    sb, jn, sb_rows, jn_rows = _run_event_pipes(cache_root, verbose=verbose)

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
    _jinniu_wiring_ok(jn, cache_root, jn_edge + jn_noise_rows)
    retention = event_filter_retention(cache_root, synth.EDGE_BOUNCE[:4], hs=(EVENT_H,))
    notes = []
    for name, per_h in retention.items():
        if per_h[EVENT_H] < EVENT_FILTER_RETENTION_MIN:
            notes.append(f"{name} 的 event_returns 停牌过滤在零停牌合成市场上只保留 "
                         f"{per_h[EVENT_H]:.1%}（h={EVENT_H}）——过滤回归（历法日修法被改回"
                         f"整数差或引入了新误删，Q-20261125-04）")
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
    修根前 rps_from_ret 把 close_count 作用在 ret 帧上（ret 本身晚 N 根），实际门槛是
    N+250 根（r4 I-8），2026-11-25 当日修根（Q-20261125-03，bar_count 显式传 close 帧计数）
    ——本函数转为该修法的回归哨兵，修法被改回时 ok=False → ⚠ 注记。first_bar 是各周期
    首个非空 RPS 所在的 bar 序号（从 1 起）。"""
    first = {}
    for n in RPS_PERIODS:
        idx = np.flatnonzero(bundle[f"rps{n}"].notna().any(axis=1).to_numpy())
        first[f"rps{n}"] = int(idx[0]) + 1 if len(idx) else None
    ok = all(v is not None and v <= RPS_DOCUMENTED_MIN_BARS + 1 for v in first.values())
    return {"documented_min_bars": RPS_DOCUMENTED_MIN_BARS, "first_bar": first, "ok": bool(ok)}


def _rps_edge_pass(a: dict) -> bool:
    """rps 阳性判据（三条全过）：D9−D0 价差 / 日均 IC / 去重叠 t。calibrate 埋边扫档复用。"""
    return bool(_gt(a["d9_d0_spread"], RPS_SPREAD_MIN)
                and _gt(a["ic_mean"], RPS_IC_MEAN_MIN)
                and _gt(a["ic_t"], RPS_IC_T_MIN))


def _judge_rps(p: dict, n: dict) -> dict:
    planted_passed = _rps_edge_pass(p)
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


# ---------------------------------------------------------------- 多种子校准（Q-20261125-02）

# 校准用种子偏移：全部从 1 起数、各管道各侧互不重叠——0 号市场是阈值标定用的，不算
# 独立抽样（标定集上测误报率是循环论证，r4 I-2 教训的正面应用）。
CALIB_NOISE_BASE = 1000        # 对照侧第 k 个市场的种子偏移 = CALIB_NOISE_BASE * k
CALIB_EDGE_BASE = 100000       # 埋边扫档第 j 个种子的偏移 = CALIB_EDGE_BASE + CALIB_NOISE_BASE * j
CALIB_RPS_NOISE_BASE = 200000  # rps 对照侧偏移基数（与事件族的噪声市场抽样独立）
CALIB_RPS_EDGE_BASE = 300000
BOUNCE_LEVELS = (0.002, 0.004, 0.006, 0.008, 0.010)   # 反弹注入/日；0.010=出厂
MOM_COEF_LEVELS = (0.05, 0.10, 0.15, 0.20, 0.25)      # 动量系数；rps 出厂 0.25 / SR 出厂 0.20


def _edge_alpha_mean(stats: list[dict]) -> float:
    vals = [s["alpha_mean"] for s in stats if "alpha_mean" in s]
    return float(np.mean(vals)) if vals else float("nan")


def calibrate_event(cache_root: Path, *, n_markets: int, edge_seeds: int,
                    verbose: bool = False) -> dict:
    """事件族校准。对照侧：n_markets 个独立噪声市场（偏移 1000·k，k≥1）跑同一套管道，
    按出厂对照判据（|alpha|<0.5% 且 |t|<2，chuji 与 jinniu buy 两臂）统计实测误报率；
    接线核对逐市场照跑，读错臂直接抛错。埋边侧：bounce 从 0.2%/日扫到出厂 1%/日，
    每档 edge_seeds 个独立种子，检出=四条阳性判据全过（_event_edge_pass），逐条判据
    通过率一并报——看哪条判据在弱边上先掉。"""
    noise_syms, edge_syms = set(synth.NOISE), set(synth.EDGE_BOUNCE)
    judged = edge_syms | noise_syms
    out: dict = {"n_markets": n_markets, "edge_seeds": edge_seeds}
    clean_c: list[bool] = []
    clean_j: list[bool] = []
    insuff = 0
    for k in range(1, n_markets + 1):
        print(f"[calibrate] event 对照市场 {k}/{n_markets}", file=sys.stderr)
        synth.write_cache(cache_root, synth.noise_market_tickers(seed_shift=CALIB_NOISE_BASE * k))
        sb, jn, sb_rows, jn_rows = _run_event_pipes(cache_root, verbose=verbose)
        _jinniu_wiring_ok(jn, cache_root, [r for r in jn_rows if r["sym"] in judged])
        chuji = _stat(sb.summarize, _alpha_rows(
            [r for r in sb_rows if r["sym"] in noise_syms], "chuji", EVENT_H))
        jinniu = _stat(lambda rows: jn.summarize("buy", rows),
                       _alpha_rows([r for r in jn_rows if r["sym"] in noise_syms],
                                   "d_buy", EVENT_H))
        ok_c, suf_c = _noise_arm_state(chuji)
        ok_j, suf_j = _noise_arm_state(jinniu)
        clean_c.append(ok_c)
        clean_j.append(ok_j)
        insuff += int(not (suf_c and suf_j))
    out["noise"] = {"markets": n_markets, "chuji_clean": sum(clean_c),
                    "jinniu_clean": sum(clean_j),
                    "both_clean": int(np.logical_and(clean_c, clean_j).sum()),
                    "insufficient": insuff}
    sweeps = []
    for b in BOUNCE_LEVELS:
        stats: list[dict] = []
        crit = {"alpha": 0, "t": 0, "pos": 0, "nsig": 0}
        for j in range(1, edge_seeds + 1):
            print(f"[calibrate] event 埋边 bounce={b} 种子 {j}/{edge_seeds}", file=sys.stderr)
            tickers = synth.event_market_tickers(seed_shift=CALIB_EDGE_BASE + CALIB_NOISE_BASE * j,
                                                 bounce=b)
            synth.write_cache(cache_root, tickers)
            sb, jn, sb_rows, jn_rows = _run_event_pipes(cache_root, verbose=verbose)
            _jinniu_wiring_ok(jn, cache_root, [r for r in jn_rows if r["sym"] in judged])
            s = _stat(sb.summarize, _alpha_rows(
                [r for r in sb_rows if r["sym"] in edge_syms], "chuji", EVENT_H))
            stats.append(s)
            crit["alpha"] += _gt(s.get("alpha_mean"), EDGE_ALPHA_MIN)
            crit["t"] += _gt(s.get("alpha_t"), EDGE_T_MIN)
            crit["pos"] += _gt(s.get("pos_ratio"), EDGE_POS_MIN)
            crit["nsig"] += int(s.get("n_sig", 0) >= EDGE_NSIG_MIN)
        sweeps.append({"level": b, "seeds": edge_seeds, "detect": sum(map(_event_edge_pass, stats)),
                       "crit": crit, "stats": stats})
    out["edge"] = sweeps
    return out


def calibrate_rps(cache_root: Path, *, n_markets: int, edge_seeds: int) -> dict:
    """rps 校准。对照侧：独立噪声市场（偏移与事件族不重叠）上两条出厂判据
    （|D9−D0|≤1pp、|去重叠 t|≤2）的实测触发率；出厂 validity.py 臂 C 的 naive 重叠 t
    同款触发率一并报——膨胀是公式性质，纯噪声市场上它就该大面积过 2（√20 膨胀的
    实证，Q-20261125-05）。埋边侧：动量系数 0.05→出厂 0.25 扫档，检出=三条阳性判据
    全过（_rps_edge_pass）。"""
    out: dict = {"n_markets": n_markets, "edge_seeds": edge_seeds}
    spreads, t_deo, t_naive = [], [], []
    for k in range(1, n_markets + 1):
        print(f"[calibrate] rps 对照市场 {k}/{n_markets}", file=sys.stderr)
        d = synth.write_cache(cache_root, synth.noise_market_tickers(
            seed_shift=CALIB_RPS_NOISE_BASE + CALIB_NOISE_BASE * k))
        a = _rps_arms(_load_rps_bundle(d))["fwd20"]
        spreads.append(a["d9_d0_spread"])
        t_deo.append(a["ic_t"])
        t_naive.append(a["ic_t_overlap"])
    deo, naive = np.abs(t_deo), np.abs(t_naive)
    out["noise"] = {"markets": n_markets,
                    "spread_fp": int((np.abs(spreads) > RPS_NOISE_SPREAD_MAX).sum()),
                    "t_fp": int((deo > RPS_NOISE_T_MAX).sum()),
                    "naive_fp": int((naive > RPS_NAIVE_T_FLAG).sum()),
                    "both_clean": int(((np.abs(spreads) <= RPS_NOISE_SPREAD_MAX)
                                       & (deo <= RPS_NOISE_T_MAX)).sum()),
                    "t_deo_q": [float(np.quantile(deo, q)) for q in (0.5, 0.9, 1.0)],
                    "t_naive_q": [float(np.quantile(naive, q)) for q in (0.5, 0.9, 1.0)],
                    "spreads": spreads, "t_deoverlap": t_deo, "t_naive": t_naive}
    sweeps = []
    for m in MOM_COEF_LEVELS:
        stats: list[dict] = []
        crit = {"spread": 0, "ic": 0, "t": 0}
        for j in range(1, edge_seeds + 1):
            print(f"[calibrate] rps 埋边 mom_coef={m} 种子 {j}/{edge_seeds}", file=sys.stderr)
            d = synth.write_cache(cache_root, synth.event_market_tickers(
                seed_shift=CALIB_RPS_EDGE_BASE + CALIB_NOISE_BASE * j, mom_coef=m))
            a = _rps_arms(_load_rps_bundle(d))["fwd20"]
            stats.append(a)
            crit["spread"] += _gt(a["d9_d0_spread"], RPS_SPREAD_MIN)
            crit["ic"] += _gt(a["ic_mean"], RPS_IC_MEAN_MIN)
            crit["t"] += _gt(a["ic_t"], RPS_IC_T_MIN)
        sweeps.append({"level": m, "seeds": edge_seeds, "detect": sum(map(_rps_edge_pass, stats)),
                       "crit": crit, "stats": stats})
    out["edge"] = sweeps
    return out


def calibrate_sr(sr_root: Path, *, n_markets: int, edge_seeds: int, n_perm: int) -> dict:
    """SR 校准。对照侧：独立噪声宇宙上六格 p 值的逐格触发率 + 六格全过（出厂「过松」
    判据只在全过时报）的触发率——逐格假阳性它放过，这里量化放了多少（README 已知
    限制的数字化）。埋边侧：动量系数 0.05→出厂 0.20 扫档，检出=六格全过
    （_matrix_all_pass），逐格通过率一并报。"""
    out: dict = {"n_markets": n_markets, "edge_seeds": edge_seeds, "n_perm": n_perm}
    cell_fp = {f"{t}/{r}": 0 for t in TIERS for r in SR_ROWS}
    all_pass_fp = 0
    for k in range(1, n_markets + 1):
        print(f"[calibrate] sr 对照宇宙 {k}/{n_markets}", file=sys.stderr)
        root = synth.write_sr_market(sr_root / "calib-noise", noise_only=True,
                                     seed_shift=CALIB_NOISE_BASE * k)
        wf = build_weekly_frame(root, _sr_spec(), bench_symbol=synth.SR_BENCH,
                                pick_bypass_single=True)
        rows, _ = _sr_matrix(wf, n_perm=n_perm)
        all_pass_fp += int(_matrix_all_pass(rows))
        for t in TIERS:
            for r in SR_ROWS:
                cell_fp[f"{t}/{r}"] += int(_lt(rows[t][r], ALPHA))
    out["noise"] = {"markets": n_markets, "all_pass_fp": all_pass_fp, "cell_fp": cell_fp}
    sweeps = []
    for m in MOM_COEF_LEVELS:
        cells = {f"{t}/{r}": 0 for t in TIERS for r in SR_ROWS}
        detect = 0
        for j in range(1, edge_seeds + 1):
            print(f"[calibrate] sr 埋边 mom_coef={m} 种子 {j}/{edge_seeds}", file=sys.stderr)
            root = synth.write_sr_market(sr_root / "calib-edge", mom_coef=m,
                                         seed_shift=CALIB_EDGE_BASE + CALIB_NOISE_BASE * j)
            wf = build_weekly_frame(root, _sr_spec(), bench_symbol=synth.SR_BENCH,
                                    pick_bypass_single=True)
            rows, _ = _sr_matrix(wf, n_perm=n_perm)
            detect += int(_matrix_all_pass(rows))
            for t in TIERS:
                for r in SR_ROWS:
                    cells[f"{t}/{r}"] += int(_lt(rows[t][r], ALPHA))
        sweeps.append({"level": m, "seeds": edge_seeds, "detect": detect, "cells": cells})
    out["edge"] = sweeps
    return out


def calibrate(cache_root: Path, sr_root: Path, *, n_markets: int = 50, edge_seeds: int = 3,
              n_perm: int = 1000, targets=("event", "sr", "rps"),
              verbose: bool = False) -> dict:
    """多种子校准总入口。测量工具不是闸门：结果供阈值重标与「负结果可信度」评估参考，
    exit code 恒 0。全量约半小时（SR 的置换检验占大头，可降 --n-perm；SR 判定阈值
    α=0.1，n_perm=200 时 p 值分辨率 1/201 仍够用）。"""
    out: dict = {}
    if "event" in targets:
        out["event"] = calibrate_event(cache_root, n_markets=n_markets,
                                       edge_seeds=edge_seeds, verbose=verbose)
    if "sr" in targets:
        out["sr"] = calibrate_sr(sr_root, n_markets=n_markets, edge_seeds=edge_seeds,
                                 n_perm=n_perm)
    if "rps" in targets:
        out["rps"] = calibrate_rps(cache_root, n_markets=n_markets, edge_seeds=edge_seeds)
    return out


def render_calibrate(v: dict) -> str:
    lines = []
    if "event" in v:
        e, nz = v["event"], v["event"]["noise"]
        n = nz["markets"]
        lines.append(f"== calibrate[event] 对照侧 {n} 个独立噪声市场"
                     f"（种子偏移 {CALIB_NOISE_BASE}·k，k≥1，不含阈值标定用的 0 号）")
        lines.append(f"  误报率  chuji 臂 {n - nz['chuji_clean']}/{n}  jinniu 臂 "
                     f"{n - nz['jinniu_clean']}/{n}  双臂全干净 {nz['both_clean']}/{n}"
                     f"  样本不足 {nz['insufficient']}（出厂 2σ 判据名义 ≈5%/臂）")
        for s in e["edge"]:
            lv = f"{s['level'] * 100:.1f}%" + ("（出厂）" if s["level"] == synth.BOUNCE else "")
            c = s["crit"]
            lines.append(f"  埋边 bounce={lv}/日: 检出 {s['detect']}/{s['seeds']}"
                         f"（判据通过 alpha {c['alpha']} t {c['t']} 正率 {c['pos']} "
                         f"信号数 {c['nsig']}，各 /{s['seeds']}）"
                         f"  均值 alpha={_edge_alpha_mean(s['stats']) * 100:+.2f}%")
    if "sr" in v:
        s, nz = v["sr"], v["sr"]["noise"]
        n = nz["markets"]
        lines.append(f"== calibrate[sr] 对照侧 {n} 个独立噪声宇宙（n_perm={s['n_perm']}）")
        lines.append(f"  六格全过（出厂过松判据触发线）: {nz['all_pass_fp']}/{n}")
        cells = "  ".join(f"{k} {cnt}/{n}" for k, cnt in nz["cell_fp"].items())
        lines.append(f"  逐格触发率: {cells}——出厂判据只在六格全过时报，逐格假阳性它不报")
        for sw in s["edge"]:
            lv = f"{sw['level']:.2f}" + ("（出厂）" if sw["level"] == synth.SR_MOM_COEF else "")
            lines.append(f"  埋边 mom_coef={lv}: 检出（六格全过）{sw['detect']}/{sw['seeds']}")
    if "rps" in v:
        r, nz = v["rps"], v["rps"]["noise"]
        n = nz["markets"]
        lines.append(f"== calibrate[rps] 对照侧 {n} 个独立噪声市场"
                     f"（偏移 {CALIB_RPS_NOISE_BASE}+{CALIB_NOISE_BASE}·k）")
        lines.append(f"  误报率  |D9−D0|>1pp: {nz['spread_fp']}/{n}  |去重叠t|>2: "
                     f"{nz['t_fp']}/{n}（名义 ≈5%）  双判据全干净 {nz['both_clean']}/{n}")
        lines.append(f"  [口径对照] naive 重叠 t（出厂 validity.py 臂 C 口径）|t|>2: "
                     f"{nz['naive_fp']}/{n}——|t| 分位 中位/90%/最大 = "
                     f"{nz['t_naive_q'][0]:.1f}/{nz['t_naive_q'][1]:.1f}/{nz['t_naive_q'][2]:.1f}"
                     f" vs 去重叠 {nz['t_deo_q'][0]:.1f}/{nz['t_deo_q'][1]:.1f}/{nz['t_deo_q'][2]:.1f}"
                     "（√20 膨胀的实证）")
        for s in r["edge"]:
            lv = f"{s['level']:.2f}" + ("（出厂）" if s["level"] == synth.MOM_COEF_EVENT else "")
            c = s["crit"]
            lines.append(f"  埋边 mom_coef={lv}: 检出 {s['detect']}/{s['seeds']}"
                         f"（价差过 {c['spread']} IC过 {c['ic']} t过 {c['t']}，各 /{s['seeds']}）")
    return "\n".join(lines)


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
    ap = argparse.ArgumentParser(description="planted 合成对照检查（固定种子回归基线 + 多种子校准）")
    ap.add_argument("target", choices=["sr", "event", "rps", "all", "calibrate"])
    ap.add_argument("--n-perm", type=_positive, default=1000,
                    help="SR vs随机 的置换数，默认 1000；单测用 100（p 值分辨率 1/(n+1)）；"
                         "calibrate 全量跑可降 200")
    ap.add_argument("--sr-root", type=Path, default=DEFAULT_SR_ROOT,
                    help="SR 合成宇宙根目录（须在 data/planted-benchmark 或仓库 data/ 之外）")
    ap.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT,
                    help="事件族 / rps 合成缓存根目录（同上；指向真实缓存会被写守卫拒绝）")
    ap.add_argument("--real-bundle", type=Path, default=None,
                    help="rps：可选，真实 RPS bundle 路径（只读，报 naive t 与去重叠 t）")
    ap.add_argument("--verbose", action="store_true", help="透传底层管道的完整表格输出（默认静默）")
    ap.add_argument("--strict", action="store_true",
                    help="把「既有管道契约偏差」注记也算失败（默认只报不算，exit code 只看三态判定）")
    ap.add_argument("--n-markets", type=_positive, default=50,
                    help="calibrate：对照侧独立市场/宇宙数，默认 50")
    ap.add_argument("--edge-seeds", type=_positive, default=3,
                    help="calibrate：埋边扫档每档独立种子数，默认 3")
    ap.add_argument("--calib-targets", default="event,sr,rps",
                    help="calibrate：跑哪些管道，逗号分隔（默认 event,sr,rps）")
    ap.add_argument("--out-json", type=Path, default=None,
                    help="calibrate：可选，结果 JSON 落盘路径（原始逐市场读数）")
    args = ap.parse_args(argv)
    if args.target == "calibrate":
        targets = tuple(t.strip() for t in args.calib_targets.split(",") if t.strip())
        bad = sorted(set(targets) - {"event", "sr", "rps"})
        if bad:
            ap.error(f"--calib-targets 未知管道：{bad}（可选 event/sr/rps）")
        v = calibrate(args.cache_root, args.sr_root, n_markets=args.n_markets,
                      edge_seeds=args.edge_seeds, n_perm=args.n_perm, targets=targets,
                      verbose=args.verbose)
        print(render_calibrate(v))
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(json.dumps(v, ensure_ascii=False, indent=1, default=float),
                                     encoding="utf-8")
        return 0
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
