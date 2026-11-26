# tests/test_sleeve_u4.py
"""sleeve.py U4（停牌跳空过滤）的直测（2026-11-26 max 评审 r5 I-5）。

U4 于 2026-11-25 由 YYYYMMDD 整数差改为 civil_days（Q-20261125-04），此前没有任何测试引用 sleeve。
用一份合成缓存 + monkeypatch 的信号，只让日期决定事件去留：
① 信号日→次日跨月（整数差 70，实际 3 个日历日）→ 保留；
② 信号日→次日真停牌 15 个日历日 → 剔除。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SB_DIR = REPO_ROOT / "tools" / "stage-bottom"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sleeve():
    """按路径加载 sleeve.py。它头部的 `from run_backtest import …` 用裸模块名，而 jinniu 也有
    同名 run_backtest.py——临时把 stage-bottom 这份登记为 `run_backtest`，装完还原。"""
    saved = {k: sys.modules.get(k) for k in ("run_backtest", "stage_bottom")}
    old = list(sys.path)
    sys.path.insert(0, str(SB_DIR))
    try:
        _load("run_backtest", SB_DIR / "run_backtest.py")
        return _load("sleeve_under_test", SB_DIR / "sleeve.py")
    finally:
        sys.path[:] = old
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _calendar():
    """约 330 根：第 i_cross 根的次日跨月；第 i_cross+10 根之后停牌 11 个交易日（15 个日历日）。"""
    dates = list(pd.bdate_range("2022-01-03", periods=345))
    i_cross = next(i for i in range(260, len(dates) - 1)
                   if dates[i].month != dates[i + 1].month)
    gap_at = i_cross + 10
    dates = dates[:gap_at + 1] + dates[gap_at + 12:]
    return dates, i_cross, gap_at


def _write_stock(path: Path, dates, price: float = 10.0) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for d in dates:
            fh.write(json.dumps({"date": d.strftime("%Y-%m-%d"), "open": price, "high": price + 0.5,
                                 "low": price - 0.5, "close": price, "amount": 5e7}) + "\n")


def test_u4_keeps_month_crossing_and_drops_true_suspension(tmp_path, monkeypatch, sleeve):
    dates, i_cross, gap_at = _calendar()
    assert len(dates) >= 300                           # collect 的最短历史门槛
    ymd = [int(d.strftime("%Y%m%d")) for d in dates]
    assert ymd[i_cross + 1] - ymd[i_cross] > sleeve.GAP_DAYS        # 整数差 > 10：旧写法会误删
    assert (dates[i_cross + 1] - dates[i_cross]).days <= sleeve.GAP_DAYS
    assert (dates[gap_at + 1] - dates[gap_at]).days > sleeve.GAP_DAYS   # 真停牌（≥14 个日历日）

    path = tmp_path / "600001.SH.jsonl"
    _write_stock(path, dates)
    sig = np.zeros(len(dates), dtype=bool)
    sig[i_cross] = True
    sig[gap_at] = True
    monkeypatch.setattr(sleeve, "stage_bottom_signals", lambda hgh, low, c: {"rsi_up20": sig})
    monkeypatch.setattr(sleeve, "stage_bottom_indicators",
                        lambda hgh, low, c: {"rsi5": np.zeros(len(c)), "adx": np.full(len(c), 80.0)})

    ev_gate, ev_base, _, _ = sleeve.collect([path])
    expected = [ymd[i_cross + 1]]
    assert sorted(e["e_di"] for e in ev_gate) == expected
    assert sorted(e["e_di"] for e in ev_base) == expected
