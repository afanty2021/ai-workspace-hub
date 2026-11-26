# tests/test_rps_core_locks.py
"""rps_core 预热门槛与去重叠 t 的直测（2026-11-26 max 评审 r5 I-5）。

2026-11-25 的两处修根此前没有任何测试引用被修模块，变异全部存活：
① rps_from_ret 的 bar_count 显式参数（Q-20261125-03）：缺参抛 TypeError；首个有效 RPS250
   落在第 251 根而不是第 500 根。
② validity.py 臂 C 的判定 t = 去重叠 t（Q-20261125-05）：实现抽成 rps_core.deoverlap_t，这里直测。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "rps"))
from rps_core import close_count, deoverlap_t, interval_ret, rps_from_ret  # noqa: E402


def _close_frame(days: int = 600, tickers: int = 3, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0005, 0.02, size=(days, tickers))
    close = 10.0 * np.cumprod(1.0 + ret, axis=0)
    idx = pd.bdate_range("2020-01-02", periods=days)
    return pd.DataFrame(close, index=idx, columns=[f"T{k}" for k in range(tickers)])


def test_rps_from_ret_without_bar_count_raises_instead_of_silent_fallback():
    close = _close_frame()
    with pytest.raises(TypeError, match="bar_count"):
        rps_from_ret(interval_ret(close, 250))


def test_first_valid_rps250_is_bar_251_when_counted_on_close_frame():
    close = _close_frame()
    ret250 = interval_ret(close, 250)
    r = rps_from_ret(ret250, bar_count=close_count(close))
    first = r.dropna(how="all").index[0]
    assert first == close.index[250]                  # 第 251 根：docstring 口径
    # 对照：把计数作用在 ret 帧上（修根前写法）会把首根推到第 500 根——这正是缺参必须抛错的理由
    r_bug = rps_from_ret(ret250, bar_count=close_count(ret250))
    assert r_bug.dropna(how="all").index[0] == close.index[499]


def test_deoverlap_t_equals_phase_zero_subsample():
    ic = pd.Series(np.sin(np.arange(100) / 7.0) + 0.3)
    sub = ic.to_numpy()[::20]
    assert len(sub) == 5
    expected = sub.mean() / sub.std(ddof=1) * np.sqrt(len(sub))
    assert deoverlap_t(ic, 20) == pytest.approx(expected, rel=1e-12)
    assert deoverlap_t(ic.to_numpy(), 20) == pytest.approx(expected, rel=1e-12)


def test_deoverlap_t_is_far_below_naive_t_on_overlapping_windows():
    white = np.random.default_rng(3).normal(0.0, 1.0, size=2000)
    ic = pd.Series(white).rolling(20).mean().dropna() + 0.02   # 相邻两日共享 19/20 的成分
    naive = ic.mean() / ic.std() * np.sqrt(len(ic))
    deo = deoverlap_t(ic, 20)
    assert 0 < deo < naive
    assert naive / deo > 2.5                           # 理论膨胀 ≈ √20 ≈ 4.5（本例 4.6）；留余量防抽样波动


def test_deoverlap_t_degenerate_inputs_are_nan():
    assert np.isnan(deoverlap_t([np.nan] * 50))
    assert np.isnan(deoverlap_t([0.5] * 200))          # 零方差
    assert np.isnan(deoverlap_t([0.1, 0.2, 0.3], 20))  # 相位 0 子序列只有 1 个点


def test_deoverlap_t_drops_nan_before_subsampling():
    # M24 变异锁（2026-11-26 max 评审）：docstring 承诺「可含 NaN，先剔除」——去掉 dropna
    # 会因 NaN 传染 std 返回 NaN。含 NaN 输入必须与手工 dropna 后的结果逐位一致。
    ic = pd.Series([0.1, np.nan, 0.3, np.nan, 0.9, 0.2, np.nan, 0.5, 0.4, np.nan] * 5)
    t = deoverlap_t(ic, 1)
    assert np.isfinite(t)
    expected_sub = ic.dropna().to_numpy()[::1]
    expected = expected_sub.mean() / expected_sub.std(ddof=1) * np.sqrt(len(expected_sub))
    assert t == pytest.approx(expected, rel=1e-12)
