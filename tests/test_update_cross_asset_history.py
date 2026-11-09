"""update_cross_asset_history 单测（Q-20261109-04 C1）：全封闭不联网。

覆盖：klines 解析（7 列/坏行/amount 指纹）、beg 增量判定（浅 series 全窗口）、
batch 档权威覆盖快照行、节流重试的请求侧效果（mock 计数）、
Nasdaq 历史主源（^SOX 深度受限的票级覆盖：解析/合流/东财降级/main 分发）、
新浪全球期货日线主源（XAUUSD=X 无东财 secid：JSONP 解析/合流/无降级 fail）。
"""

from __future__ import annotations

import contextlib
import io
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


def _nasdaq_response(rows: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"data": {"symbol": "SOX", "totalRecords": len(rows),
                                       "tradesTable": {"rows": rows}}}
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

    def test_tickers_validation_rejects_unknown_ticker(self) -> None:
        # XAUUSD=X 已合法（sina 源族，见 SinaSourceTests）；未知票仍拒绝。
        # 封闭性教训（2026-11-09）：本测试曾裸跑 main——真打新浪+把真实 data root
        # 的 XAUUSD=X 回补了。main 类测试必须 mock 网络与 data root。
        with tempfile.TemporaryDirectory() as tmp:
            with patch("update_cross_asset_history.requests.get",
                       return_value=_kline_response([])), \
                    patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
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


def _nasdaq_row(day: str, close: str, o: str, h: str, lo: str) -> dict:
    return {"date": day, "close": close, "volume": "--", "open": o, "high": h, "low": lo}


class ParseNasdaqHistoryTests(unittest.TestCase):
    def test_comma_dates_desc_order_and_fingerprint(self) -> None:
        # API 返回新→旧；解析后必须升序（series 文件按日期升序追加）
        rows = ucah.parse_nasdaq_history([
            _nasdaq_row("11/06/2026", "9,390.25", "9,495.21", "9,627.26", "9,221.35"),
            _nasdaq_row("11/05/2026", "9,011.14", "9,806.31", "9,838.13", "8,997.39"),
        ])
        self.assertEqual([r["date"] for r in rows], ["2026-11-05", "2026-11-06"])
        self.assertEqual(rows[0]["close"], 9011.14)  # H1 档案基准日
        self.assertIsNone(rows[0]["volume"])          # 指数 "--" → None
        self.assertIsNone(rows[0]["amount"])          # 无官方成交额
        self.assertEqual(rows[0]["source"], "nasdaq-historical")  # 写者指纹

    def test_bad_rows_skipped(self) -> None:
        rows = ucah.parse_nasdaq_history([
            {"date": "bad/date", "close": "1,0", "volume": "--",
             "open": "1", "high": "1", "low": "1"},
            {"date": "11/06/2026", "close": "", "volume": "--",
             "open": "9,495.21", "high": "9,627.26", "low": "9,221.35"},  # close 缺失
            _nasdaq_row("11/06/2026", "9,390.25", "9,495.21", "9,627.26", "9,221.35"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-11-06")

    def test_volume_na_sentinel_keeps_valid_row(self) -> None:
        # Nasdaq 对个别交易日（半日市/数据缺口）volume 用 "N/A"——有效 OHLC 行
        # 不得因 volume N/A 整行丢弃（评审 M-1：哨兵元组曾缺 N/A 家族，
        # float("N/A") 抛 ValueError 会静默吞掉该日 SOX）
        rows = ucah.parse_nasdaq_history([
            {"date": "11/27/2025", "close": "9,000.00", "volume": "N/A",
             "open": "9,100.00", "high": "9,150.00", "low": "8,950.00"},
        ])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["volume"])
        self.assertEqual(rows[0]["close"], 9000.00)


class NasdaqSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        target = self.root / "market" / "series"
        target.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_nasdaq_source_fills_gap_and_preserves_same_day_provenance(self) -> None:
        # 东财浅历史（首行 2026-07）+ Nasdaq 全窗 → gap 合流；
        # 同日行 batch 合并 None 字段跳过 → eastmoney 的 amount 指纹保留
        (self.root / "market" / "series" / "^SOX.jsonl").write_text(
            '{"date": "2026-07-06", "close": 12900.14, "volume": 0.0, "amount": 0.0, "source": "eastmoney-kline"}\n'
            '{"date": "2026-11-06", "close": 9390.25, "volume": 0.0, "amount": 0.0, "source": "eastmoney-kline"}\n',
            encoding="utf-8")
        with patch("update_cross_asset_history.requests.get", return_value=_nasdaq_response([
            _nasdaq_row("11/06/2026", "9,390.25", "9,495.21", "9,627.26", "9,221.35"),
            _nasdaq_row("11/05/2026", "9,011.14", "9,806.31", "9,838.13", "8,997.39"),
        ])) as mock_get:
            status = ucah.update_ticker(self.root, "^SOX", "251.SOX",
                                        backfill_days=800, history_source="nasdaq")
        self.assertEqual(status, "written")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["assetclass"], "index")
        self.assertEqual(params["todate"], date.today().isoformat())
        self.assertEqual(params["fromdate"][:4],
                         (date.today() - timedelta(days=800)).strftime("%Y"))  # 全窗起点
        import json
        lines = (self.root / "market" / "series" / "^SOX.jsonl").read_text(
            encoding="utf-8").splitlines()
        by_date = {json.loads(ln)["date"]: json.loads(ln) for ln in lines}
        self.assertEqual(by_date["2026-11-05"]["source"], "nasdaq-historical")  # gap 合流
        kept = by_date["2026-11-06"]
        # 同日行：batch 权威写者按设计覆盖 source（与快照→eastmoney-kline 同机制）；
        # nasdaq 无官方量额（None）→ 东财的 volume/amount 保留
        self.assertEqual(kept["source"], "nasdaq-historical")
        self.assertEqual(kept["amount"], 0.0)
        self.assertEqual(kept["volume"], 0.0)

    def test_nasdaq_failure_falls_back_to_eastmoney(self) -> None:
        # Nasdaq 两次全炸 → 降级东财 klines（浅历史强于无）
        import requests as _rq
        self._exc = _rq.exceptions.ConnectionError("nasdaq down")
        (self.root / "market" / "series" / "^SOX.jsonl").write_text(
            '{"date": "2026-11-06", "close": 9390.25, "volume": 0.0, "amount": 0.0, "source": "eastmoney-kline"}\n',
            encoding="utf-8")
        with patch("update_cross_asset_history.requests.get",
                   side_effect=[self._exc, self._exc,
                                _kline_response(["2026-11-06,9495.21,9390.25,9627.26,9221.35,0,0"])]) as mock_get, \
                patch("update_cross_asset_history.time.sleep"):
            status = ucah.update_ticker(self.root, "^SOX", "251.SOX",
                                        backfill_days=800, history_source="nasdaq")
        self.assertEqual(status, "written")
        self.assertEqual(mock_get.call_count, 3)  # nasdaq×2（含重试）+ 东财×1
        import json
        last = json.loads((self.root / "market" / "series" / "^SOX.jsonl")
                          .read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["source"], "eastmoney-kline")

    def test_nasdaq_empty_response_degrades_with_warning(self) -> None:
        # 200 + data:null（典型反爬形态）不算异常但等于主源失效——必须留痕
        # 再降级（评审 M-2：静默降级会让 ^SOX 长期退化回浅历史而无人察觉）
        (self.root / "market" / "series" / "^SOX.jsonl").write_text(
            '{"date": "2026-11-06", "close": 9390.25, "volume": 0.0, "amount": 0.0, "source": "eastmoney-kline"}\n',
            encoding="utf-8")
        empty = MagicMock()
        empty.raise_for_status.return_value = None
        empty.json.return_value = {"data": None}
        captured = io.StringIO()
        with patch("update_cross_asset_history.requests.get",
                   side_effect=[empty, _kline_response(["2026-11-06,9495.21,9390.25,9627.26,9221.35,0,0"])]) as mock_get, \
                contextlib.redirect_stderr(captured):
            status = ucah.update_ticker(self.root, "^SOX", "251.SOX",
                                        backfill_days=800, history_source="nasdaq")
        self.assertEqual(status, "written")
        self.assertEqual(mock_get.call_count, 2)  # 空成功不重试 + 东财×1
        self.assertIn("Nasdaq 历史返回空", captured.getvalue())

class ParseSinaGlobalHistoryTests(unittest.TestCase):
    def test_jsonp_wrapper_strip_sort_and_fingerprint(self) -> None:
        # 真实外壳：/*<script>*/\nvar t=([...]);；API 新→旧返回，解析后升序
        payload = ('/*<script>location.href=\'//sina.com\';</script>*/\nvar t=('
                   '[{"date":"2026-11-06","open":"4087.480","high":"4106.790","low":"4028.270",'
                   '"close":"4070.750","volume":"0","position":"0","s":"0.000"},'
                   '{"date":"2026-11-05","open":"4064.100","high":"4146.770","low":"4057.760",'
                   '"close":"4124.030","volume":"0","position":"0","s":"0.000"}]);')
        rows = ucah.parse_sina_global_history(payload)
        self.assertEqual([r["date"] for r in rows], ["2026-11-05", "2026-11-06"])
        # 11-06 全 OHLC 与快照行逐位一致（同源族同日切口径的实证锚点）
        self.assertEqual(rows[1]["close"], 4070.75)
        self.assertEqual(rows[1]["open"], 4087.48)
        self.assertIsNone(rows[1]["volume"])   # 现货无量，与快照行 volume null 一致
        self.assertIsNone(rows[1]["amount"])
        self.assertEqual(rows[1]["source"], "sina-global")

    def test_wrapper_missing_or_garbage_returns_empty(self) -> None:
        self.assertEqual(ucah.parse_sina_global_history("var t=[];"), [])
        self.assertEqual(ucah.parse_sina_global_history("not jsonp at all"), [])
        self.assertEqual(ucah.parse_sina_global_history('var t=([{"date":"bad","open":"x"}]);'), [])


class SinaSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "market" / "series").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _sina_mock(self) -> MagicMock:
        # 直接返回响应 mock（patch(return_value=X) 语义=get() 返回 X 本体，
        # 不再触发一层调用——多包一层会让 resp.text 变 child mock）。
        # 首行 2020-01-02 在 800 天回补窗外：必须被 fetch 的窗口过滤剔除
        # （评审 I-2——删过滤后 API 全史会一次性吞入，靠 len==3 锁住）
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = ('/*<script>*/\nvar t=('
                  '[{"date":"2026-11-05","open":"4064.100","high":"4146.770","low":"4057.760",'
                  '"close":"4124.030","volume":"0","position":"0","s":"0.000"},'
                  '{"date":"2026-11-06","open":"4087.480","high":"4106.790","low":"4028.270",'
                  '"close":"4070.750","volume":"0","position":"0","s":"0.000"},'
                  '{"date":"2026-11-09","open":"4066.570","high":"4134.070","low":"4054.250",'
                  '"close":"4128.750","volume":"0","position":"0","s":"0.000"},'
                  '{"date":"2020-01-02","open":"1520.000","high":"1530.000","low":"1510.000",'
                  '"close":"1525.000","volume":"0","position":"0","s":"0.000"}]);')
        return resp

    def test_sina_source_fills_gap_and_overwrites_snapshot_day(self) -> None:
        # 快照钩子行（sina 实时、volume null）+ 新浪日线全窗 → gap 合流；
        # 同日 batch 权威覆盖 source（与东财/Nasdaq 族同机制）
        (self.root / "market" / "series" / "XAUUSD=X.jsonl").write_text(
            '{"date": "2026-11-06", "open": 4087.48, "high": 4106.79, "low": 4028.27, '
            '"close": 4070.75, "volume": null, "amount": null, "source": "sina"}\n',
            encoding="utf-8")
        with patch("update_cross_asset_history.requests.get",
                   return_value=self._sina_mock()) as mock_get:
            status = ucah.update_ticker(self.root, "XAUUSD=X", "",
                                        backfill_days=800, history_source="sina")
        self.assertEqual(status, "written")
        self.assertEqual(mock_get.call_args.kwargs["params"], {"symbol": "XAU"})
        import json
        lines = (self.root / "market" / "series" / "XAUUSD=X.jsonl").read_text(
            encoding="utf-8").splitlines()
        by_date = {json.loads(ln)["date"]: json.loads(ln) for ln in lines}
        self.assertEqual(len(lines), 3)
        self.assertEqual(by_date["2026-11-05"]["source"], "sina-global")  # gap 合流
        self.assertEqual(by_date["2026-11-06"]["source"], "sina-global")  # 同日权威覆盖
        self.assertEqual(by_date["2026-11-09"]["close"], 4128.75)         # 新尾行

    def test_sina_failure_without_secid_is_fail(self) -> None:
        # XAUUSD=X 无东财 secid → 新浪炸后如实计 fail（不假装降级、不空请求）
        import requests as _rq
        with patch("update_cross_asset_history.requests.get",
                   side_effect=_rq.exceptions.ConnectionError("sina down")) as mock_get, \
                patch("update_cross_asset_history.time.sleep"):
            status = ucah.update_ticker(self.root, "XAUUSD=X", "",
                                        backfill_days=800, history_source="sina")
        self.assertEqual(status, "fail")
        self.assertEqual(mock_get.call_count, 2)  # 1 次 + 重试 1 次，未再打东财

    def test_main_accepts_xau_ticker_and_dispatches_sina(self) -> None:
        # --tickers 白名单扩新浪族；分发走 symbol 参数（非东财 klt）
        with patch("update_cross_asset_history.requests.get",
                   return_value=self._sina_mock()) as mock_get, \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            ucah.main(["--tickers", "XAUUSD=X"])
        self.assertEqual(mock_get.call_args.kwargs["params"], {"symbol": "XAU"})
        with self.assertRaises(SystemExit):
            ucah.main(["--tickers", "600276.SH"])


    def test_main_dispatch_routes_sox_to_nasdaq_and_tnx_to_eastmoney(self) -> None:
        # main 按 NASDAQ_HISTORY_SYMBOLS 分发：^SOX 出 index 参数、^TNX 出 klt 参数
        # （resolve_data_root 在 main 内局部 import → patch 源模块 market_data_io；
        # mock 给有效行——空数据会按设计降级东财，分发断言就不成立了）
        with patch("update_cross_asset_history.requests.get", return_value=_nasdaq_response([
                _nasdaq_row("11/06/2026", "9,390.25", "9,495.21", "9,627.26", "9,221.35"),
        ])) as mock_get, \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            ucah.main(["--tickers", "^SOX"])
        self.assertIn("assetclass", mock_get.call_args.kwargs["params"])
        with patch("update_cross_asset_history.requests.get",
                   return_value=_kline_response(["2026-11-07,1,2,3,4,0,0"])) as mock_get, \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            ucah.main(["--tickers", "^TNX"])
        self.assertIn("klt", mock_get.call_args.kwargs["params"])


if __name__ == "__main__":
    unittest.main()
