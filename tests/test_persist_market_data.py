"""persist_market_data 单测。钩子的天条：失败永不阻塞日报（spec §3）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401

import persist_market_data as pmd  # noqa: E402
from market_data_io import read_series_rows, series_file  # noqa: E402


def _quote(ticker: str, **over: dict) -> dict:
    base = {"ticker": ticker, "price": 71.54, "open": 71.0, "dayHigh": 73.2, "dayLow": 70.5,
            "volume": 123456.0, "tradeDate": "2026-11-02", "source": "mootdx"}
    base.update(over)
    return base


def _snapshot(quotes: list[dict]) -> dict:
    return {"quotes": quotes, "movers": [], "earnings": [],
            "meta": {"fetched_at": "2026-11-02T08:30:00+00:00", "quotes": {"state": "ok"}}}


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_snapshot_wraps_full_payload_and_overwrites_same_day(self) -> None:
        path1 = pmd.save_daily_snapshot(_snapshot([_quote("600276.SH")]), self.root, today="2026-11-02")
        self.assertEqual(json.loads(path1.read_text(encoding="utf-8"))["payload"]["meta"]["quotes"]["state"], "ok")
        self.assertEqual(path1.name, "2026-11-02.json")
        path2 = pmd.save_daily_snapshot(_snapshot([_quote("300476.SZ")]), self.root, today="2026-11-02")
        self.assertEqual(path1, path2)  # 同日覆盖
        payload = json.loads(path2.read_text(encoding="utf-8"))["payload"]
        self.assertEqual(payload["quotes"][0]["ticker"], "300476.SZ")


class SeriesAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_maps_to_series_row(self) -> None:
        row = pmd.quote_to_series_row(_quote("600276.SH"))
        self.assertEqual(row["date"], "2026-11-02")
        self.assertEqual(row["close"], 71.54)
        self.assertEqual(row["high"], 73.2)
        self.assertIsNone(row["amount"])  # 钩子路径无 amount（spec §4.2）

    def test_unparseable_tradedate_returns_none(self) -> None:
        self.assertIsNone(pmd.quote_to_series_row(_quote("^SOX", tradeDate="")))

    def test_nan_inf_prices_become_null(self) -> None:
        # Minor：与 update_market_series.bars_to_rows 同款清洗——NaN/inf 不进 JSONL
        row = pmd.quote_to_series_row(_quote("600276.SH", price=float("nan"), volume=float("inf")))
        self.assertIsNone(row["close"])
        self.assertIsNone(row["volume"])

    def test_appends_per_ticker_and_skips_bad_dates(self) -> None:
        n = pmd.append_series_from_snapshot(
            _snapshot([_quote("600276.SH"), _quote("^SOX", tradeDate="garbage")]), self.root)
        self.assertEqual(n, 1)
        self.assertTrue(series_file(self.root, "600276.SH").exists())
        self.assertFalse(series_file(self.root, "^SOX").exists())  # 坏日期只进快照不进 series

    def test_snapshot_writer_fills_null_only(self) -> None:
        # 预置批量权威行（完整 OHLCV），钩子行只能补 null 不能覆盖
        pmd.append_series_from_snapshot(_snapshot([_quote("600276.SH")]), self.root)
        path = series_file(self.root, "600276.SH")
        mio_rows = read_series_rows(path)
        mio_rows[0]["amount"] = 88900000.0
        path.write_text("".join(json.dumps(r) + "\n" for r in mio_rows), encoding="utf-8")
        pmd.append_series_from_snapshot(
            _snapshot([_quote("600276.SH", price=999.0)]), self.root)  # 盘中价乱值
        self.assertEqual(read_series_rows(path)[-1]["close"], 71.54)  # 没被覆盖


class HookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_hook_swallows_exceptions(self) -> None:
        with patch.object(pmd, "save_daily_snapshot", side_effect=RuntimeError("boom")):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)  # 不抛即通过

    def test_report_source_wires_hook(self) -> None:
        source = (REPO_ROOT / "tools/daily-watch/scripts/generate_daily_report.py").read_text(encoding="utf-8")
        self.assertIn("_persist_market_data_hook(market_data)", source)
        self.assertIn("def _persist_market_data_hook(", source)


if __name__ == "__main__":
    unittest.main()
