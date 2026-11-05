# tests/test_sr_baselines.py
import numpy as np

from sector_rotation.baselines import (EqualWeightAnnual, momentum_topk, random_k,
                                       reversal_topk)
from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member, UniverseSpec

M2 = [Member("881101", "机械", ("E1.SH",), 0.10),
      Member("881127", "半导体", ("E2.SH",), 0.10)]
SPEC = UniverseSpec(M2, {})


def _wf(index_rows, valid=None, fridays=None):
    T, L = index_rows.shape
    v = np.ones((T, L), bool) if valid is None else valid
    return WeeklyFrame(
        fridays=fridays or [f"w{i}" for i in range(T)], index_close=index_rows,
        etf_symbols=[["E1.SH", "E2.SH"]] * T,
        etf_open=np.ones((T, L)), etf_close=np.ones((T, L)),
        etf_prev_close=np.ones((T, L)), etf_week_amount=np.full((T, L), 2e8),
        members=M2, spec=SPEC, valid=v, dvalid=v.copy(),
        bench_300=np.full(T, 0.001))


def test_momentum_picks_topk_by_trailing_return():
    idx = np.array([[100.0, 100.0], [101.0, 110.0], [101.0, 120.0]])
    assert momentum_topk(_wf(idx), 2, lookback=2, k=1) == {1: 1.0}
    assert reversal_topk(_wf(idx), 2, lookback=2, k=1) == {0: 1.0}


def test_equal_weight_annual_rebalance():
    fridays = ["2020-01-03", "2020-06-05", "2021-01-08"]
    wf = _wf(np.ones((3, 2)), fridays=fridays)
    eq = EqualWeightAnnual()
    w0 = eq(wf, 0)
    assert w0 == {0: 0.5, 1: 0.5}
    assert eq(wf, 1) == w0                    # 同年同宇宙 → 持有不调（评审 C5）
    v = np.ones((3, 2), bool)
    v[2, 1] = False   # 次年 + 成员退出 → point-in-time 重建
    assert eq(_wf(np.ones((3, 2)), v, fridays=fridays), 2) == {0: 1.0}


def test_random_k_deterministic():
    wf = _wf(np.ones((3, 2)))
    assert random_k(wf, 2, k=1, seed=7) == random_k(wf, 2, k=1, seed=7)
