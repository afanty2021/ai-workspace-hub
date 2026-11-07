# tests/test_sr_hold_confirm.py
"""R20261107-03 沉默持有确认驱动的回归测试（预注册批，2026-11-07）。

覆盖：tail_bounds 窗口语义（决策年+执行年+valid 三重过滤、末界、周连续）、
make_hold_strat 沉默持有状态机（发声→照单、沉默→持有、无历史→现金）、
family_verdict 三档机械归类。真实窗口断言（周数冻结带/与消费窗相接）在
runner main 内对真实帧执行，不进单测。"""
import numpy as np
import pytest

pytest.importorskip("torch")

from sector_rotation.data import WeeklyFrame  # noqa: E402
from sector_rotation.models import ROCState  # noqa: E402
from sector_rotation.universe import Member, UniverseSpec  # noqa: E402
from repro_hold_confirm import (  # noqa: E402
    TAIL_END, TAIL_START, family_verdict, make_hold_strat, tail_bounds)

M1 = [Member("A", "甲", ("EA.SH",), 0.10)]
SPEC = UniverseSpec(M1, {})


def _wf(fridays, valid=True):
    T = len(fridays)
    v = np.ones((T, 1), bool) if valid else np.zeros((T, 1), bool)
    return WeeklyFrame(fridays, np.full((T, 1), 100.0), [["EA.SH"]] * T,
                       np.ones((T, 1)), np.full((T, 1), 1.01),
                       np.ones((T, 1)), np.full((T, 1), 2e8), M1, SPEC,
                       v, v.copy(), np.full(T, 0.001))


def test_tail_bounds_filters_decision_year_exec_year_validity():
    # 2022-12-30 决策的执行周是 2023-W01，但决策周五 <2023-01-01 → 双侧弃
    fridays = ["2022-12-16", "2022-12-23", "2022-12-30",
               "2023-01-06", "2023-01-13", TAIL_END]
    wf = _wf(fridays)
    s, e = tail_bounds(wf)
    assert (s, e) == (3, 6)            # 2023-01-06 起至冻结末界
    wf_bad = _wf(fridays, valid=False)
    with pytest.raises(AssertionError):
        tail_bounds(wf_bad)            # 全 invalid → 无决策周
    # 末界之后的周（残缺 exec 周）不进窗
    wf2 = _wf(fridays + ["2026-10-30"])
    s2, e2 = tail_bounds(wf2)
    assert wf2.fridays[e2 - 1] == TAIL_END


def test_tail_bounds_requires_contiguity():
    # 真实风险形态：中周 valid 失败被过滤 → 帧索引断档
    fridays = ["2023-01-06", "2023-01-13", "2023-01-20"]
    wf = _wf(fridays)
    wf.valid[1] = False
    with pytest.raises(AssertionError, match="不连续"):
        tail_bounds(wf)


class _Stub:
    """脚本化 select：按调用序返回预设组合（测试沉默持有状态机）。"""

    def __init__(self, seq):
        self.seq, self.i = list(seq), 0

    def select(self, wf_, t, roc=None):
        out = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return dict(out)


def test_hold_strat_silence_holds_last_roster():
    m = _Stub([{0: 0.5, 1: 0.5}, {}, {}, {2: 1.0}, {}])
    strat = make_hold_strat({2023: m}, ROCState())
    wf = _wf(["2023-01-06", "2023-01-13", "2023-01-20", "2023-01-27",
              "2023-02-03"])
    assert strat(wf, 0) == {0: 0.5, 1: 0.5}      # 发声→照单
    assert strat(wf, 1) == {0: 0.5, 1: 0.5}      # 沉默→持有
    assert strat(wf, 2) == {0: 0.5, 1: 0.5}      # 连续沉默→继续持有
    assert strat(wf, 3) == {2: 1.0}              # 新发声→换仓（旧成员被卖出）
    assert strat(wf, 4) == {2: 1.0}              # 再沉默→持有新单


def test_hold_strat_cold_start_and_missing_year():
    m = _Stub([{}])                              # 冷启动即沉默
    strat = make_hold_strat({2023: m}, ROCState())
    wf = _wf(["2023-01-06", "2023-01-13"])
    assert strat(wf, 0) == {}                    # 无历史组合→现金
    m2 = _Stub([{0: 1.0}])
    strat2 = make_hold_strat({2023: m2}, ROCState())
    assert strat2(wf, 0) == {0: 1.0}
    assert strat2(wf, 1) == {0: 1.0}             # 年内沉默持有
    assert strat2(_wf(["2024-01-05"]), 0) == {}  # 2024 无模型（驱动层按年接线）


def test_family_verdict_three_tiers():
    strong = family_verdict({13: 0.04, 26: 0.05, 52: 0.06})
    assert "强正" in strong
    weak = family_verdict({13: 0.01, 26: 0.005, 52: 0.02})
    assert "弱正" in weak
    fail = family_verdict({13: -0.02, 26: 0.01, 52: 0.03})
    assert "证伪" in fail                        # 族中位 ≤0（两负一正中位负）
    one_neg = family_verdict({13: 0.05, 26: 0.05, 52: -0.01})
    assert "弱正" in one_neg                     # 中位>0 但非全正 → 不进强正档


def test_frozen_window_constants():
    assert TAIL_START == "2023-01-01" and TAIL_END == "2026-10-23"
