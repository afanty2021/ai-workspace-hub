"""persist_market_data 单测。钩子的天条：失败永不阻塞日报（spec §3）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

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

    def test_snapshot_filename_follows_payload_fetched_at(self) -> None:
        # Minor③：回填旧日期快照必须写旧日期文件——旧行为用墙钟命名，会把旧
        # payload 静默重写进当日快照（今天的 daily 文件被昨天的数据覆盖）
        snap = dict(_snapshot([]), meta={"fetched_at": "2026-11-01T09:00:00+00:00",
                                         "quotes": {"state": "ok"}})
        self.assertEqual(pmd.save_daily_snapshot(snap, self.root).name, "2026-11-01.json")

    def test_snapshot_falls_back_to_wall_clock_without_valid_fetched_at(self) -> None:
        # fetched_at 缺失或日历非法（02-31）都退墙钟——与旧行为一致的兜底路径
        for meta in ({}, {"fetched_at": "2026-02-31T09:00:00+00:00"},
                     {"fetched_at": "not-a-date"}):
            snap = {"quotes": [], "movers": [], "earnings": [], "meta": meta}
            path = pmd.save_daily_snapshot(snap, self.root)
            self.assertEqual(path.name, datetime.now().strftime("%Y-%m-%d") + ".json", msg=meta)

    def test_snapshot_today_injection_wins_over_fetched_at(self) -> None:
        snap = dict(_snapshot([]), meta={"fetched_at": "2026-11-01T09:00:00+00:00"})
        self.assertEqual(pmd.save_daily_snapshot(snap, self.root, today="2026-12-31").name,
                         "2026-12-31.json")


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


class UsSessionGateTests(unittest.TestCase):
    """friction 2026-11-03 第 2 次修根：实时源盘前/盘中报价只进快照不进 series。

    两个已发生的事故形态都要被挡：①盘前抓取价格=上一收盘、asOf=当日（周五价
    10,687.62 被写成 11-02 行，险些漏判 SOX 破线）；②个股盘前指示价（NVDA 有
    盘前交易）被写成当日收盘行。第五轮评审 I-1：受闸集合=四个实时报价源
    （nasdaq/fmp/finnhub/yfinance）——nasdaq 是浏览器头抓取型端点，一挂降级链
    下一环顶上就是同构事故复发。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
        return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York"))

    def test_pre_market_prev_close_misdated_blocked(self) -> None:
        # 形态①：周一 06:10 ET 盘前抓取，价格=周五收盘、asOf=周一（原始事故）
        q = _quote("^SOX", tradeDate="Nov 2, 2026 6:10 AM ET", source="nasdaq", price=10687.62)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 2, 6, 11))
        self.assertEqual(n, 0)
        self.assertFalse(series_file(self.root, "^SOX").exists())

    def test_pre_market_indicative_price_blocked(self) -> None:
        # 形态②：个股盘前指示价，asOf=今日盘前（当日未收盘）
        q = _quote("NVDA", tradeDate="Nov 3, 2026 5:25 AM ET", source="nasdaq", price=205.3964)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 3, 5, 26))
        self.assertEqual(n, 0)
        self.assertFalse(series_file(self.root, "NVDA").exists())

    def test_intraday_quote_blocked(self) -> None:
        # 盘中动态价同理（与 A 股盘中动态 bar 同构病灶）
        q = _quote("NVDA", tradeDate="Nov 3, 2026 11:00 AM ET", source="nasdaq", price=204.0)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 3, 11, 1))
        self.assertEqual(n, 0)

    def test_past_session_date_written_next_day(self) -> None:
        # 隔天抓取：指数 asOf=最后交易日 < 今天 → 正确落行（事故当日的正确路径：
        # 11-03 盘前抓到 asOf 11-02 + 真实周一收盘 10,328.33）
        q = _quote("^SOX", tradeDate="Nov 2, 2026 4:00 PM ET", source="nasdaq", price=10328.33)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 3, 5, 25))
        self.assertEqual(n, 1)
        rows = read_series_rows(series_file(self.root, "^SOX"))
        self.assertEqual((rows[-1]["date"], rows[-1]["close"]), ("2026-11-02", 10328.33))

    def test_same_day_after_close_written(self) -> None:
        # 刚收盘：asOf=今天且 ET ≥ 16:00 → 写
        q = _quote("NVDA", tradeDate="Nov 3, 2026 4:05 PM ET", source="nasdaq", price=203.1)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 3, 16, 6))
        self.assertEqual(n, 1)

    def test_future_asof_clock_skew_blocked(self) -> None:
        # asOf > 今天：时钟错乱，宁可不写
        q = _quote("^SOX", tradeDate="Nov 4, 2026 4:00 PM ET", source="nasdaq", price=10400.0)
        n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                            now_et=self._et(2026, 11, 3, 17, 0))
        self.assertEqual(n, 0)

    def test_realtime_fallback_sources_gated(self) -> None:
        # 第五轮评审 I-1：fmp/finnhub/yfinance 同为实时报价端点（nasdaq 挂掉后
        # 降级链上的同构入口），当日未收盘一律拦——拦的是「今日戳+盘前价」形态
        for src in ("fmp", "finnhub", "yfinance"):
            with self.subTest(source=src):
                q = _quote(f"X-{src}", tradeDate="2026-11-03", source=src)
                n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                                    now_et=self._et(2026, 11, 3, 5, 26))
                self.assertEqual(n, 0)
                self.assertFalse(series_file(self.root, f"X-{src}").exists())

    def test_realtime_fallback_sources_past_date_written(self) -> None:
        # 三源隔天自愈同 nasdaq：asOf<今天 → 放行（收盘价已定，正确落行）
        for src in ("fmp", "finnhub", "yfinance"):
            with self.subTest(source=src):
                q = _quote(f"X-{src}", tradeDate="2026-11-02", source=src)
                n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                                    now_et=self._et(2026, 11, 3, 5, 26))
                self.assertEqual(n, 1)

    def test_close_boundary_1559_vs_1600(self) -> None:
        # 收盘边界逐分钉死（第五轮 M-B）：15:59 拒、16:00 收；EDT 夏令时同口径
        # （ZoneInfo 保证 7 月仍是挂钟 16:00）
        for (y, m, d) in ((2026, 11, 3), (2026, 7, 13)):
            with self.subTest(date=f"{y:04d}-{m:02d}-{d:02d}"):
                q = _quote("NVDA", tradeDate=f"{y:04d}-{m:02d}-{d:02d}", source="nasdaq", price=203.0)
                n_pre = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                                        now_et=self._et(y, m, d, 15, 59))
                self.assertEqual(n_pre, 0)
                n_post = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                                         now_et=self._et(y, m, d, 16, 0))
                self.assertEqual(n_post, 1)

    def test_exempt_sources_not_gated(self) -> None:
        # 豁免源不过此门：CN 由批量权威写者覆盖，eod/fred 收盘口径，sina/eastmoney
        # 现价口径自洽——asOf=今日+任意时钟都写
        for src in ("mootdx", "sina", "eod", "fred", "eastmoney"):
            with self.subTest(source=src):
                q = _quote(f"X-{src}", tradeDate="2026-11-03", source=src)
                n = pmd.append_series_from_snapshot(_snapshot([q]), self.root,
                                                    now_et=self._et(2026, 11, 3, 5, 26))
                self.assertEqual(n, 1)


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
        # 4c 宏观前移后调用带 macro_meta 透传（旧断言 `_persist_market_data_hook(market_data)`
        # 按无参调用锁定，已随调用序前移更新）
        self.assertIn("_persist_market_data_hook(\n        market_data,", source)
        self.assertIn("def _persist_market_data_hook(", source)


class RunLedgerHookTests(unittest.TestCase):
    """4a 运行账本接线：open+data-close 两行、逃生门、账本失败 sentinel 不抛。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _degraded_snapshot() -> dict:
        snap = _snapshot([_quote("600276.SH")])
        snap["meta"]["quotes"]["degradations"] = [
            {"ticker": "NVDA", "source_tried": "nasdaq", "reason": "timeout",
             "fallback": "finnhub"}]
        return snap

    def _ledger_rows(self) -> list[dict]:
        ledger = self.root / ".state" / "run-log.jsonl"
        return [json.loads(line) for line in
                ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_hook_writes_open_and_data_close(self) -> None:
        pmd.run_persist_hook(self._degraded_snapshot(), self.root)
        rows = self._ledger_rows()
        self.assertEqual([r["type"] for r in rows], ["open", "data-close"])
        open_row, close_row = rows
        self.assertEqual(open_row["kind"], "watch")
        self.assertEqual(open_row["trade_date"], "2026-11-02")  # fetched_at 的业务日
        self.assertEqual(close_row["run_id"], open_row["run_id"])
        self.assertEqual(close_row["sources_used"], ["mootdx"])  # 行内 source 汇总
        self.assertEqual(close_row["missing"], [  # meta 降级清单透传
            {"ticker": "NVDA", "source_tried": "nasdaq", "reason": "timeout",
             "fallback": "finnhub"}])
        (target,) = close_row["data_targets"]
        self.assertTrue(target["path"].endswith("market/series/600276.SH.jsonl"),
                        msg=target["path"])
        self.assertEqual(target["anchor_date"], "2026-11-02")
        self.assertRegex(target["sha256"], r"^[0-9a-f]{64}$")

    def test_macro_meta_missing_flows_into_data_close(self) -> None:
        pmd.run_persist_hook(
            _snapshot([_quote("600276.SH")]), self.root,
            macro_meta={"missing_symbols": ["VIX", "SPY"], "reason": "FMP_API_KEY not set"})
        close_row = self._ledger_rows()[1]
        self.assertIn({"item": "VIX", "reason": "FMP_API_KEY not set"}, close_row["missing"])
        self.assertIn({"item": "SPY", "reason": "FMP_API_KEY not set"}, close_row["missing"])

    def test_run_log_disable_env_skips_ledger(self) -> None:
        with patch.dict(os.environ, {"RUN_LOG_DISABLE": "1"}):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)
        self.assertFalse((self.root / ".state").exists())
        self.assertTrue(series_file(self.root, "600276.SH").exists())  # 持久化照常

    def test_run_log_false_param_skips_ledger(self) -> None:
        pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root, run_log=False)
        self.assertFalse((self.root / ".state").exists())

    def test_ledger_open_failure_writes_sentinel_not_raises(self) -> None:
        archive = pmd._load_run_archive()
        with patch.object(archive, "append_open", side_effect=RuntimeError("ledger boom")):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)  # 不抛即通过
        sentinel = self.root / ".state" / "run-log.error"
        self.assertTrue(sentinel.is_file())
        self.assertIn("open", sentinel.read_text(encoding="utf-8"))
        self.assertTrue(series_file(self.root, "600276.SH").exists())  # 持久化不受账本失败影响

    def test_ledger_close_failure_writes_sentinel_not_raises(self) -> None:
        archive = pmd._load_run_archive()
        with patch.object(archive, "append_data_close", side_effect=RuntimeError("close boom")):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)
        self.assertIn("data-close",
                      (self.root / ".state" / "run-log.error").read_text(encoding="utf-8"))
        self.assertEqual([r["type"] for r in self._ledger_rows()], ["open"])  # close 没写成

    def test_persist_failure_leaves_open_without_close(self) -> None:
        # 落盘失败不写 data-close：open 留给 verify 的孤儿判定（spec §3.2 I3）
        with patch.object(pmd, "save_daily_snapshot", side_effect=RuntimeError("disk full")):
            pmd.run_persist_hook(_snapshot([_quote("600276.SH")]), self.root)
        self.assertEqual([r["type"] for r in self._ledger_rows()], ["open"])


class CliSnapshotFileTests(unittest.TestCase):
    """--snapshot-file 两种入参都接受：fetch 原始输出（顶层 quotes）与 daily/ 落盘 wrapper（顶层 payload）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_wrapper(self, quotes: list[dict]) -> Path:
        wrapper = {"schema_version": 1, "fetched_at": "2026-11-03T12:00:00+00:00",
                   "payload": _snapshot(quotes)}
        path = self.root / "in.json"
        path.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
        return path

    def test_wrapper_file_auto_unwrapped_and_series_appended(self) -> None:
        # friction 修根：直传 data/market/daily/ 式 wrapper 文件——旧行为零行追加（quotes 埋在
        # payload 下不被识别），新行为自动解包，quotes 照常进 series（NVDA 用真实 Nasdaq 缩写月戳）
        wrapper_file = self._write_wrapper([
            _quote("600276.SH"),
            _quote("NVDA", tradeDate="Nov 2, 2026 12:03 PM ET", source="nasdaq")])
        with patch.object(pmd, "resolve_data_root", return_value=self.root):
            self.assertEqual(pmd.main(["--snapshot-file", str(wrapper_file)]), 0)
        self.assertEqual([r["date"] for r in read_series_rows(series_file(self.root, "600276.SH"))],
                         ["2026-11-02"])
        self.assertEqual(read_series_rows(series_file(self.root, "NVDA"))[-1]["date"], "2026-11-02")

    def test_wrapper_rewrite_not_double_wrapped(self) -> None:
        # 锁死损坏路径：传 wrapper 后重写的当日快照，payload 直下有 quotes、无二层 payload
        wrapper_file = self._write_wrapper([_quote("600276.SH")])
        with patch.object(pmd, "resolve_data_root", return_value=self.root):
            pmd.main(["--snapshot-file", str(wrapper_file)])
        daily_files = list((self.root / "market" / "daily").glob("*.json"))
        self.assertEqual(len(daily_files), 1)
        daily = json.loads(daily_files[0].read_text(encoding="utf-8"))
        self.assertIn("quotes", daily["payload"])
        self.assertNotIn("payload", daily["payload"])  # 双层包裹 = 静默数据损坏

    def test_raw_fetch_output_still_works(self) -> None:
        # fetch 原始输出（顶层 quotes 直下、无 payload 键）行为不变
        raw = self.root / "raw.json"
        raw.write_text(json.dumps(_snapshot([_quote("600276.SH")]), ensure_ascii=False),
                       encoding="utf-8")
        with patch.object(pmd, "resolve_data_root", return_value=self.root):
            self.assertEqual(pmd.main(["--snapshot-file", str(raw)]), 0)
        self.assertTrue(series_file(self.root, "600276.SH").exists())

    def test_garbage_json_without_quotes_rejected_exit_2(self) -> None:
        # Minor⑤：传错文件（无 quotes 的 JSON）旧行为静默落盘快照+0 行追加+退出 0
        for junk in ('{"foo": 1}', "[1, 2, 3]", '{"payload": {"no_quotes": true}}'):
            bad = self.root / "bad.json"
            bad.write_text(junk, encoding="utf-8")
            with self.assertRaises(SystemExit, msg=junk) as ctx:
                pmd.main(["--snapshot-file", str(bad)])
            self.assertEqual(ctx.exception.code, 2, msg=junk)
        self.assertFalse((self.root / "market").exists())  # 拒绝点在落盘之前


if __name__ == "__main__":
    unittest.main()
