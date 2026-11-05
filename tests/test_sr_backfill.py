from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

import backfill  # noqa: E402


def _page_df(dates: list[str]) -> "pd.DataFrame":
    n = len(dates)
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [10.0] * n, "high": [11.0] * n,
        "low": [9.0] * n, "close": [10.5] * n,
        "volume": [1000.0] * n, "amount": [10500.0] * n,
    })


def test_fetch_paginated_dedupes_and_uses_start(monkeypatch):
    pages = [_page_df(["2026-11-02", "2026-10-30"]),
             _page_df(["2026-10-30", "2026-10-29"]),
             _page_df([])]
    calls = []

    def fake_call(method, **kw):
        calls.append((method, kw))
        return pages[len(calls) - 1]

    monkeypatch.setattr(backfill, "_mootdx_call", fake_call)
    rows = backfill.fetch_bars_paginated("881101", index=True, total=6, page=2)
    assert [r["date"] for r in rows] == ["2026-10-29", "2026-10-30", "2026-11-02"]
    assert calls[1][1]["start"] == 2          # start 分页（持久化 spec L284 口径）
    assert calls[0][0] == "index_bars" and calls[0][1]["frequency"] == 9


def test_fetch_etf_strips_suffix_for_api(monkeypatch):
    seen = {}

    def fake_call(method, **kw):
        seen["symbol"] = kw["symbol"]
        return _page_df(["2026-11-02"])

    monkeypatch.setattr(backfill, "_mootdx_call", fake_call)
    backfill.fetch_bars_paginated("512480.SH", index=False)
    assert seen["symbol"] == "512480"        # API 製码，路径带后缀


def test_fetch_returns_empty_when_source_down(monkeypatch):
    def boom(method, **kw):
        raise RuntimeError("server down")

    monkeypatch.setattr(backfill, "_mootdx_call", boom)
    assert backfill.fetch_bars_paginated("881101", index=True) == []


def test_verify_depth_report(tmp_path: Path):
    d = tmp_path / "sector" / "series"
    d.mkdir(parents=True)
    (d / "881101.jsonl").write_text(
        '{"date":"2020-01-03","close":1.0}\n{"date":"2020-01-06","close":1.1}\n',
        encoding="utf-8")
    rows = backfill.verify_depth([("881101", True)], data_root=tmp_path,
                                 expect_bars=2500)
    assert rows[0] == {"code": "881101", "rows": 2, "first": "2020-01-03",
                       "last": "2020-01-06", "shortfall": 2498}


def test_fetch_handles_real_mootdx_datetime_column(monkeypatch):
    # 真实 mootdx schema（2026-11-05 实测 index_bars/bars）：无 date 列，
    # datetime 索引同时重复出现为列（mootdx_source 头注释同口径）。
    n = 2
    df = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-10-30", "2026-11-02"]),
        "open": [10.0] * n, "high": [11.0] * n,
        "low": [9.0] * n, "close": [10.5] * n,
        "volume": [1000.0] * n, "amount": [10500.0] * n,
    })
    monkeypatch.setattr(backfill, "_mootdx_call", lambda m, **kw: df)
    rows = backfill.fetch_bars_paginated("881101", index=True, total=2, page=800)
    assert [r["date"] for r in rows] == ["2026-10-30", "2026-11-02"]


def test_read_candidates_skips_comment_lines(tmp_path: Path):
    # delisted-etf.txt 约定（Step 5）：每行一代码，整行 # 注释与行尾 # 来源注释都要跳过
    p = tmp_path / "delisted-etf.txt"
    p.write_text("# 来源: 上交所/深交所终止上市公告 2021-2025\n"
                 "516680.SH   # 建信细分有色 2022-09 终止上市\n"
                 "\n"
                 "# 宽基对照探针\n"
                 "159897.SZ\n", encoding="utf-8")
    assert backfill._read_candidates(p) == ["516680.SH", "159897.SZ"]


def test_verify_depth_parses_market_data_io_format(tmp_path: Path):
    # 真实落盘格式（踩坑实录）：market_data_io 用 json.dumps 默认分隔符，
    # 冒号后带空格 {"date": "2023-07-13"}——按 '"date":"' 紧凑切分必炸 IndexError。
    d = tmp_path / "market" / "series"
    d.mkdir(parents=True)
    (d / "512480.SH.jsonl").write_text(
        '{"date": "2023-07-13", "close": 0.906, "source": "mootdx"}\n'
        '{"date": "2023-07-14", "close": 0.919, "source": "mootdx"}\n',
        encoding="utf-8")
    rows = backfill.verify_depth([("512480.SH", False)], data_root=tmp_path,
                                 expect_bars=2600)
    assert rows[0]["first"] == "2023-07-13"
    assert rows[0]["last"] == "2023-07-14"
    assert rows[0]["rows"] == 2
