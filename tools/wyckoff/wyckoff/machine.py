"""威科夫示意图状态机（纯逻辑，无 I/O、无时钟——所有日期来自数据行）。

移植源：tools/wyckoff/reference/lunqfx-wyckoff.pine（TradingView LunqFX 开源脚本，
2026-11-07 用户手拷全文，逐行对靶）。五个 stage 与原脚本 1:1 对应：
0 搜索 climax → 1 Phase A（climax 已出，等 AR）→ 2 Phase B（区间 + ST + spring 池）
→ 3 Phase C（spring/UTAD 已确认）→ 4/5 Phase D/E（SOS 后目标与失效）。

对靶后的关键语义（v1 猜测版错误之处，v2 已修正）：
- ATR = Wilder RMA(50)（非 SMA14）；前 period-1 根 na，机器整体被 not na(atr) 门控；
- climax 延伸：WAIT_AR 内任何新影线极值都延伸 ext，无需重新满足 climax 三条件；
- AR 超时 = climax_lookback 根自极值 bar（非 range_max）；AR 行程/高度阈值用确认 bar ATR；
- Spring/UTAD 不需要 ST 先成立；minRange 之前收回的破位 = 无事件（区间继续）；
- 失败深度 = 收盘越过 climax 侧超区间高度 fail_depth_frac（影线深度不判）；
- minRange 之前的深破位/突破/pend 超时 → 丢弃不计（evDrop）；之后 → failed（计入）；
- 只有一个 spring：确认后失效位 = spring 极值被收盘穿越；spring 态超时自极值 bar 起；
- SOS 与 pending spring 同 bar：SOS 优先，spring 不确认，inv = climax 极值；
- MARKUP 中 T2 命中与收盘失效同 bar：T2 优先（complete）；
- 结束当 bar 可立即再开新示意图（同 bar climax 再入，while-redispatch 实现）；
- volume SMA20 含当前 bar；newLo/newHi 窗口含当前 bar（≤ 语义）。

保留的移植近似（与原脚本的已知差异，低影响）：
- 派发 = 价格取负镜像后跑同一套吸筹逻辑（原脚本 dir 乘子逐条对称，镜像等价）；
  原脚本同 bar 同中 SC/BC 用蜡烛色裁决——窗口最低低点与最高高点不可能同时成立，未移植；
- 两类独立扫全 history 后按「一次一个示意图」时间重叠去重（保留先启动者），
  近似原脚本单机单示意图的完整时序（含同 bar 再入）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .params import Params

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass
class Event:
    type: str          # SC/BC/AR/ST/SPRING/UTAD/SOS/SOW/LPS/LPSY/T1/T2 + 终态名
    bar: int           # 判定发生的 bar（pivot 事件 = 确认 bar，非 pivot 本身）
    date: str
    level: float | None = None
    pivot_bar: int | None = None  # pivot/极值事件的本体 bar


@dataclass
class Schematic:
    kind: str                  # 'accum' | 'dist'
    outcome: str               # complete / failed / expired / dropped
    outcome_detail: str        # t2 / breakdown_in_range / breakdown_after_spring /
                               # invalidated_after_sos / expired_range /
                               # expired_after_spring / expired_markup / vturn /
                               # early_break / ar_too_tall / ar_timeout
    sc_bar: int
    sc_date: str
    sc_level: float            # SC 低点（派发为 BC 高点）
    ar_pivot_bar: int = -1
    ar_confirm_bar: int = -1
    ar_date: str = ""
    ar_level: float = 0.0      # AR pivot 价（creek/ice）
    range_bottom: float = 0.0
    range_top: float = 0.0
    st: Event | None = None
    spring: Event | None = None        # 原脚本只跟踪一个 spring
    sos: Event | None = None
    lps: Event | None = None
    t1: float | None = None
    t2: float | None = None
    invalid: float | None = None
    t1_hit_bar: int | None = None
    height_atr: float | None = None
    end_bar: int = -1
    end_date: str = ""
    range_len: int | None = None   # SC→SOS 的 bar 数
    events: list[Event] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        """进 track record 的「完成区间」：complete/failed/expired（dropped 不算）。"""
        return self.outcome in ("complete", "failed", "expired")


# ---------------------------------------------------------------------------
# 因果预计算
# ---------------------------------------------------------------------------


def _atr_rma(rows: list[Bar], period: int) -> list[float | None]:
    """ta.atr(period)：Wilder RMA。前 period-1 根 None；第 period-1 根 = TR 的 SMA
    播种（Pine rma 首值口径），此后 atr += (tr - atr)/period。"""
    out: list[float | None] = [None] * len(rows)
    prev_atr: float | None = None
    seed: list[float] = []
    for i, r in enumerate(rows):
        if i == 0:
            tr = r.high - r.low
        else:
            prev_close = rows[i - 1].close
            tr = max(r.high - r.low, abs(r.high - prev_close), abs(r.low - prev_close))
        if i < period - 1:
            seed.append(tr)
        elif i == period - 1:
            seed.append(tr)
            prev_atr = sum(seed) / period
            out[i] = prev_atr
        else:
            assert prev_atr is not None
            prev_atr = prev_atr + (tr - prev_atr) / period
            out[i] = prev_atr
    return out


def _volma20_incl(vol: list[float | None]) -> list[float | None]:
    """ta.sma(nz(volume), 20)：含当前 bar。i<19 为 None（Pine sma 未满窗返回 na；
    本机 atr 门控 ≥49 根后才开跑，实际总满窗）。"""
    out: list[float | None] = []
    vals = [v if v else 0.0 for v in vol]  # nz 语义：None/0 → 0
    for i in range(len(vol)):
        if i < 19:
            out.append(None)
        else:
            out.append(sum(vals[i - 19: i + 1]) / 20)
    return out


def _pivot_high_flags(high: list[float], k: int) -> list[bool]:
    n = len(high)
    flags = [False] * n
    for p in range(k, n - k):
        if all(high[p] > high[p - j] and high[p] > high[p + j] for j in range(1, k + 1)):
            flags[p] = True
    return flags


def _pivot_low_flags(low: list[float], k: int) -> list[bool]:
    n = len(low)
    flags = [False] * n
    for p in range(k, n - k):
        if all(low[p] < low[p - j] and low[p] < low[p + j] for j in range(1, k + 1)):
            flags[p] = True
    return flags


# ---------------------------------------------------------------------------
# 状态机（吸筹方向；派发用镜像进入）
# ---------------------------------------------------------------------------

_IDLE, _WAIT_AR, _RANGE, _SPRUNG, _MARKUP = "IDLE", "WAIT_AR", "RANGE", "SPRUNG", "MARKUP"


def _is_climax(low: list[float], high: list[float], vol: list[float | None],
               volma: list[float | None], atr: list[float | None], t: int, p: Params) -> bool:
    lb = p.climax_lookback
    if t - lb + 1 < 0 or atr[t] is None or atr[t] <= 0:
        return False
    if low[t] > min(low[t - lb + 1: t + 1]):  # low <= 窗口最低（窗含当前 bar）
        return False
    if (high[t] - low[t]) < p.climax_range_atr * atr[t]:
        return False
    avg = volma[t]
    if avg is not None and avg > 0:  # hasVol
        if (vol[t] or 0.0) < p.climax_vol_mult * avg:
            return False
    return True


def _detect_accum(rows: list[Bar], p: Params, kind: str) -> list[Schematic]:
    n = len(rows)
    high = [r.high for r in rows]
    low = [r.low for r in rows]
    close = [r.close for r in rows]
    vol = [r.volume for r in rows]
    atr = _atr_rma(rows, p.atr_period)
    volma = _volma20_incl(vol)
    k = p.swing_strength
    piv_hi = _pivot_high_flags(high, k)
    piv_lo = _pivot_low_flags(low, k)

    results: list[Schematic] = []
    state = _IDLE
    resume_from = 0
    sch: Schematic | None = None
    # WAIT_AR 可变极值（原脚本 ext/extBar）
    ext = 0.0
    ext_bar = -1
    # RANGE 区间变量（原脚本 cs/bs/rngH + pend 系列）
    cs = bs = height = 0.0
    pend = False
    pend_n = 0
    pend_ext = 0.0
    pend_ext_bar = -1

    def date_of(i: int) -> str:
        return rows[i].date

    def emit(s: Schematic, outcome: str, detail: str, end: int) -> None:
        s.outcome = outcome
        s.outcome_detail = detail
        s.end_bar = end
        s.end_date = date_of(end)
        s.events.append(Event("DROPPED" if outcome == "dropped" else outcome.upper(),
                              end, date_of(end)))
        results.append(s)

    for t in range(n):
        if atr[t] is None:  # 原脚本 if barstate.isconfirmed and not na(atr)
            continue
        # 同 bar 再入：终态落盘后 stage 归 0，原脚本当 bar 可继续搜新 climax
        redispatch = True
        while redispatch:
            redispatch = False

            if state == _IDLE:
                if t < resume_from:
                    break
                if _is_climax(low, high, vol, volma, atr, t, p):
                    sch = Schematic(kind=kind, outcome="", outcome_detail="",
                                    sc_bar=t, sc_date=date_of(t), sc_level=low[t])
                    sch.events.append(Event("SC", t, date_of(t), low[t]))
                    ext, ext_bar = low[t], t
                    pend, pend_n = False, 0
                    state = _WAIT_AR
                break

            assert sch is not None
            age = t - sch.sc_bar
            early = age < p.min_range_len

            # ── stage 4/5：目标、失效、LPS ──
            if state == _MARKUP:
                hit_t2 = high[t] >= sch.t2
                # hitMax 更新在失效判定之前：失效 bar 上命中 T1 也计入 track record
                if not hit_t2 and sch.t1_hit_bar is None and high[t] >= sch.t1:
                    sch.t1_hit_bar = t
                    sch.events.append(Event("T1", t, date_of(t), sch.t1))
                if hit_t2:  # T2 优先于收盘失效（原脚本顺序）
                    if sch.t1_hit_bar is None:  # 原脚本 hitMax=2 → rT1 按 ≥1 计
                        sch.t1_hit_bar = t
                    sch.events.append(Event("T2", t, date_of(t), sch.t2))
                    emit(sch, "complete", "t2", t)
                    resume_from = t
                    redispatch = True
                elif close[t] < sch.invalid:
                    emit(sch, "failed", "invalidated_after_sos", t)
                    resume_from = t
                    redispatch = True
                elif t - sch.sos.bar > p.markup_max_bars:
                    emit(sch, "expired", "expired_markup", t)
                    resume_from = t
                    redispatch = True
                if not redispatch and sch.lps is None:
                    q = t - k
                    if (q > sch.sos.bar and piv_lo[q]
                            and low[q] > (sch.range_top + sch.range_bottom) / 2):
                        sch.lps = Event("LPS", t, date_of(t), low[q], pivot_bar=q)
                        sch.events.append(sch.lps)

            # ── stage 2/3：ST 先判 → SOS 共用判定 → spring 态 / 区间态分支 ──
            elif state in (_RANGE, _SPRUNG):
                if state == _RANGE and not pend and sch.st is None:
                    q = t - k
                    if q > sch.ar_pivot_bar and piv_lo[q]:
                        d = low[q] - cs
                        if 0 <= d <= p.st_zone_frac * height:
                            sch.st = Event("ST", t, date_of(t), low[q], pivot_bar=q)
                            sch.events.append(sch.st)
                if close[t] > bs:  # SOS（同 bar 优先于 spring：pend 作废，inv 用 cs）
                    if early:
                        emit(sch, "dropped", "vturn", t)
                        resume_from = t
                        redispatch = True
                    else:
                        h = sch.range_top - sch.range_bottom
                        sch.t1 = bs + h
                        sch.t2 = bs + 2 * h
                        sch.invalid = sch.spring.level if sch.spring else cs
                        sch.sos = Event("SOS", t, date_of(t), close[t])
                        sch.events.append(sch.sos)
                        sch.range_len = t - sch.sc_bar
                        state = _MARKUP
                elif state == _SPRUNG:
                    if close[t] < sch.spring.level:  # 收盘越过 spring 极值
                        emit(sch, "failed", "breakdown_after_spring", t)
                        resume_from = t
                        redispatch = True
                    elif t - sch.spring.pivot_bar > p.range_max_bars:
                        emit(sch, "expired", "expired_after_spring", t)
                        resume_from = t
                        redispatch = True
                else:  # stage 2：spring 池 / 深破 / pend / 超时
                    if pend:
                        pend_n += 1
                        if low[t] < pend_ext:
                            pend_ext = low[t]
                            pend_ext_bar = t
                        if close[t] >= cs:  # 收回 → spring（early 不计，区间继续）
                            pend = False
                            if not early:
                                sch.spring = Event("SPRING", t, date_of(t), pend_ext,
                                                   pivot_bar=pend_ext_bar)
                                sch.events.append(sch.spring)
                                state = _SPRUNG
                        elif ((cs - close[t]) > p.fail_depth_frac * height
                              or pend_n > p.spring_max_out):
                            if early:
                                emit(sch, "dropped", "early_break", t)
                            else:
                                emit(sch, "failed", "breakdown_in_range", t)
                            resume_from = t
                            redispatch = True
                    elif low[t] < cs:  # 影线破 climax 侧
                        if close[t] >= cs:  # 同 bar 收回 → spring（early 不计）
                            if not early:
                                sch.spring = Event("SPRING", t, date_of(t), low[t],
                                                   pivot_bar=t)
                                sch.events.append(sch.spring)
                                state = _SPRUNG
                        elif (cs - close[t]) > p.fail_depth_frac * height:
                            # 收盘深破（影线深度不判）
                            if early:
                                emit(sch, "dropped", "early_break", t)
                            else:
                                emit(sch, "failed", "breakdown_in_range", t)
                            resume_from = t
                            redispatch = True
                        else:
                            pend = True
                            pend_n = 1
                            pend_ext = low[t]
                            pend_ext_bar = t
                    if not redispatch and state == _RANGE and age > p.range_max_bars:
                        emit(sch, "expired", "expired_range", t)
                        resume_from = t
                        redispatch = True

            # ── stage 1：climax 延伸直到 AR 成形 ──
            elif state == _WAIT_AR:
                if low[t] < ext:  # 任何新低都延伸（无需 climax 条件）
                    ext = low[t]
                    ext_bar = t
                q = t - k
                ar_ok = (q > ext_bar and piv_hi[q]
                         and (high[q] - ext) >= p.min_ar_atr * atr[t])
                if ar_ok:
                    rally = high[q] - ext
                    if rally > p.max_range_atr * atr[t]:
                        emit(sch, "dropped", "ar_too_tall", t)
                        resume_from = t
                        redispatch = True
                    else:
                        sch.ar_pivot_bar, sch.ar_confirm_bar = q, t
                        sch.ar_date, sch.ar_level = date_of(q), high[q]
                        sch.range_bottom, sch.range_top = ext, high[q]
                        cs, bs, height = ext, high[q], high[q] - ext
                        sch.height_atr = height / atr[t]
                        sch.events.append(Event("AR", t, date_of(t), high[q], pivot_bar=q))
                        state = _RANGE
                        pend = False
                elif t - ext_bar > p.climax_lookback:  # AR 超时（trendLen 自极值 bar）
                    emit(sch, "dropped", "ar_timeout", t)
                    resume_from = t
                    redispatch = True

            if redispatch:
                state = _IDLE
                sch = None
                pend = False

    # 数据末尾仍未终态的示意图：原脚本 track record 只统计完成区间，不落盘
    return results


# ---------------------------------------------------------------------------
# 镜像（派发）与合并
# ---------------------------------------------------------------------------

_DIST_RELABEL = {"SC": "BC", "SPRING": "UTAD", "SOS": "SOW", "LPS": "LPSY"}


def _mirror_rows(rows: list[Bar]) -> list[Bar]:
    return [Bar(r.date, -r.open, -r.low, -r.high, -r.close, r.volume) for r in rows]


def _flip_schematic(s: Schematic) -> Schematic:
    """把镜像坐标系里的吸筹示意图翻回真实价格的派发示意图。"""
    s.kind = "dist"
    s.sc_level = -s.sc_level
    s.ar_level = -s.ar_level
    s.range_bottom, s.range_top = -s.range_top, -s.range_bottom
    if s.t1 is not None:
        s.t1 = -s.t1
    if s.t2 is not None:
        s.t2 = -s.t2
    if s.invalid is not None:
        s.invalid = -s.invalid
    for ev in s.events:
        ev.type = _DIST_RELABEL.get(ev.type, ev.type)
        if ev.level is not None:
            ev.level = -ev.level
    # st/spring/sos/lps 与 events 里的 Event 是同一对象（append 同一实例），
    # 上面的循环已翻转/改名，这里不能再翻一遍。
    return s


def detect(rows: list[Bar], params: Params | None = None) -> list[Schematic]:
    """跑一个序列的完整检测：吸筹 + 派发（镜像），再按一次一个示意图做重叠去重。"""
    p = params or Params()
    if len(rows) < p.climax_lookback:
        return []
    accum = _detect_accum(rows, p, kind="accum")
    dist = [_flip_schematic(s) for s in _detect_accum(_mirror_rows(rows), p, kind="accum")]
    merged: list[Schematic] = []
    last_end = -1
    for s in sorted(accum + dist, key=lambda x: (x.sc_bar, x.end_bar)):
        if s.sc_bar > last_end:
            merged.append(s)
            last_end = s.end_bar
    return merged
