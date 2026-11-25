# tools/planted-benchmark/synth.py
"""planted 合成市场生成器（借鉴 Allencake/mit-trader-skill 的 --planted 机制）。

合成市场构成（种子全部固定、全链确定性；本模块只产合成数据）：

- 埋边序列（真实优势），两类优势族对应两类管道：
  - ts_momentum：AR(1) 趋势埋进对数收益（mit-trader 同款公式），rps 横截面的目标边；
  - bottom_reversal：V 型急跌后注入反弹漂移（因果状态机），stage-bottom chuji 的目标边。
- 噪声序列：几何随机游走（基准漂移 BASE_DRIFT、零自相关），阴性对照。
- 配对设计：噪声对照市场与埋边市场共用同一批 eps 种子，只差边项——把边项拆掉
  （momentum=0 / 不注入反弹）即精确得到噪声市场，对照是纯粹的。
- 不设漂移对照：mit-trader 的 NOISE_C（只漂移、零自相关）是单资产时序动量对
  「敞口匹配置换零假设」的对照；本库三管道的零假设结构下它没有鉴别力——事件族的
  alpha = 信号前瞻均值 − 同票基础率，漂移代数抵消；SR 全体同漂移时 vs随机 的零假设
  与噪声宇宙等价；rps 是横截面排名。一个永远不会变红的对照只会误导（max 评审 r4 I-7）。

校准与纪律：
- 日波动 σ=0.02（A 股日线量级）；单日收益截断 ±9.5%（涨跌停内，避开 stage-bottom/jinniu
  的 12% 除权过滤与 SR 的 30% corrupt-week 防护——合成数据不得触发数据质量闸门）；
- 日期 = bdate_range(end=ANCHOR) 固定锚点，不用 date.today()（对齐仓库 today 注入纪律，
  同种子全链可复现）；
- amount ≈3e8 元：过 SR 流动性闸门（周均额 ≥5000 万）；SR 的 ETF 行由 write_sr_market 自给；
- 价格量级不真实：动量项的积分是随机游走，合成价格可跨多个数量级（约 1e-7 ~ 1e4）。
  落盘一律用有效数字量化（_q），不得定点位舍入（定点位会把极小价 round 成 0.0 →
  下游除零 + fwd 收益天文数字污染分位价差）。含绝对价位/成交额闸门的工具（如
  weak_scan 的 MIN_PRICE）不能直接复用本市场；
- 写守卫（guard_root）：合成票码与真实缓存可能同名，写入只允许落在
  <repo>/data/planted-benchmark/ 或仓库 data/ 之外的目录。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data"
SYNTH_HOME = DATA_DIR / "planted-benchmark"   # 仓库内唯一允许落合成数据的目录

ANCHOR = "2026-11-20"          # 固定锚点日（周五）；改锚点 = 换市场，全部读数随之失效
SOURCE = "planted-benchmark"
VOL = 0.02                     # A 股日波动校准
PHI = 0.97                     # AR(1) 趋势衰减系数（mit-trader 同款，半衰期 ~23 日）
DAILY_CLIP = 0.095             # 单日对数收益截断 ±9.5%（简单收益 ≤9.97%，涨跌停内 + 避开 12%
                               # 除权过滤 / 30% corrupt-week——合成数据不得触发数据质量闸门）
BASE_DRIFT = 0.0006            # 全部序列的基准漂移（≈15%/年）
N_EVENT_BARS = 2000            # 事件研究族 / rps 面板每票 bar 数（~8 年，够 MA250/RPS250）
N_SR_WEEKS_BARS = 1800         # SR 合成指数/ETF 的日线 bar 数

# ---------- 事件研究族 / rps 共用的合成票池（59 只 = 12 反弹 + 12 动量 + 35 噪声） ----------
# 代码取真实缓存（7482 票）完全空闲的 609xxx / 309xxx 段（2026-11-25 核对），同时满足
# stage-bottom/jinniu 的 UNIVERSE_RE 白名单；首版用 600900/000900/601100 段时有 34 只与
# 真实缓存同名（r4 I-1）。段位空闲不是保证，写守卫才是硬防线。
N_TICKERS = 59

EDGE_BOUNCE = [f"609{900 + i}.SH" for i in range(12)]   # V 型反弹埋边（chuji 的目标边）
EDGE_MOM = [f"309{900 + i}.SZ" for i in range(12)]      # 时序动量埋边（rps 的目标边；
                                                        # 对事件研究族不判定——动量票不是
                                                        # 超卖修复信号的优势族）
NOISE = [f"609{100 + i}.SH" for i in range(35)]         # 纯噪声（阴性对照）

# 种子分配：族间隔离，族内有序（i → 基数 + i）；噪声对照市场复用同一批种子（配对）
SEED_BOUNCE, SEED_MOM, SEED_NOISE = 1000, 2000, 4000

# 埋边参数（改动任一参数 = 换市场，须重跑全链并重新标定 run_check 的阈值）
# 形状取舍：首版用缓坡下跌（−10%/20 日），下跌途中链式信号反复点火、FILTER(5) 又压掉
# 反弹首日的信号，对不准注入窗；改成 V 型急跌（短而陡）后 chuji 能稳定落在注入段内。
# 这是开发期一次性观察，数字未留档；现行读数以 run_check.py event 的输出为准。
MOM_COEF_EVENT = 0.25           # rps 面板动量边的强度
DROP = -0.08                    # 底部反转触发：过去 lookback 日累计对数收益 < DROP
DROP_LOOKBACK = 8
BOUNCE = 0.01                   # 反弹注入漂移 /日（×10 日 ≈ +10%/episode）
BOUNCE_DAYS = 10
BOUNCE_COOL = 8                 # 反弹结束后冷却日数（防 episode 重叠）


def _q(x, sig: int = 6) -> float:
    """有效数字量化（非定点位）：合成价格可跨多个数量级，定点位舍入会把极小价 round
    成 0.0（下游 adjust_close 除零 + fwd 收益天文数字污染分位价差）。量具全用比值，
    绝对量级不进任何闸门。"""
    return float(f"{float(x):.{sig}g}")


def guard_root(root: Path) -> Path:
    """写守卫（r4 I-1）：合成数据只允许落 <repo>/data/planted-benchmark/ 或仓库 data/
    之外。write_cache 以 "w" 打开同名文件，根目录一旦误指真实缓存（如
    data/wyckoff/daily），一次旗标误传就会覆盖真实票文件、污染日报 cron 的输入。"""
    r = Path(root).expanduser().resolve()
    data, home = Path(DATA_DIR).resolve(), Path(SYNTH_HOME).resolve()
    in_data = r == data or data in r.parents
    in_home = r == home or home in r.parents
    if in_data and not in_home:
        raise SystemExit(
            f"拒绝写入 {r}：合成数据只能落 {home} 或仓库 data/ 之外的目录"
            "（max 评审 r4 I-1 写守卫）")
    return r


def daily_returns(seed: int, n: int, *, drift: float = BASE_DRIFT, vol: float = VOL,
                  momentum: float = 0.0) -> np.ndarray:
    """对数收益 r_t = drift + eps_t + momentum*trend_t；trend_t = PHI*trend_{t-1} + eps_t
    （AR(1) 趋势埋边，momentum>0 制造真实正自相关）。eps~N(0,vol²) i.i.d.，
    固定种子可复现；截断 ±DAILY_CLIP。"""
    rng = np.random.default_rng(seed)
    eps = rng.standard_normal(n) * vol
    r = np.empty(n)
    trend = 0.0
    for t in range(n):
        trend = PHI * trend + eps[t]
        r[t] = drift + eps[t] + momentum * trend
    return np.clip(r, -DAILY_CLIP, DAILY_CLIP)


def _bounce_path(seed: int, n: int, *, drift: float = BASE_DRIFT, vol: float = VOL,
                 drop: float = DROP, lookback: int = DROP_LOOKBACK, bounce: float = BOUNCE,
                 bounce_days: int = BOUNCE_DAYS, cool_days: int = BOUNCE_COOL):
    """底部反转状态机唯一实现：返回 (r, mask)。收益 = drift + eps（与 daily_returns 同种子、
    同漂移，对照市场只差 bounce 项）+ 反弹注入。触发用已实现收益 r（含已注入 bounce，
    因果）——mask 是注入窗的一等概念（测试与诊断用它对准信号/注入位置）。"""
    rng = np.random.default_rng(seed)
    eps = rng.standard_normal(n) * vol
    r = np.empty(n)
    mask = np.zeros(n, dtype=bool)
    state = cool = 0
    for t in range(n):
        r_t = drift + eps[t]
        injected = False
        if state > 0:
            r_t += bounce
            state -= 1
            injected = True
        elif cool > 0:
            cool -= 1
        elif t >= lookback and r[t - lookback:t].sum() < drop:
            state, cool = bounce_days, cool_days
            r_t += bounce
            state -= 1                      # 当日即反弹第 1 天
            injected = True
        r[t] = r_t
        mask[t] = injected                  # 显式记录注入（不能用 r_t != eps[t]：还有漂移项）
    return np.clip(r, -DAILY_CLIP, DAILY_CLIP), mask


def bottom_reversal_returns(seed: int, n: int, **kw) -> np.ndarray:
    """V 型急跌后注入反弹漂移（因果状态机，只用过去收益判定，固定种子确定性）。

    过去 lookback 日累计收益 < drop 且不在反弹/冷却态 → 注入 +bounce/日 × bounce_days，
    随后冷却 cool_days 日。真实优势 = 急跌后有正期望修复；截断同 daily_returns。"""
    return _bounce_path(seed, n, **kw)[0]


def bounce_mask(seed: int, n: int, **kw) -> np.ndarray:
    """反弹注入 mask（True = 该日收益含 bounce 注入）。触发依赖已实现路径，
    bounce 参数不同则 mask 不同（反馈语义）。"""
    return _bounce_path(seed, n, **kw)[1]


def ohlc_frame(seed: int, n: int, gen: str = "daily", **kw):
    """收益序列 → (dates, open, high, low, close)。

    开=昨收（无跳空）；high/low = max/min(open,close)×(1±u)，u~U(0,vol/2)——
    保留 HHV/LLV/TR 的日内毛刺语义，不触碰任何闸门阈值。
    gen="daily" 走 daily_returns（kw 含 momentum/drift），gen="bounce" 走 bottom_reversal_returns。
    日内毛刺用独立子流 default_rng([seed, 1])：首版用 seed+1，与邻票（seed+1）的收益流同源。"""
    fn = daily_returns if gen == "daily" else bottom_reversal_returns
    r = fn(seed, n, **kw)
    close = 100.0 * np.exp(np.cumsum(r))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    u = np.random.default_rng([seed, 1]).uniform(0.0, VOL / 2, n)
    high = np.maximum(open_, close) * (1 + u)
    low = np.minimum(open_, close) * (1 - u)
    dates = pd.bdate_range(end=ANCHOR, periods=n)
    return dates, open_, high, low, close


def jsonl_rows(seed: int, n: int, gen: str = "daily", *, base_amount: float = 3e8, **kw):
    """ohlc_frame → hub 日线缓存同构 jsonl 行列表（date/open/high/low/close/volume/amount/source）。"""
    dates, o, hgh, low, c = ohlc_frame(seed, n, gen, **kw)
    rng = np.random.default_rng([seed, 2])
    volume = rng.uniform(1e6, 4e6, n)              # 手（与价格不自洽，见模块头「价格量级不真实」）
    amt_mult = rng.uniform(0.7, 1.3, n)
    return [{"date": d.strftime("%Y-%m-%d"),
             "open": _q(oo), "high": _q(hh), "low": _q(ll), "close": _q(cc),
             "volume": round(float(v), 0), "amount": round(float(a), 0),
             "source": SOURCE}
            for d, (oo, hh, ll, cc), v, a
            in zip(dates, zip(o, hgh, low, c), volume, base_amount * amt_mult)]


def write_cache(cache_root: Path, tickers: dict[str, dict]) -> Path:
    """按 {sym: jsonl_rows kwargs} 写 <cache_root>/<sym>.jsonl。

    先过写守卫；目录里已有的 *.jsonl 若是本模块上一轮写的（首行带 SOURCE）则清掉
    （票池换人后旧票不得静默进入横截面），不是本模块写的直接拒绝（不清理、不混写）。"""
    cache_root = guard_root(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    for old in cache_root.glob("*.jsonl"):
        with open(old) as fh:
            head = fh.readline()
        if SOURCE in head:
            old.unlink()
        else:
            raise SystemExit(f"拒绝写入 {cache_root}：{old.name} 不是本模块产出的，不清理不混写")
    for sym, kw in tickers.items():
        rows = jsonl_rows(**kw)
        with open(cache_root / f"{sym}.jsonl", "w") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return cache_root


def event_market_tickers(n_bars: int = N_EVENT_BARS, *, bounce: float | None = None,
                         mom_coef: float | None = None, seed_shift: int = 0) -> dict[str, dict]:
    """事件研究族 + rps 共用的 59 只合成市场。

    rps 判定用 EDGE_MOM（12 只动量票）vs 全体；事件族判定用 EDGE_BOUNCE（12 只反弹票）
    vs NOISE（35 只）；两族互不判对方的边。
    calibrate（多种子校准）用：bounce/mom_coef 扫边强度，seed_shift 平移全部种子造
    独立市场。None 哨兵而非默认参数绑定——测试 monkeypatch 模块常数必须继续生效；
    出厂参数下 kwargs 与首版逐字节等价（bounce=BOUNCE 显式写出即默认路径）。"""
    bounce = BOUNCE if bounce is None else bounce
    mom_coef = MOM_COEF_EVENT if mom_coef is None else mom_coef
    tickers = {}
    for i, sym in enumerate(EDGE_BOUNCE):
        tickers[sym] = dict(seed=SEED_BOUNCE + i + seed_shift, n=n_bars, gen="bounce", bounce=bounce)
    for i, sym in enumerate(EDGE_MOM):
        tickers[sym] = dict(seed=SEED_MOM + i + seed_shift, n=n_bars, momentum=mom_coef)
    for i, sym in enumerate(NOISE):
        tickers[sym] = dict(seed=SEED_NOISE + i + seed_shift, n=n_bars)
    return tickers


def noise_market_tickers(n_bars: int = N_EVENT_BARS, *, seed_shift: int = 0) -> dict[str, dict]:
    """rps 阴性对照市场：与 event_market_tickers 同票码、同 eps 种子，只去掉两个边项
    （RPS 是横截面排名，必须整市场换掉才得到零优势横截面）。seed_shift 同
    event_market_tickers（calibrate 用它造独立噪声市场测误报率）。"""
    tickers = {}
    for i, sym in enumerate(EDGE_BOUNCE):
        tickers[sym] = dict(seed=SEED_BOUNCE + i + seed_shift, n=n_bars)
    for i, sym in enumerate(EDGE_MOM):
        tickers[sym] = dict(seed=SEED_MOM + i + seed_shift, n=n_bars)
    for i, sym in enumerate(NOISE):
        tickers[sym] = dict(seed=SEED_NOISE + i + seed_shift, n=n_bars)
    return tickers


# ---------- SR（sector-rotation）合成宇宙 ----------

SR_N = 12
SR_EDGE = (3, 5, 7)                # 出厂配置：SI03/SI05/SI07 埋动量边（k=3 持仓）
SR_MOM_COEF = 0.20                 # SR 动量边的强度
SR_SEED = 6000                     # 12 个行业共用的 eps 种子基数（埋边/噪声宇宙相同，配对）
SR_BENCH_SEED = 7000
SR_ETF = lambda i: f"PLANTED-ETF-{i:02d}"     # noqa: E731  每成员单 ETF 候选；合成名不与真实 series 同名
SR_IDX = lambda i: f"SI{i:02d}"              # noqa: E731
SR_BENCH = "PLANTED-BENCH"         # build_weekly_frame 的 bench_symbol（须显式传入）


def _index_rows(seed: int, n: int, *, momentum: float = 0.0):
    """指数序列：build_weekly_frame 只读 close（+可选 volume）。"""
    dates, _, _, _, c = ohlc_frame(seed, n, "daily", momentum=momentum)
    rng = np.random.default_rng([seed, 3])
    return [{"date": d.strftime("%Y-%m-%d"), "close": _q(x),
             "volume": round(float(v), 0), "source": SOURCE}
            for d, x, v in zip(dates, c, rng.uniform(5e5, 2e6, n))]


def _etf_rows_from_index(idx_rows: list[dict], seed: int):
    """ETF 与指数逐日收益完全相同（理想跟踪，隔离「ETF 跟踪误差」变量；
    ETF 价格 = 指数/100，量纲不影响任何闸门——闸门全用比值）。"""
    rng = np.random.default_rng([seed, 4])
    out = []
    prev_c = None
    for row in idx_rows:
        c = row["close"] / 100.0
        o = prev_c if prev_c is not None else c
        out.append({"date": row["date"], "open": _q(o), "high": _q(max(o, c)),
                    "low": _q(min(o, c)), "close": _q(c),
                    "volume": row["volume"], "amount": round(3e8 * rng.uniform(0.8, 1.2), 0),
                    "source": SOURCE})
        prev_c = c
    return out


def write_sr_market(root: Path, *, n_bars: int = N_SR_WEEKS_BARS,
                    noise_only: bool = False, mom_coef: float | None = None,
                    seed_shift: int = 0) -> Path:
    """写 SR 合成宇宙：sector/series/<指数>.jsonl + market/series/<ETF>.jsonl + bench。

    - 默认：12 行业中 SR_EDGE 埋动量边（阳性对照）；
    - noise_only=True：同种子、不加动量项（阴性对照——与埋边宇宙只差边项）；
    - calibrate（多种子校准）用：mom_coef 扫边强度，seed_shift 造独立宇宙。
      mom_coef 用 None 哨兵读模块常数（测试 monkeypatch synth.SR_MOM_COEF 必须继续生效）。"""
    root = guard_root(root)
    mom_coef = SR_MOM_COEF if mom_coef is None else mom_coef
    (root / "sector" / "series").mkdir(parents=True, exist_ok=True)
    (root / "market" / "series").mkdir(parents=True, exist_ok=True)

    def _dump(path: Path, rows: list[dict]) -> None:
        with open(path, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    for i in range(SR_N):
        kw = dict(seed=SR_SEED + i + seed_shift,
                  momentum=0.0 if noise_only or i not in SR_EDGE else mom_coef)
        idx_rows = _index_rows(n=n_bars, **kw)
        _dump(root / "sector" / "series" / f"{SR_IDX(i)}.jsonl", idx_rows)
        _dump(root / "market" / "series" / f"{SR_ETF(i)}.jsonl",
              _etf_rows_from_index(idx_rows, SR_SEED + i + seed_shift))
    _dump(root / "market" / "series" / f"{SR_BENCH}.jsonl",
          _index_rows(SR_BENCH_SEED + seed_shift, n_bars))   # bench = 独立噪声序列，两宇宙共用
    return root
