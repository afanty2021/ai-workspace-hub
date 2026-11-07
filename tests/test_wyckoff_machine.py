"""威科夫状态机单测 v2：对靶 Pine 源码后的语义（tools/wyckoff/reference/*.pine）。

夹具按真实默认参数（trendLen=50 / RMA50 ATR / climRng=1.2 / climVol=1.5 含当前 bar /
minRange=15 / stTol=0.35 / sprBars=3 / failDep=0.30×区间高度 / maxRng=maxLeg=300）构造。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "wyckoff"))

from wyckoff.machine import (  # noqa: E402
    Bar,
    _detect_accum,
    _mirror_rows,
    detect,
)
from wyckoff.params import Params  # noqa: E402


def bar(i: int, o: float, h: float, lo: float, c: float, v: float | None = 1000.0) -> Bar:
    return Bar(date=f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", open=o, high=h, low=lo, close=c, volume=v)


def flat(n: int, h=101.0, lo=100.0, c=100.5, v=1000.0) -> list[Bar]:
    return [bar(i, c, h, lo, c, v) for i in range(n)]


# --- 主夹具（accum 全路径）：
# --- SC(60) → AR pivot(63)/确认(66) → ST pivot(69)/确认(72) → SPRING(76)
# --- → SOS(80) → T1(83) → T2/complete(85)；区间 [95, 99.5] 高 4.5
BASE_TAIL: list[tuple] = [
    # (o, h, l, c, v)
    (100.5, 99.0, 95.0, 98.0, 2000.0),   # 60 SC：最低低点+宽幅 4+放量（均含当前 bar）
    (96.5, 96.8, 96.3, 96.6, 1000.0),    # 61（跳空高开，低点不延伸 ext）
    (97.0, 97.5, 96.5, 97.2, 1000.0),    # 62
    (98.0, 99.5, 97.0, 99.0, 1000.0),    # 63 AR pivot（high 99.5）
    (98.0, 98.5, 97.5, 98.0, 1000.0),    # 64
    (97.2, 97.5, 97.0, 97.2, 1000.0),    # 65
    (96.5, 96.8, 96.4, 96.5, 1000.0),    # 66 AR 确认（63+3）：rally 4.5 ∈ [2×ATR, 10×ATR]
    (98.0, 98.3, 97.6, 98.0, 1000.0),    # 67
    (97.5, 97.8, 97.2, 97.5, 1000.0),    # 68
    (96.9, 97.3, 96.3, 96.9, 1000.0),    # 69 ST pivot（low 96.3 ≤ 95+0.35×4.5=96.575）
    (97.5, 97.8, 97.1, 97.5, 1000.0),    # 70
    (98.0, 98.2, 97.6, 98.0, 1000.0),    # 71
    (98.2, 98.5, 97.9, 98.2, 1000.0),    # 72 ST 确认（69+3）
    (97.5, 97.8, 97.2, 97.5, 1000.0),    # 73
    (97.0, 97.4, 96.8, 97.0, 1000.0),    # 74
    (96.5, 96.9, 96.3, 96.5, 1000.0),    # 75
    (96.5, 97.0, 94.6, 96.0, 1000.0),    # 76 SPRING：影线 94.6 破 95、同 bar 收回 96
    (97.5, 98.0, 97.0, 97.5, 1000.0),    # 77
    (98.5, 99.0, 98.2, 98.5, 1000.0),    # 78
    (99.2, 99.4, 98.9, 99.2, 1000.0),    # 79
    (99.2, 100.3, 99.4, 100.0, 1000.0),  # 80 SOS：close 100 > 99.5，age 20
    (100.0, 102.0, 101.0, 101.5, 1000.0),  # 81
    (101.5, 103.5, 102.6, 103.0, 1000.0),  # 82
    (103.0, 105.5, 104.6, 105.0, 1000.0),  # 83 T1=104 命中
    (105.0, 107.5, 106.6, 107.0, 1000.0),  # 84
    (107.0, 110.2, 109.0, 110.0, 1000.0),  # 85 T2=108.5 命中 → complete
]


def fixture(**overrides: tuple) -> list[Bar]:
    tail = list(BASE_TAIL)
    for idx, tup in overrides.items():
        tail[int(idx[3:]) - 60] = tup  # barN → tail[N-60]（BASE_TAIL[0] = bar 60 SC）
    return flat(60) + [bar(60 + i, *tup) for i, tup in enumerate(tail)]


def only(schs):
    assert len(schs) == 1, f"expect 1 schematic, got {len(schs)}: {[(s.kind, s.outcome, s.sc_bar) for s in schs]}"
    return schs[0]


# ---------------------------------------------------------------------------
# 主路径与结构判定
# ---------------------------------------------------------------------------


def test_full_path_accum_complete():
    s = only(_detect_accum(fixture(), Params(), kind="accum"))
    assert s.kind == "accum" and s.outcome == "complete" and s.outcome_detail == "t2"
    assert s.sc_bar == 60 and s.sc_level == 95.0
    assert s.ar_pivot_bar == 63 and s.ar_confirm_bar == 66
    assert s.range_bottom == 95.0 and s.range_top == 99.5 and s.ar_level == 99.5
    assert s.st is not None and s.st.pivot_bar == 69 and s.st.bar == 72
    assert s.spring is not None and s.spring.bar == 76
    assert s.spring.level == 94.6 and s.spring.pivot_bar == 76
    assert s.sos is not None and s.sos.bar == 80
    assert s.t1 == 104.0 and s.t2 == 108.5 and s.invalid == 94.6
    assert s.t1_hit_bar == 83 and s.end_bar == 85 and s.range_len == 20
    assert [e.type for e in s.events] == ["SC", "AR", "ST", "SPRING", "SOS", "T1", "T2", "COMPLETE"]


def test_atr_gate_before_bar_49():
    # bar 40 的 climax 形态 bar 因 na(atr) 被整体跳过（原脚本 not na(atr) 门控）
    rows = flat(60)
    rows[40] = bar(40, 100.5, 99.0, 95.0, 98.0, 2000.0)
    tail = [(96.0, 96.5, 95.0, 96.0, 1000.0)] * 55
    rows += [bar(61 + i, *tup) for i, tup in enumerate(tail)]
    rows[60] = bar(60, 100.5, 98.0, 93.0, 96.0, 2500.0)
    schs = [s for s in _detect_accum(rows, Params(), kind="accum")]
    assert all(s.sc_bar == 60 for s in schs) and schs, [(s.sc_bar, s.outcome) for s in schs]


def test_volume_sma_includes_current_bar():
    # vol=1520：含当前 bar 的均值 1026×1.5=1539 > 1520 → 不触发（排除当前的旧口径会误触发）
    rows = fixture(bar60=(100.5, 99.0, 95.0, 98.0, 1520.0))
    assert _detect_accum(rows, Params(), kind="accum") == []
    rows = fixture(bar60=(100.5, 99.0, 95.0, 98.0, 2000.0))
    assert len(_detect_accum(rows, Params(), kind="accum")) == 1


def test_no_volume_climax_by_range_alone():
    rows = [bar(i, r.open, r.high, r.low, r.close, None) for i, r in enumerate(fixture())]
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "complete"


def test_wait_ar_ext_extends_without_climax_criteria():
    # 61 号新低 94.8（非 climax 形态）仍延伸 ext；区间底=94.8
    rows = fixture(bar61=(95.5, 95.7, 94.8, 95.5, 1000.0),
                   bar62=(95.5, 96.5, 95.0, 96.0, 1000.0),
                   bar63=(96.0, 97.5, 96.0, 97.2, 1000.0),
                   bar64=(97.2, 99.6, 97.0, 99.0, 1000.0),
                   bar65=(99.0, 98.5, 97.5, 98.0, 1000.0),
                   bar66=(98.0, 97.5, 97.0, 97.2, 1000.0),
                   bar67=(97.2, 96.8, 96.5, 96.6, 1000.0))
    schs = _detect_accum(rows, Params(), kind="accum")
    started = [s for s in schs if s.ar_confirm_bar >= 0]
    s = started[0]
    assert s.range_bottom == 94.8  # ext 已延伸，range 自 ext 起算


def test_ar_too_tall_dropped():
    # rally 20 > 10×ATR[67]（bar65 自 114 崩回 97 的 TR=17 已抬高 ATR 至 ~1.79）
    rows = fixture(bar64=(112.0, 115.0, 97.0, 114.0, 1000.0))
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "dropped" and s.outcome_detail == "ar_too_tall" and not s.finished


def test_ar_timeout_uses_climax_lookback():
    rows = flat(60)
    rows += [bar(60 + i, 96.0, 96.5, 95.5, 96.0, 1000.0) for i in range(55)]
    rows[60] = bar(60, 100.5, 99.0, 95.0, 98.0, 2000.0)  # SC
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "dropped" and s.outcome_detail == "ar_timeout"
    assert s.end_bar == 111  # 自 ext_bar(60) 起 trendLen=50


# ---------------------------------------------------------------------------
# spring / 破位语义（Pine 专项）
# ---------------------------------------------------------------------------


def test_spring_does_not_require_st():
    rows = fixture(bar66=(97.0, 97.3, 97.0, 97.2, 1000.0),   # 66 低点抬走（否则成替代 pivot）
                   bar69=(96.9, 97.3, 96.9, 97.0, 1000.0))   # ST pivot 抬出 35% 区
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.st is None and s.spring is not None and s.spring.bar == 76
    assert s.outcome == "complete"


def test_early_recovered_break_no_event():
    # 73 破位（age 13 < 15）、74 收回 → 不计 spring；76 破位也去掉，SOS 后 inv = climax 极值
    rows = fixture(bar73=(97.5, 97.8, 94.7, 94.8, 1000.0),
                   bar74=(94.8, 97.4, 94.7, 96.5, 1000.0),
                   bar76=(96.5, 97.0, 96.2, 96.5, 1000.0))
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.spring is None and s.invalid == 95.0 and s.sos is not None


def test_early_deep_break_dropped_not_failed():
    rows = fixture(bar74=(97.0, 97.2, 91.5, 92.0, 1000.0))  # age 14：深破 → 丢弃
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "dropped" and s.outcome_detail == "early_break" and not s.finished


def test_late_deep_close_fails_wick_depth_ignored():
    # 76 影线 91.5 收 94.8：影线深不判；close 深 0.2 不判 → pend → 77 收回 = spring
    rows = fixture(bar76=(96.5, 97.0, 91.5, 94.8, 1000.0),
                   bar77=(94.8, 97.5, 94.6, 96.5, 1000.0))
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.spring is not None and s.spring.level == 91.5  # pend_ext 跟踪最深影线
    assert s.outcome == "complete"


def test_late_deep_close_fails():
    rows = fixture(bar76=(96.5, 97.0, 96.2, 96.5, 1000.0),  # 去掉 76 破位（保持 stage 2）
                   bar78=(98.5, 98.7, 92.5, 92.8, 1000.0))   # age 18：close 深 2.2 > 1.35
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "failed" and s.outcome_detail == "breakdown_in_range"
    assert s.end_bar == 78


def test_pend_timeout_fails_on_fourth_bar_outside():
    rows = fixture(bar76=(96.5, 97.0, 94.6, 94.7, 1000.0),
                   bar77=(94.7, 95.5, 94.5, 94.6, 1000.0),
                   bar78=(94.6, 95.4, 94.4, 94.5, 1000.0),
                   bar79=(94.5, 95.3, 94.3, 94.4, 1000.0))
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "failed" and s.outcome_detail == "breakdown_in_range"
    assert s.end_bar == 79  # pendN=4 > sprBars=3


def test_sos_same_bar_cancels_pending_spring():
    rows = fixture(bar76=(96.5, 97.0, 94.6, 94.7, 1000.0),
                   bar77=(94.7, 101.0, 99.0, 100.5, 1000.0))  # 收回并直接突破
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.sos is not None and s.sos.bar == 77
    assert s.spring is None and s.invalid == 95.0  # inv = climax 极值非影线低


def test_breakdown_after_spring_uses_spring_extreme():
    rows = fixture(bar77=(96.0, 96.5, 94.2, 94.5, 1000.0))  # 收盘 94.5 < spring 94.6
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "failed" and s.outcome_detail == "breakdown_after_spring"
    assert s.end_bar == 77


def _flat_tail(rows: list[Bar], start: int, n: int) -> list[Bar]:
    """截断到 start，再接 n 根横盘 bar（不突破不破位）。"""
    return rows[:start] + [bar(start + i, 97.5, 98.4, 96.5, 97.5, 1000.0) for i in range(n)]


def test_expired_after_spring_counts_from_spring_extreme():
    p = Params(range_max_bars=20)
    rows = _flat_tail(fixture(bar80=(99.2, 99.4, 98.9, 99.2, 1000.0)), 81, 20)
    s = only(_detect_accum(rows, p, kind="accum"))
    assert s.outcome == "expired" and s.outcome_detail == "expired_after_spring"
    assert s.end_bar == 97  # 自 spring 极值 bar 76 起 20


def test_expired_range_without_spring():
    p = Params(range_max_bars=25)
    rows = _flat_tail(fixture(bar76=(96.5, 97.0, 96.2, 96.5, 1000.0),   # 去掉破位
                              bar80=(99.2, 99.4, 98.9, 99.2, 1000.0)),  # 去掉 SOS
                     81, 20)
    s = only(_detect_accum(rows, p, kind="accum"))
    assert s.outcome == "expired" and s.outcome_detail == "expired_range"
    assert s.end_bar == 86  # 自 SC bar 60 起 25


def test_vturn_early_breakout_dropped():
    rows = fixture(bar68=(97.5, 100.5, 97.2, 100.0, 1000.0))  # age 8：close 100 > 99.5
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "dropped" and s.outcome_detail == "vturn" and not s.finished


# ---------------------------------------------------------------------------
# MARKUP 语义与镜像
# ---------------------------------------------------------------------------


def test_t2_beats_invalidation_same_bar():
    rows = fixture(bar81=(100.0, 109.0, 94.0, 94.5, 1000.0))  # T2 影线命中 + 收盘破 inv
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "complete" and s.end_bar == 81
    assert s.t1_hit_bar == 81  # 原脚本 hitMax=2 → rT1 按 ≥1 计


def test_invalidated_after_sos_t1_still_counted():
    rows = fixture(bar83=(103.0, 104.5, 103.5, 103.8, 1000.0),   # T1 命中
                   bar84=(103.8, 104.0, 94.0, 94.5, 1000.0))     # 收盘破 inv 94.6
    s = only(_detect_accum(rows, Params(), kind="accum"))
    assert s.outcome == "failed" and s.outcome_detail == "invalidated_after_sos"
    assert s.t1_hit_bar == 83  # 失效 bar 前命中的 T1 计入 track record


def test_mirror_dist_full_path():
    merged = detect(_mirror_rows(fixture()), Params())
    s = only(merged)
    assert s.kind == "dist" and s.outcome == "complete"
    assert s.sc_level == -95.0 and s.range_top == -95.0 and s.range_bottom == -99.5
    assert s.spring is not None and s.spring.type == "UTAD" and s.spring.level == -94.6
    assert s.sos.type == "SOW" and s.sos.bar == 80
    assert s.t1 == -104.0 and s.t2 == -108.5 and s.invalid == -94.6
    assert [e.type for e in s.events] == ["BC", "AR", "ST", "UTAD", "SOW", "T1", "T2", "COMPLETE"]


def test_detect_merges_no_overlap():
    merged = detect(fixture(), Params())
    last_end = -1
    for s in merged:
        assert s.sc_bar > last_end
        last_end = s.end_bar


def test_short_series_returns_empty():
    assert detect(flat(30), Params()) == []
