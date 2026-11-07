"""stats 单测：track_record 口径 + 箱体基线量具。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "wyckoff"))

from wyckoff.machine import Bar, Event, Schematic  # noqa: E402
from wyckoff.stats import baseline_stats, box_baseline, track_record  # noqa: E402


def sch(kind: str, outcome: str, detail: str = "", *, spring: bool = False,
        sos: bool = False, t1: bool = False, range_len: int | None = None) -> Schematic:
    s = Schematic(kind=kind, outcome=outcome, outcome_detail=detail,
                  sc_bar=0, sc_date="2024-01-01", sc_level=100.0)
    if spring:
        s.spring = Event("SPRING", 5, "2024-01-06", 98.0)
    if sos:
        s.sos = Event("SOS", 10, "2024-01-11", 110.0)
        s.range_len = range_len
        if t1:
            s.t1_hit_bar = 12
    return s


def test_track_record_counts_and_conditionals():
    schs = [
        sch("accum", "complete", "t2", spring=True, sos=True, t1=True, range_len=30),
        sch("accum", "complete", "t2", sos=True, t1=True, range_len=25),      # 无 spring
        sch("accum", "failed", "invalidated_after_sos", sos=True, t1=True, range_len=40),
        sch("accum", "expired", "expired_range"),                               # 未突破
        sch("accum", "vturn", "breakout_before_min_len"),                       # 不计入
        sch("dist", "complete", "t2", spring=True, sos=True, t1=True, range_len=35),
    ]
    tr = track_record(schs)
    a = tr["accum"]
    assert a["n_finished"] == 4          # vturn 不计
    assert a["n_complete"] == 2 and a["n_failed"] == 1 and a["n_expired"] == 1
    assert a["n_spring"] == 1 and a["p_spring"] == 0.25
    assert a["n_broke"] == 3 and a["p_broke"] == 0.75
    assert a["p_t1_given_sos"] == 1.0 and a["p_t2_given_sos"] == round(2 / 3, 3)
    assert a["p_fail_after_sos"] == round(1 / 3, 3)
    assert a["avg_range_len"] == 31.7
    assert tr["dist"]["n_finished"] == 1


def test_box_baseline_up_down_and_outcomes():
    # 60 根箱体 [10, 20]（横盘），bar 60 收 21 突破上沿：
    rows = [Bar(f"d{i}", 15, 20, 10, 15) for i in range(60)]
    # height=10 → T1=30, T2=40, invalid=10
    rows += [Bar("d60", 21, 22, 20.5, 21)]           # 突破
    rows += [Bar("d61", 22, 31, 21, 30)]             # T1 命中
    rows += [Bar("d62", 31, 41, 30, 40)]             # T2 命中 → complete
    evs = box_baseline(rows)
    assert len(evs) == 1 and evs[0].kind == "up" and evs[0].outcome == "complete"
    assert evs[0].t1_hit
    st = baseline_stats(evs)
    assert st["up"]["p_t2"] == 1.0


def test_box_baseline_fail_path():
    rows = [Bar(f"d{i}", 15, 20, 10, 15) for i in range(60)]
    rows += [Bar("d60", 21, 22, 20.5, 21)]   # 突破
    rows += [Bar("d61", 12, 13, 9, 9)]       # 收盘跌破箱底 10 → failed
    evs = box_baseline(rows)
    assert evs[0].outcome == "failed" and not evs[0].t1_hit


def test_box_baseline_dedupe_within_box_len():
    rows = [Bar(f"d{i}", 15, 20, 10, 15) for i in range(60)]     # 箱 [10,20]
    rows.append(Bar("d60", 21, 22, 20.5, 21))                     # 突破 1（skip 到 120）
    rows.append(Bar("d61", 22, 23, 21.5, 22))                     # 滚动高点 20 < 22 本该报，被跳过
    rows += [Bar(f"d{i}", 14, 15, 11, 14) for i in range(62, 131)]  # 回箱内横盘
    evs = box_baseline(rows)
    assert len(evs) == 1 and evs[0].bar == 60
