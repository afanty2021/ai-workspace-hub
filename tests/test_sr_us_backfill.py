# tests/test_sr_us_backfill.py
import numpy as np
import pandas as pd

from us_backfill import (DATA_ROOT, US_MEMBERS, annual_close_returns,
                         check_anchors, df_to_rows, split_residues)


def _df(sym: str, dates, closes, volumes=None) -> pd.DataFrame:
    cols = pd.MultiIndex.from_product([[sym], ["Open", "High", "Low", "Close", "Volume"]])
    n = len(dates)
    vols = np.ones(n) * 1e6 if volumes is None else volumes
    data = np.column_stack([np.array(closes), np.array(closes) * 1.01,
                            np.array(closes) * 0.99, np.array(closes), vols])
    return pd.DataFrame(data, index=pd.DatetimeIndex(dates), columns=cols)


def test_df_to_rows_schema_and_amount():
    df = _df("XLE", ["2020-01-02", "2020-01-03"], [10.0, 11.0])
    rows = df_to_rows("XLE", df)
    assert rows[0]["date"] == "2020-01-02"
    assert rows[0]["source"] == "yfinance"
    assert abs(rows[0]["amount"] - 10.0 * 1e6) < 1e-6      # amount = close × volume
    assert set(rows[0]) == {"date", "open", "high", "low", "close",
                            "volume", "amount", "source"}


def test_annual_close_returns_compounds_year_end():
    # 首年无前年末基准 → 不在输出字典（年际收益语义；SPY_ANCHORS 2013 键 =
    # 2012 末→2013 末）——夹具必须含前年基准行（复查轮 N1：否则 got[2020]
    # KeyError，且易诱导执行者错改实现语义毁锚点口径）。实现不动。
    rows = [{"date": "2019-12-31", "close": 100.0},
            {"date": "2020-06-01", "close": 100.0},
            {"date": "2020-12-31", "close": 110.0},
            {"date": "2021-06-01", "close": 121.0},
            {"date": "2021-12-31", "close": 99.0}]
    got = annual_close_returns(rows)
    assert abs(got[2020] - 0.10) < 1e-12 and abs(got[2021] - (99.0 / 110.0 - 1)) < 1e-12


def test_check_anchors_reports_out_of_band_and_missing():
    # 计划评审 M-6：锚点年缺失 = 数据不完整，必须硬警报，不静默跳过。
    anchors = {2022: (-0.205, -0.16)}
    assert check_anchors({2022: -0.181}, anchors) == []
    errs = check_anchors({2022: -0.05}, anchors)
    assert len(errs) == 1 and "2022" in errs[0]
    miss = check_anchors({}, anchors)
    assert len(miss) == 1 and "缺失" in miss[0]


def test_split_residues_detects_jump():
    rows = [{"date": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 11)]
    rows.append({"date": "2020-01-13", "close": 50.0})     # 周一跳变 -50%
    res = split_residues(rows)
    assert res == [("2020-01-13", -0.5)]


def test_constants_and_layout():
    assert len(US_MEMBERS) == 11 and "VOX" in US_MEMBERS and "IYR" in US_MEMBERS
    assert DATA_ROOT.name == "us-sector"
