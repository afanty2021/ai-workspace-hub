# tests/test_sr_ashare_hold_probe.py
"""A 股沉默持有探索 runner 回归测试（R20261107-05，2026-11-07）。

覆盖：window_bounds 处女段护栏/锚点行/末行漂移拦截、mature_cohort 规则
（锚周 valid ∧ 指数自 IDX_T0 无缺口）、sub_frame 列切片完整性、
make_hold/make_count 状态机。真实数据路径（帧构建/Part1 复现锚/Part2 移植）
由 CLI 首跑验收，不进单测。"""
import numpy as np
import pytest

from sector_rotation.data import WeeklyFrame  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402
from ashare_hold_probe import (ANCHOR, END_CAP, make_count, make_hold,  # noqa: E402
                               mature_cohort, sub_frame, window_bounds)

M = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10),
     Member("C", "丙", ("EC.SH",), 0.10)]
SPEC = UniverseSpec(M, {})


def _wf(fridays, *, anchor_valid=(True, True, True), gaps=()) -> WeeklyFrame:
    """三成员玩具帧：锚行 valid 由参数控制、锚后行全员 valid（引擎 any() 跳行
    语义需要非空）；gaps=(成员列, 行) 打指数 NaN 洞。"""
    T, L = len(fridays), 3
    valid = np.zeros((T, L), bool)
    valid[fridays.index(ANCHOR)] = anchor_valid
    valid[fridays.index(ANCHOR) + 1:] = True
    idx = np.full((T, L), 100.0)
    for j, t in gaps:
        idx[t, j] = np.nan
    return WeeklyFrame(fridays, idx, [["EA.SH", "EB.SH", "EC.SH"]] * T,
                       np.full((T, L), 10.0), np.full((T, L), 10.1),
                       np.full((T, L), 10.0), np.full((T, L), 1e9), M, SPEC,
                       valid, valid.copy(), np.full(T, 0.001))


def test_window_bounds_guard_and_anchor():
    wf = _wf(["2018-12-28", ANCHOR, END_CAP])
    assert window_bounds(wf) == (1, 3)
    with pytest.raises(RuntimeError, match="处女段"):
        window_bounds(_wf(["2018-12-28", ANCHOR, END_CAP, "2026-11-13"]))
    with pytest.raises(AssertionError):        # 末行漂移（快照变化）
        window_bounds(_wf(["2018-12-28", ANCHOR, "2026-10-30"]))


def test_mature_cohort_rule():
    # A：锚周 valid ∧ 无洞 → 入；B：锚周 valid 但 T0 后有指数洞 → 出；
    # C：锚周 invalid（指数再干净）→ 出
    wf = _wf(["2018-12-28", ANCHOR, END_CAP],
             anchor_valid=(True, True, False), gaps=((1, 2),))
    assert mature_cohort(wf).tolist() == [0]
    # 洞在 IDX_T0 之前 → 不影响（规则自 T0 起算）
    wf2 = _wf(["2018-12-21", "2018-12-28", ANCHOR, END_CAP],
              gaps=((1, 0),))
    assert mature_cohort(wf2).tolist() == [0, 1, 2]


def test_sub_frame_slicing():
    wf = _wf(["2018-12-28", ANCHOR, END_CAP])
    sub = sub_frame(wf, np.array([0, 2]))
    assert sub.index_close.shape == (3, 2)
    assert np.allclose(sub.index_close, wf.index_close[:, [0, 2]])
    assert [m.index_code for m in sub.members] == ["A", "C"]
    assert sub.etf_symbols[0] == ["EA.SH", "EC.SH"]
    assert sub.valid.shape == (3, 2) and sub.etf_volume is None
    assert sub.bench_300 is wf.bench_300 and sub.fridays is wf.fridays


def _seq_select(seq):
    state = {"i": 0}

    def select(wf_, t):
        out = seq[min(state["i"], len(seq) - 1)]
        state["i"] += 1
        return dict(out)

    return select


def test_make_hold_and_count_semantics():
    seq = [{0: 0.5, 1: 0.5}, {}, {1: 1.0}, {}]
    strat, st = make_hold(_seq_select(seq))
    assert strat(None, 0) == {0: 0.5, 1: 0.5}      # 发声 → 照单
    assert strat(None, 1) == {0: 0.5, 1: 0.5}      # 沉默 → 持有上期
    assert strat(None, 2) == {1: 1.0}              # 发声换仓
    assert strat(None, 3) == {1: 1.0}              # 沉默 → 持有上期
    assert (st["spoke"], st["silent"]) == (2, 2)
    strat2, st2 = make_count(_seq_select(seq))
    assert strat2(None, 0) == {0: 0.5, 1: 0.5}     # 全平：沉默周=现金
    assert strat2(None, 1) == {} and strat2(None, 2) == {1: 1.0}
    assert strat2(None, 3) == {}
    assert (st2["spoke"], st2["silent"]) == (2, 2)
