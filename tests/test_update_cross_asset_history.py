"""update_cross_asset_history 单测（Q-20261109-04 C1）：全封闭不联网。

覆盖：klines 解析（7 列/坏行/amount 指纹）、beg 增量判定（浅 series 全窗口）、
batch 档权威覆盖快照行、节流重试的请求侧效果（mock 计数）。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import update_cross_asset_history as ucah


def _kline_response(klines: list[str]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"data": {"klines": klines}}
    return mock


class ParseKlinesTests(unittest.TestCase):
    def test_seven_column_row_with_amount_fingerprint(self) -> None:
        rows = ucah.parse_klines(["2026-11-05,9806.31,9011.14,9838.13,8997.39,0,0"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-11-05")
        self.assertEqual(row["close"], 9011.14)  # H1 档案基准日
        self.assertEqual(row["amount"], 0.0)     # 恒非 None = batch 写者指纹
        self.assertEqual(row["source"], "eastmoney-kline")

    def test_short_and_garbage_lines_skipped(self) -> None:
        rows = ucah.parse_klines(["2026-11-05,1,2,3", "bad,line,with,words,not,numbers,here",
                                  "2026-11-06,1.0,2.0,3.0,0.5,10,20"])
        self.assertEqual(len(rows), 1)

    def test_data_null_returns_empty(self) -> None:
        self.assertEqual(ucah.parse_klines([]), [])


class UpdateTickerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_series(self, ticker: str, lines: list[str]) -> None:
        # 走真实 io 层格式：快照行 amount=None（钩子指纹）
        target = self.root / "market" / "series"
        target.mkdir(parents=True)
        (target / f"{ticker}.jsonl").write_text("".join(lines), encoding="utf-8")

    @patch("update_cross_asset_history.requests.get", return_value=_kline_response([
        "2026-11-05,9806.31,9011.14,9838.13,8997.39,0,0",
        "2026-11-06,9495.21,9390.25,9627.26,9221.35,0,0",
    ]))
    def test_batch_overwrites_snapshot_same_day(self, mock_get) -> None:
        # 快照钩子先写过 11-06 盘中值（amount=None、close=9500.0 盘中）
        self._write_series("^SOX", [
            '{"date": "2026-11-05", "close": 9011.14, "volume": null, "amount": null, "source": "eastmoney"}\n',
            '{"date": "2026-11-06", "close": 9500.0, "volume": null, "amount": null, "source": "eastmoney"}\n',
        ])
        self.assertEqual(ucah.update_ticker(self.root, "^SOX", "251.SOX", force=True), "written")
        lines = (self.root / "market" / "series" / "^SOX.jsonl").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        import json
        last = json.loads(lines[-1])
        self.assertEqual(last["close"], 9390.25)   # 收盘权威覆盖盘中 9500
        self.assertIsNotNone(last["amount"])       # batch 指纹写入
        # beg 参数=force 时从窗口起点（不传 today 依赖的具体值，只断言不是尾行增量）
        beg = mock_get.call_args.kwargs["params"]["beg"]
        self.assertNotEqual(beg, "20261106")

    @patch("update_cross_asset_history.requests.get", return_value=_kline_response([
        "2026-11-09,102.25,102.21,102.29,102.20,0,0",
    ]))
    def test_incremental_beg_is_tail_when_covered(self, mock_get) -> None:
        # series 首行早于窗口起点（历史完整）→ 增量模式，beg=尾行日（含当天覆盖）
        self._write_series("DX-Y.NYB", [
            '{"date": "2024-01-02", "close": 101.0, "amount": 0.0, "source": "eastmoney-kline"}\n'
            '{"date": "2026-11-06", "close": 102.30, "amount": 0.0, "source": "eastmoney-kline"}\n',
        ])
        ucah.update_ticker(self.root, "DX-Y.NYB", "100.UDI", backfill_days=800)
        beg = mock_get.call_args.kwargs["params"]["beg"]
        self.assertEqual(beg, "20261106")

    @patch("update_cross_asset_history.requests.get", return_value=_kline_response([
        "2026-11-09,102.25,102.21,102.29,102.20,0,0",
    ]))
    def test_shallow_series_gets_full_window(self, mock_get) -> None:
        # 浅 series（快照钩子攒几天、首行晚于窗口起点）→ 必须全窗口回补，
        # 不能只拿 1-2 行增量（2026-11-09 首跑实测 bug 的回归锁）
        self._write_series("^SOX", [
            '{"date": "2026-11-06", "close": 9390.25, "amount": null, "source": "eastmoney"}\n',
        ])
        ucah.update_ticker(self.root, "^SOX", "251.SOX", backfill_days=800)
        beg = mock_get.call_args.kwargs["params"]["beg"]
        self.assertEqual(beg[:4], (date.today() - timedelta(days=800)).strftime("%Y"))  # 全窗口起点

    @patch("update_cross_asset_history.requests.get", return_value=_kline_response([]))
    def test_empty_klines_returns_empty(self, mock_get) -> None:
        self.assertEqual(ucah.update_ticker(self.root, "^IXIC", "100.NDX", force=True), "empty")

    def test_tickers_validation_rejects_unknown_and_xau(self) -> None:
        with self.assertRaises(SystemExit):
            ucah.main(["--tickers", "XAUUSD=X"])  # 无 secid 的票显式拒绝
        with self.assertRaises(SystemExit):
            ucah.main(["--tickers", "600276.SH"])  # A 股票不属于本脚本


class ThrottleRetryTests(unittest.TestCase):
    def test_retry_once_then_raise(self) -> None:
        import requests as _rq
        with patch("update_cross_asset_history.requests.get",
                   side_effect=_rq.exceptions.ConnectionError("peer closed")) as mock_get, \
                patch("update_cross_asset_history.time.sleep") as mock_sleep:
            with self.assertRaises(RuntimeError):
                ucah.fetch_kline_rows("251.SOX", "20260101")
        self.assertEqual(mock_get.call_count, 2)   # 1 次 + 重试 1 次
        mock_sleep.assert_called()                 # 重试前退避


if __name__ == "__main__":
    unittest.main()
