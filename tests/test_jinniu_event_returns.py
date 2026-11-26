# tests/test_jinniu_event_returns.py
"""jinniu event_returns 的间隔口径锁（2026-11-26 max 评审 r5 I-1 / M-8）。

周线路径的 di 是周序号（resample_weekly 的返回值），不是日期。2026-11-25 的历法日修根把它
当 YYYYMMDD 解析：周序号每跨 100 回跳 68 天，跨界的长停牌窗被漏剔。修法=周线调用显式传
dnum=周序号、阈值按周给；di 含非法年月日时直接抛错（防再漏调用点）。

断言链：
① 周线：跨周序号 100 边界的长停牌窗被剔；相邻周保留。
② 日线：跨月前瞻窗保留（Q-20261125-04 修根不回退）；真停牌被剔。
③ 周序号不传 dnum 直接抛错；resample_weekly 的返回值是对齐周一的周计数。
④ by_year：周线接线传周序号；文件枚举走宇宙白名单（原裸 glob 混入 LOF/基金/跨资产/板块指数）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import run_check

REPO_ROOT = Path(__file__).resolve().parents[1]
JN_DIR = REPO_ROOT / "tools" / "jinniu"


def _jn():
    return run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)


def _ymd(dates) -> np.ndarray:
    return np.array([int(d.strftime("%Y%m%d")) for d in dates], dtype=np.int64)


def _by_year(jn):
    """按路径加载 by_year.py。它头部 `from run_backtest import …` 用的是裸模块名，而
    stage-bottom 也有同名 run_backtest.py——临时把 jinniu 这份登记为 `run_backtest`，装完还原。"""
    saved = sys.modules.get("run_backtest")
    old = list(sys.path)
    sys.modules["run_backtest"] = jn
    sys.path.insert(0, str(JN_DIR))
    try:
        spec = importlib.util.spec_from_file_location("jinniu_by_year_under_test", JN_DIR / "by_year.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = old
        if saved is None:
            sys.modules.pop("run_backtest", None)
        else:
            sys.modules["run_backtest"] = saved


def test_weekly_long_suspension_across_week_index_100_boundary_is_removed():
    jn = _jn()
    # 周序号 1295 之后停牌 59 周，下一根是 1355——窗口跨过 1300（1299→1300 若被当 YYYYMMDD 解析会回跳 68 天）
    weeks = np.concatenate([np.arange(1290, 1296), np.arange(1355, 1381)])
    assert weeks[6] - weeks[5] == 60
    o = np.linspace(10.0, 20.0, len(weeks))
    sig = np.zeros(len(weeks), dtype=bool)
    sig[5] = True
    for h in jn.WEEKLY_H:
        idx, _ = jn.event_returns(weeks, o, sig, h, jn.GAP_WEEKS, dnum=weeks)
        assert idx.size == 0, f"h={h}：停牌 59 周的样本必须被剔"


def test_weekly_adjacent_bars_are_kept_with_week_unit_thresholds():
    jn = _jn()
    weeks = np.arange(1290, 1330)                      # 含 1299→1300，相邻周间隔恒为 1 周
    o = np.linspace(10.0, 20.0, len(weeks))
    base_all = np.ones(len(weeks), dtype=bool)
    idx, ret = jn.event_returns(weeks, o, base_all, 1, jn.GAP_WEEKS, dnum=weeks)
    assert idx.size == len(weeks) - 3                  # idx ≥ 1 且 idx+1+h < n：1..37 全保留
    assert np.allclose(ret, o[idx + 2] / o[idx + 1] - 1.0)


def test_daily_month_crossing_window_is_kept_and_true_suspension_is_removed():
    jn = _jn()
    dates = list(pd.bdate_range("2024-01-02", periods=40))
    di = _ymd(dates)
    o = np.linspace(10.0, 12.0, len(dates))
    i2 = dates.index(pd.Timestamp("2024-01-31"))
    assert di[i2 + 1] - di[i2] == 70                   # 整数差把 1 个日历日算成 70：旧 bug 的触发条件
    sig = np.zeros(len(dates), dtype=bool)
    sig[i2] = True
    idx, _ = jn.event_returns(di, o, sig, 1, jn.GAP_DAYS)
    assert list(idx) == [i2]

    # 真停牌：第 10 根之后停 14 个交易日（约 20 个日历日）
    full = list(pd.bdate_range("2024-01-02", periods=60))
    dates = full[:11] + full[25:]
    assert (dates[11] - dates[10]).days > jn.GAP_DAYS
    di = _ymd(dates)
    sig = np.zeros(len(dates), dtype=bool)
    sig[9] = True
    sig[10] = True
    idx, _ = jn.event_returns(di, o[:len(dates)], sig, 1, jn.GAP_DAYS)
    assert list(idx) == [9]


def test_forward_window_crossing_a_long_suspension_is_removed_but_short_gaps_are_kept():
    """前瞻窗上限 = h*5+20 个日历日（日线）：窗口内跨长停牌剔除，窗内短缺口不影响。"""
    jn = _jn()
    full = list(pd.bdate_range("2024-01-02", periods=120))
    # 第 20 根之后停牌 35 个交易日（50 个日历日），落在 i=19 的前瞻窗内（i→i+1 本身正常）
    dates = full[:21] + full[56:]
    assert (dates[21] - dates[20]).days > 5 * 5 + 20     # 光这一段就超过 h=5 的窗口上限（45 天）
    assert (dates[20] - dates[19]).days <= jn.GAP_DAYS
    di = _ymd(dates)
    o = np.linspace(10.0, 20.0, len(dates))
    sig = np.zeros(len(dates), dtype=bool)
    sig[19] = True
    for h in (1, 5):
        idx, _ = jn.event_returns(di, o, sig, h, jn.GAP_DAYS)
        assert idx.size == 0, f"h={h}：前瞻窗跨 49 天停牌必须被剔"

    # 窗内只有 11 天的短缺口：h=5 的上限是 45 天，保留
    short = full[:21] + full[28:]
    di = _ymd(short)
    sig = np.zeros(len(short), dtype=bool)
    sig[19] = True
    idx, _ = jn.event_returns(di, o[:len(short)], sig, 5, jn.GAP_DAYS)
    assert list(idx) == [19]


def test_week_index_without_dnum_raises_instead_of_silent_misparse():
    jn = _jn()
    weeks = np.arange(1290, 1296)
    o = np.linspace(10.0, 20.0, len(weeks))
    sig = np.zeros(len(weeks), dtype=bool)
    sig[1] = True
    with pytest.raises(ValueError, match="dnum"):
        jn.event_returns(weeks, o, sig, 1, jn.GAP_WEEKS)


def test_resample_weekly_returns_monday_aligned_week_index():
    jn = _jn()
    dates = list(pd.bdate_range("2024-01-02", periods=120))
    di = _ymd(dates)
    o = np.arange(120, dtype=float)
    wd, wo, wc = jn.resample_weekly(di, o, o + 0.5)
    mondays = pd.to_datetime(wd * 7 - 3, unit="D")
    assert (mondays.dayofweek == 0).all()              # 周键 = (days+3)//7，对齐周一
    assert np.all(np.diff(wd) == 1)                    # 连续 24 个自然周
    assert wo[0] == o[0] and wc[-1] == o[-1] + 0.5


def test_by_year_weekly_path_passes_week_index_and_filters_universe(tmp_path, monkeypatch):
    jn = _jn()
    by = _by_year(jn)
    weeks = np.arange(2580, 2680)                      # 跨 2600
    wo = np.linspace(10.0, 20.0, len(weeks))
    sig = np.zeros(len(weeks), dtype=bool)
    sig[15] = True
    wyear = ((weeks * 7 - 3).astype("datetime64[D]").astype("datetime64[Y]").astype(int) + 1970)
    out = by.pooled_by_year(weeks, wo, sig, 4, by.GAP_WEEKS, year_arr=wyear, dnum=weeks)
    assert sum(len(ss) for ss, _ in out.values()) == 1

    # 宇宙白名单：非标的文件不进分年度表
    (tmp_path / "600001.SH.jsonl").write_text("{}\n")
    (tmp_path / "HG.NYB.jsonl").write_text("{}\n")
    (tmp_path / "501300.SH.jsonl").write_text("{}\n")   # LOF 段，不在白名单
    loaded = []

    def _rec(path):
        loaded.append(Path(path).name)
        return np.array([20240102], dtype=np.int64), np.array([10.0]), np.array([10.0])

    monkeypatch.setattr(by, "CACHE", tmp_path)
    monkeypatch.setattr(by, "load_symbol", _rec)
    assert by.main() == 0
    assert loaded == ["600001.SH.jsonl"]
