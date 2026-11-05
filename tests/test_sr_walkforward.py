# tests/test_sr_walkforward.py
import numpy as np

from sector_rotation.baselines import EqualWeightAnnual, momentum_topk
from sector_rotation.cost import CostModel
from sector_rotation.data import WeeklyFrame
from sector_rotation.permtest import paired_block_bootstrap, perm_test_vs_random
from sector_rotation.universe import Member, UniverseSpec
from sector_rotation.walkforward import coverage_start, run_walkforward

M2 = [Member("A", "甲", ("EA.SH",), 0.10), Member("B", "乙", ("EB.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(T=30, seed=5, valid=None):
    rng = np.random.default_rng(seed)
    idx = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, (T, 2)), axis=0)
    v = np.ones((T, 2), bool) if valid is None else valid
    v[-1, :] = False
    return WeeklyFrame([f"w{i}" for i in range(T)], idx,
                       [["EA.SH", "EB.SH"]] * T, np.ones((T, 2)),
                       1 + rng.normal(0.001, 0.02, (T, 2)), np.ones((T, 2)),
                       np.full((T, 2), 2e8), M2, SPEC, v, v.copy(), np.full(T, 0.001))


def test_coverage_start_finds_first_week_meeting_min_universe():
    v = np.zeros((20, 2), bool)
    v[10:, :] = True                        # 第 10 周起 2 行业全部可用
    assert coverage_start(_wf(T=20, valid=v), min_universe=2) == 10


def test_walkforward_uses_coverage_start_and_runs():
    wf = _wf()
    res = run_walkforward(wf, momentum_topk, cost=CostModel.base())
    assert res.nav[0] == 1.0 and len(res.nav) == len(res.weekly) + 1
    assert len(res.t_rows) == len(res.weekly)          # 评审 C4：行号账本等长
    assert all(set(tr["holdings"]) <= {0, 1} for tr in res.trades)


def test_paired_block_bootstrap_positive_and_negative():
    """评审 C2：重定心版——正效应 p<0.1、负效应 p 接近 1（未重定心版两者都 ≈0.5）。"""
    rng = np.random.default_rng(1)
    assert paired_block_bootstrap(rng.normal(0.002, 0.01, 300),
                                  block=4, n=500) < 0.1
    assert paired_block_bootstrap(rng.normal(-0.002, 0.01, 300),
                                  block=4, n=500) > 0.9


def test_perm_test_p_in_range():
    out = perm_test_vs_random(_wf(T=40), CostModel.base(), k=1, n=30,
                              strategy=EqualWeightAnnual())
    assert 0 <= out["p_value"] <= 1 and out["n_random"] == 30
