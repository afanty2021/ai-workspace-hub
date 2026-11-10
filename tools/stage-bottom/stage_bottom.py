"""通达信「阶段底部出击」公式信号翻译（2026-11-10 用户提供原文，逐行对靶）。

公式原文 → 本模块映射（只翻译可回测部分）：

    LC   = REF(C,1)
    RSI5 = SMA(MAX(C-LC,0),5,1) / SMA(ABS(C-LC),5,1) * 100   # Wilder RSI(5)，SMA 即 1/5 平滑
    TR1  = SUM(MAX(MAX(H-L, |H-LC|), |L-LC|), 10)            # 10 日 TR 累和（SUM 非 Wilder 平滑）
    HD   = H - REF(H,1);  LD = REF(L,1) - L
    DMP  = SUM(IF(HD>0 AND HD>LD, HD, 0), 10)
    DMM  = SUM(IF(LD>0 AND LD>HD, LD, 0), 10)
    PDI  = DMP*100/TR1;  MDI = DMM*100/TR1
    ADX  = MA( |MDI-PDI| / (MDI+PDI) * 100, 5)              # 参数 (10,5)，标准 DMI 是 (14,14)
    AV   = RSI5 + ADX
    WR10 = 100*(HHV(H,10)-C) / (HHV(H,10)-LLV(L,10))        # 威廉 %R：越大越超卖
    NEWVOL = RSI5 - WR10                                    # 命名误导，与成交量无关
    阶段底部 = AV + NEWVOL = 2*RSI5 + ADX - WR10            # 化简真身（三构件高度共线）
    准备 = 阶段底部 < 0                    （状态）
    出击 = CROSS(阶段底部, 0)              （上穿 0，主买入信号）
    KDJ 变体：RSV = EMA((C-LLV(L,9))/(HHV(H,9)-LLV(L,9))*100, 3)
              K = EMA(RSV,3)；D = MA(K,3)  （非标准 KDJ：双 EMA 平滑 + MA 的 D）
    KD 金叉 = CROSS(K,D)；KD 死叉 = CROSS(D,K)

不可回测/无效部分（不影响信号，逐条核实过）：
- DXR := (ADX+REF(ADX,5))/2 + RSI5 —— 定义后未被任何输出引用，死代码。
- 趋势线 := LLV(阶段底部,1) —— 1 期最低恒等于自身；配套 趋势线>230 绿柱：值域上界
  2*100+100-0=300，需 RSI5≈100 且 WR10≈0 的极端连板行情，实际不可达，不回测。
- 0 轴线/COLOR/LINETHICK/STICKLINE 全是画图层。
- 除零语义：TR1=0（10 日一字横盘）、HHV=LLV、HIGHV=LOWV、MDI+PDI=0 时按无效值
  （NaN）处理，比较运算对 NaN 一律 False，与通达信「无效不触发」一致。

回测信号臂（对照设计）：
- chuji     出击 = CROSS(阶段底部,0)                —— 公式主信号
- zhunbei   准备状态第一天（阶段底部 由 >=0 转 <0） —— 公式的「左侧提醒」
- kd_gold   KD 金叉（公式红柱）                     —— 二级确认
- rsi_dn20  RSI5 下穿 20                            —— 裸超卖基线（买深度超卖）
- rsi_up20  RSI5 上穿 20                            —— 裸超卖修复基线（出击的最简近似）
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

WARMUP = 60  # 与 jinniu 口径一致：每票前 N 根不取信号（平滑器种子瞬态 |残差|<1e-5）


# ---------- 通达信基元 ----------

def shift1(x: np.ndarray) -> np.ndarray:
    """REF(x,1)：右移一位，头部填 NaN（比较时 NaN→False，即「无效不触发」）。"""
    out = np.full_like(np.asarray(x, dtype=float), np.nan)
    out[1:] = x[:-1]
    return out


def tdx_sma(x: np.ndarray, n: int, m: int = 1) -> np.ndarray:
    """SMA(X,N,M)：Y=(M*X+(N-M)*Y')/N，种子 Y[0]=X[0]。即 alpha=M/N 的 EWM。"""
    return _ewm(np.asarray(x, dtype=float), m / n)


def tdx_ema(x: np.ndarray, n: int) -> np.ndarray:
    """EMA(X,N)：alpha=2/(N+1)，种子 Y[0]=X[0]。"""
    return _ewm(np.asarray(x, dtype=float), 2.0 / (n + 1))


def _ewm(x: np.ndarray, alpha: float) -> np.ndarray:
    """种子 Y[0]=X[0] 的指数平滑；NaN 输入原位透传（acc 保持），间隙由下游
    roll_mean_valid 的全有效窗要求截断。"""
    y = np.full(len(x), np.nan)
    acc = None
    a = float(alpha)
    for i in range(len(x)):
        v = x[i]
        if np.isnan(v):
            continue  # y[i] 留 NaN，acc 不动
        acc = v if acc is None else a * v + (1.0 - a) * acc
        y[i] = acc
    return y


def roll_sum(x: np.ndarray, n: int) -> np.ndarray:
    """窗口含 NaN（如首根无昨收的 TR）→ 整窗无效（TDX SUM 同语义）。"""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = sliding_window_view(x, n)
        bad = np.isnan(w).any(axis=1)
        out[n - 1:] = np.where(bad, np.nan, w.sum(axis=1))
    return out


def roll_mean(x: np.ndarray, n: int) -> np.ndarray:
    return roll_sum(x, n) / n


def roll_max(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = sliding_window_view(x, n).max(axis=1)
    return out


def roll_min(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = sliding_window_view(x, n).min(axis=1)
    return out


def civil_days(d):
    """YYYYMMDD int64 → 自 epoch 天数（Hinnant 历法；YYYYMMDD 整数差不是天数——
    单年窗口差/10000 只有 0.11「年」，年化会系统性偏 5-11%。
    原 sleeve._civil_days 修根后上移至公共核（评审 2026-11-10 I-1：三脚本 /10000 遗留）。"""
    y, m_, dd = d // 10000, d // 100 % 100, d % 100
    y2 = y - (m_ <= 2)
    era = np.where(y2 >= 0, y2, y2 - 399) // 400
    yoe = y2 - era * 400
    doy = (153 * np.where(m_ > 2, m_ - 3, m_ + 9) + 2) // 5 + dd - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def roll_mean_valid(x: np.ndarray, n: int) -> np.ndarray:
    """MA over n：窗口内全有效才输出（ADX/D 用；TDX 对无效头部同样不产值）。"""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = sliding_window_view(x, n)
        ok = ~np.isnan(w).any(axis=1)
        out[n - 1:][ok] = w[ok].mean(axis=1)
    return out


def safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """除零 → NaN（通达信无效值语义）。"""
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den != 0, num / np.where(den == 0, 1.0, den), np.nan)
    out[~np.isfinite(out)] = np.nan
    return out


def cross_up(a: np.ndarray, b: float | np.ndarray) -> np.ndarray:
    """CROSS(A,B)：昨日 A<=B 且今日 A>B（NaN 参与比较为 False）。"""
    a = np.asarray(a, dtype=float)
    prev = shift1(a)
    if np.isscalar(b):
        return (a > b) & (prev <= b)
    return (a > np.asarray(b)) & (prev <= shift1(np.asarray(b, dtype=float)))


def state_entry(neg: np.ndarray) -> np.ndarray:
    """状态第一天：今日 neg 为 True 且昨日非 True（NaN/False 都算非 True）。"""
    prev = np.zeros(len(neg), dtype=bool)
    prev[1:] = neg[:-1]
    return neg & ~prev


# ---------- 指标与信号 ----------

def stage_bottom_indicators(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """返回 {rsi5, adx, wr10, sb, k, d}；sb=阶段底部=2*RSI5+ADX-WR10。"""
    h, l, c = (np.asarray(v, dtype=float) for v in (high, low, close))
    lc = shift1(c)
    diff = c - lc  # diff[0]=NaN → RSI 头部 NaN
    up = tdx_sma(np.where(diff > 0, diff, 0.0), 5, 1)
    dn = tdx_sma(np.abs(diff), 5, 1)
    rsi5 = safe_div(up * 100.0, dn)

    tr = np.maximum(np.maximum(h - l, np.abs(h - lc)), np.abs(l - lc))
    tr1 = roll_sum(tr, 10)
    hd, ld = h - shift1(h), shift1(l) - l
    dmp = roll_sum(np.where((hd > 0) & (hd > ld), hd, 0.0), 10)
    dmm = roll_sum(np.where((ld > 0) & (ld > hd), ld, 0.0), 10)
    pdi, mdi = safe_div(dmp * 100.0, tr1), safe_div(dmm * 100.0, tr1)
    dx = safe_div(np.abs(mdi - pdi) * 100.0, mdi + pdi)
    adx = roll_mean_valid(dx, 5)

    hh10, ll10 = roll_max(h, 10), roll_min(l, 10)
    wr10 = safe_div((hh10 - c) * 100.0, hh10 - ll10)

    lowv, highv = roll_min(l, 9), roll_max(h, 9)
    rsv = tdx_ema(safe_div((c - lowv) * 100.0, highv - lowv), 3)
    k = tdx_ema(rsv, 3)
    d = roll_mean_valid(k, 3)

    sb = 2.0 * rsi5 + adx - wr10
    return {"rsi5": rsi5, "adx": adx, "wr10": wr10, "sb": sb, "k": k, "d": d,
            "companions_ok": ~(np.isnan(adx) | np.isnan(wr10))}


def companion_valid_events(si: np.ndarray, ind: dict) -> np.ndarray:
    """事件索引过滤：伴随指标（ADX/WR10）有效的子集。

    信号（如 rsi_up20）只要求 RSI5 有效，事件日 ADX/WR10 可为 NaN（横盘段除零）；
    下游做分位切点/分桶前必须先过此 mask，否则 percentile 被 NaN 毒化成 nan
    （本目录同一会话内咬过两次：followup A2 切点、oos_check pass1 切点）。
    """
    return si[ind["companions_ok"][si]]


def stage_bottom_signals(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                         warmup: int = WARMUP) -> dict[str, np.ndarray]:
    """五个信号臂 + 出场信号，全部头部 warmup 根内置 False。"""
    ind = stage_bottom_indicators(high, low, close)
    rsi5, sb, k, d = ind["rsi5"], ind["sb"], ind["k"], ind["d"]
    sigs = {
        "chuji": cross_up(sb, 0.0),
        "zhunbei": state_entry(sb < 0),          # NaN<0 → False，状态第一天
        "kd_gold": cross_up(k, d),
        "kd_dead": cross_up(d, k),
        "rsi_dn20": (rsi5 < 20.0) & (shift1(rsi5) >= 20.0),
        "rsi_up20": cross_up(rsi5, 20.0),
    }
    out = {}
    for name, sig in sigs.items():
        s = np.asarray(sig, dtype=bool).copy()
        s[:warmup] = False
        out[name] = s
    return out


# ---------- 自检 ----------

def _selftest() -> None:
    rng = np.random.default_rng(7)
    # 1) tdx_sma 递归对靶：手工逐根算 5 个点
    x = np.array([3.0, 5.0, 4.0, 6.0, 2.0, 8.0])
    y = tdx_sma(x, 5, 1)
    hand = [3.0]
    for v in x[1:]:
        hand.append((v + 4 * hand[-1]) / 5)
    assert np.allclose(y, hand), (y, hand)

    # 2) 一字横盘 → 全 NaN 透传、无信号
    c = np.full(200, 10.0)
    sigs = stage_bottom_signals(c, c, c)
    assert not any(s.any() for s in sigs.values())

    # 3) V 形底剧情（噪声版）：净阴跌 30 根（-1.5%/日 ±2% 噪声）→ 净反弹 30 根。
    #    注：干净线性阴跌不触发准备——DMI 饱和（MDI=100→ADX=100）抵消超卖项，
    #    这是公式真实特性（强趋势中 ADX 压制信号），不是翻译 bug。
    rng_v = np.random.default_rng(11)
    dn = 100.0 * np.cumprod(1.0 - 0.015 + rng_v.normal(0, 0.02, 30))
    up = dn[-1] * np.cumprod(1.0 + 0.02 + rng_v.normal(0, 0.02, 30))
    close = np.concatenate([np.full(60, 100.0), dn, up])
    high = close * (1 + np.abs(rng_v.normal(0, 0.004, len(close))))
    low = close * (1 - np.abs(rng_v.normal(0, 0.004, len(close))))
    ind = stage_bottom_indicators(high, low, close)
    sigs = stage_bottom_signals(high, low, close)
    zi = np.nonzero(sigs["zhunbei"])[0]
    ci = np.nonzero(sigs["chuji"])[0]
    gi = np.nonzero(sigs["kd_gold"])[0]
    assert len(zi) and len(ci), "V 形底应同时触发准备与出击"
    assert zi[0] < ci[0] <= zi[-1] + 8, "准备应先于出击且间隔不远"
    sb, rsi5 = ind["sb"], ind["rsi5"]
    # 出击日语义：昨日 <=0 今日 >0
    assert (sb[ci] > 0).all() and (sb[ci - 1] <= 0).all()
    # 出击时刻的典型读数：RSI5 处低位区（多数 <50；震荡修复段可到 ~60）
    assert (rsi5[ci] < 60).all(), rsi5[ci]
    # sb 化简式对靶（对有效值）
    ok = ~np.isnan(sb)
    assert np.allclose(sb[ok], (2 * rsi5 + ind["adx"] - ind["wr10"])[ok])
    # kd_gold 晚于或接近出击（双 EMA 平滑滞后）
    if len(gi):
        assert gi[0] >= ci[0] - 2

    # 4) 随机游走冒烟：信号量级合理、因果性成立（出击昨日必 <=0，今日必 >0）
    rets = rng.normal(0, 0.02, 2000)
    close = 100 * np.cumprod(1 + rets)
    high, low = close * (1 + np.abs(rng.normal(0, 0.005, 2000))), close * (1 - np.abs(rng.normal(0, 0.005, 2000)))
    sigs = stage_bottom_signals(high, low, close)
    ind = stage_bottom_indicators(high, low, close)
    ci = np.nonzero(sigs["chuji"])[0]
    assert 5 <= len(ci) <= 400, f"2000 根随机游走出击数异常: {len(ci)}"
    assert (ind["sb"][ci] > 0).all() and (ind["sb"][ci - 1] <= 0).all()
    zi = np.nonzero(sigs["zhunbei"])[0]
    assert (ind["sb"][zi] < 0).all() and ~(ind["sb"][zi - 1] < 0).all()
    print(f"selftest ok: 2000 根随机游走 chuji={len(ci)} zhunbei={len(zi)} "
          f"kd_gold={sigs['kd_gold'].sum()} rsi_dn20={sigs['rsi_dn20'].sum()} rsi_up20={sigs['rsi_up20'].sum()}")


if __name__ == "__main__":
    _selftest()
