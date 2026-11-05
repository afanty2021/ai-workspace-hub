# tests/test_sr_weekly.py
import numpy as np

from sector_rotation.data import WeeklyFrame
from sector_rotation.universe import Member, UniverseSpec
from sector_rotation.weekly import (standardize_fit_apply, weekly_gross_returns,
                                    window_blocks)

M1 = Member("881101", "机械", ("528030.SH",), 0.10)
SPEC = UniverseSpec([M1], {})


def _wf(T=15):
    rng = np.random.default_rng(3)
    return WeeklyFrame(
        fridays=[f"2026-w{i:02d}" for i in range(T)],
        index_close=rng.normal(100, 5, (T, 1)),
        etf_symbols=[["528030.SH"]] * T,
        etf_open=np.full((T, 1), 1.0), etf_close=np.full((T, 1), 1.02),
        etf_prev_close=np.full((T, 1), 0.99), etf_week_amount=np.full((T, 1), 2e8),
        members=[M1], spec=SPEC, valid=np.ones((T, 1), bool),
        dvalid=np.ones((T, 1), bool), bench_300=np.full(T, 0.001))


def test_gross_return_is_close_over_open_minus_1():
    assert np.allclose(weekly_gross_returns(_wf()), 0.02)


def test_standardize_uses_train_stats_only():
    train = np.array([[1.0, 10.0], [3.0, 30.0], [5.0, 50.0], [7.0, 70.0]])
    now = np.array([[4.0, 40.0]])
    out = standardize_fit_apply(train, now)
    # mu=(4,40), sd(train, ddof=0)=sqrt(5) 每列 → 4→0、40→0
    assert np.allclose(out, [[0.0, 0.0]])
    train2 = np.full((4, 2), 5.0)            # 零方差列 → sd 兜底 1，不除零
    assert np.isfinite(standardize_fit_apply(train2, now)).all()


def test_window_blocks_shape():
    blocks, t_index = window_blocks(_wf(T=15), window=4)
    assert blocks.shape == (11, 4) and t_index[0] == 4
