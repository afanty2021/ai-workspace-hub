"""mootdx_source 单元测试（全封闭，不联网）。

字段口径见 mootdx_source.py 模块注释（2026-11-02 实测）：quotes() 给实时快照
（vol 单位=手，昨收=官方 last_close），bars(frequency=9) 的 datetime 索引给
交易日。批量路径的线程安全靠 RLock 串行化——这里只测可封闭的纯逻辑与装配，
真实取数在接入日报时验证过（21/21 CN 票 mootdx 命中）。
"""

from __future__ import annotations

import threading
import unittest
from datetime import date
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

import mootdx_source  # noqa: E402
from mootdx_source import (  # noqa: E402
    _quote_from_snapshot,
    fetch_mootdx_quotes,
    is_mootdx_ticker,
)


class GateTests(unittest.TestCase):
    def test_cn_stock_and_etf_suffixes_pass(self) -> None:
        for ticker in (
            "600276.SH",
            "601857.SH",
            "002545.SZ",
            "301358.SZ",
            "513880.SH",  # SH ETF (51x)
            "512000.SH",  # SH ETF (56x)
            "159915.SZ",  # SZ ETF (15x)
        ):
            self.assertTrue(is_mootdx_ticker(ticker), ticker)

    def test_non_cn_or_malformed_tickers_reject(self) -> None:
        for ticker in (
            "00700.HK",
            "000660.KS",  # 与铜陵有色 000660.SZ 同码不同市
            "601857.SS",  # Yahoo 后缀，mootdx 不认
            "600276",  # 缺后缀
            "NVDA",
            "^IXIC",
            "XAUUSD=X",
            "HG=F",
            "",  # 空
            "6002766.SH",  # 7 位数字
        ):
            self.assertFalse(is_mootdx_ticker(ticker), ticker)


class SnapshotMappingTests(unittest.TestCase):
    def test_maps_fields_with_official_prev_close(self) -> None:
        quote = _quote_from_snapshot(
            "600276.SH",
            {"price": 48.77, "last_close": 48.46, "open": 49.18, "high": 49.2,
             "low": 48.31, "vol": 456389},
            "2026-11-02",
        )
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["symbol"], "600276.SH")
        self.assertEqual(quote["price"], 48.77)
        self.assertEqual(quote["previousClose"], 48.46)
        self.assertAlmostEqual(quote["change"], 0.31)
        self.assertAlmostEqual(quote["changesPercentage"], 0.31 / 48.46 * 100, places=4)
        self.assertEqual(quote["open"], 49.18)
        self.assertEqual(quote["dayHigh"], 49.2)
        self.assertEqual(quote["dayLow"], 48.31)
        self.assertEqual(quote["volume"], 456389)  # 手，与 tushare/腾讯同口径
        self.assertEqual(quote["tradeDate"], "2026-11-02")
        self.assertEqual(quote["source"], "mootdx")

    def test_float_noise_is_rounded(self) -> None:
        quote = _quote_from_snapshot(
            "600276.SH",
            {"price": 48.77, "last_close": 48.460000000000001, "open": 49.18,
             "high": 49.2, "low": 48.310000000000002, "vol": 456389.0},
            "2026-11-02",
        )
        assert quote is not None
        self.assertEqual(quote["previousClose"], 48.46)
        self.assertEqual(quote["dayLow"], 48.31)

    def test_zero_or_missing_price_rejects(self) -> None:
        self.assertIsNone(
            _quote_from_snapshot("600276.SH", {"price": 0, "last_close": 48.46}, "")
        )
        self.assertIsNone(
            _quote_from_snapshot("600276.SH", {"price": None, "last_close": 48.46}, "")
        )

    def test_missing_prev_close_keeps_price_without_change(self) -> None:
        quote = _quote_from_snapshot(
            "600276.SH", {"price": 48.77, "last_close": None}, ""
        )
        assert quote is not None
        self.assertIsNone(quote["change"])
        self.assertIsNone(quote["changesPercentage"])


class _StubSnapshotFrame:
    """最小 DataFrame 桩：mootdx quotes() 返回形状（code 列 + 行字典）。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        for row in self._rows:
            yield None, row


class _StubBarsFrame:
    """最小 DataFrame 桩：mootdx bars() 返回形状（datetime 索引）。"""

    def __init__(self, stamps: list) -> None:
        self.index = stamps
        self.empty = not stamps


class BatchFetchTests(unittest.TestCase):
    def test_batch_maps_snapshots_and_per_ticker_trade_dates(self) -> None:
        snapshots = _StubSnapshotFrame(
            [
                {"code": "600276", "price": 48.77, "last_close": 48.46, "vol": 456389},
                {"code": "513880", "price": 2.056, "last_close": 2.057, "vol": 634430},
            ]
        )
        bars_frames = {
            "600276": _StubBarsFrame([date(2026, 10, 30), date(2026, 11, 2)]),
            "513880": _StubBarsFrame([date(2026, 10, 30), date(2026, 11, 2)]),
        }

        class StubClient:
            def quotes(self, symbol):
                return snapshots

        with (
            patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()),
            patch.object(
                mootdx_source, "_mootdx_call",
                side_effect=lambda method, **kw: bars_frames[kw["symbol"]],
            ),
        ):
            quotes = fetch_mootdx_quotes(["600276.SH", "513880.SH"])

        self.assertEqual([q["symbol"] for q in quotes], ["600276.SH", "513880.SH"])
        self.assertEqual(quotes[0]["tradeDate"], "2026-11-02")
        self.assertEqual(quotes[0]["source"], "mootdx")

    def test_requests_beyond_80_are_chunked(self) -> None:
        # 通达信服务器对单次快照请求只回前 80 行、尾部静默丢弃（pytdx 不截断），
        # 客户端必须分块：100 只应拆成 80 + 20 两次调用并全部拿到。
        calls: list[list[str]] = []

        class ChunkedStub:
            def quotes(self, symbol):
                calls.append(list(symbol))
                return _StubSnapshotFrame(
                    [{"code": c, "price": 1.0, "last_close": 1.0, "vol": 1} for c in symbol]
                )

        tickers = [f"{600000 + i}.SH" for i in range(100)]
        with (
            patch.object(mootdx_source, "_get_mootdx_client", return_value=ChunkedStub()),
            patch.object(mootdx_source, "_bars_trade_date", return_value="2026-11-02"),
        ):
            quotes = fetch_mootdx_quotes(tickers)

        self.assertEqual([len(b) for b in calls], [80, 20])
        self.assertEqual(len(quotes), 100)

    def test_snapshot_missing_one_code_skips_only_that_ticker(self) -> None:
        snapshots = _StubSnapshotFrame(
            [{"code": "600276", "price": 48.77, "last_close": 48.46, "vol": 1}]
        )

        class StubClient:
            def quotes(self, symbol):
                return snapshots

        with (
            patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()),
            # 不触发真实锁重入（该契约由 LockContractTests 的限时用例专职覆盖），
            # 否则锁类型回归时本用例先死锁挂起、整套测试跑不完。
            patch.object(mootdx_source, "_bars_trade_date", return_value=""),
        ):
            quotes = fetch_mootdx_quotes(["600276.SH", "002545.SZ"])

        # 002545 不在快照里：只降级该票，不影响 600276。
        self.assertEqual([q["symbol"] for q in quotes], ["600276.SH"])

    def test_empty_snapshot_returns_empty_list(self) -> None:
        class StubClient:
            def quotes(self, symbol):
                return _StubSnapshotFrame([])

        with patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()):
            self.assertEqual(fetch_mootdx_quotes(["600276.SH"]), [])


class LockContractTests(unittest.TestCase):
    """锁契约：可重入性是批量路径的硬前提，两种回归形态都要能确定性捕获。

    若 RLock 被改回普通 Lock：① 类型断言当场红；② 真实重入路径（批量持锁 →
    逐票 _bars_trade_date → _mootdx_call 二次拿锁）表现为**死锁挂起**而非报错。
    因此其余批量用例一律不触发真实重入（patch 掉 _bars_trade_date 或
    _mootdx_call），重入覆盖集中在下面的限时守护线程用例——把挂起转成 5 秒内
    的确定性失败，全量跑法不依赖 pytest timeout 插件或 -x。
    """

    def test_lock_is_reentrant(self) -> None:
        self.assertIsInstance(mootdx_source._MOOTDX_LOCK, type(threading.RLock()))

    def test_batch_reentry_completes_without_deadlock(self) -> None:
        # 不 patch _bars_trade_date / _mootdx_call：重入必须穿过真实的两次锁获取。
        snapshots = _StubSnapshotFrame(
            [{"code": "600276", "price": 48.77, "last_close": 48.46, "vol": 1}]
        )
        bars_frame = _StubBarsFrame([date(2026, 11, 2)])

        class StubClient:
            def quotes(self, symbol):
                return snapshots

            def bars(self, symbol, frequency, offset):
                return bars_frame

        result: dict[str, list] = {}

        def run() -> None:
            result["quotes"] = fetch_mootdx_quotes(["600276.SH"])

        with patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()):
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            worker.join(timeout=5)

        if worker.is_alive():
            self.fail(
                "批量持锁后的重入路径 5s 未返回：死锁。"
                "_MOOTDX_LOCK 是否被改回了普通 Lock？"
            )
        self.assertEqual(len(result["quotes"]), 1)
        self.assertEqual(result["quotes"][0]["tradeDate"], "2026-11-02")


class UnavailableContractTests(unittest.TestCase):
    def test_client_failure_propagates_for_caller_to_degrade(self) -> None:
        # 契约：mootdx 不可用时 fetch_mootdx_quotes 抛异常，由
        # fetch_market_data 的批量 wrap / 降级链 try 负责降级，模块内部不吞。
        with patch.object(
            mootdx_source, "_get_mootdx_client",
            side_effect=RuntimeError("mootdx 通达信服务器不可用"),
        ):
            with self.assertRaises(RuntimeError):
                fetch_mootdx_quotes(["600276.SH"])


class _StubIndexFrame:
    """最小 DataFrame 桩：index_bars 返回形状（行字典 + iloc + 长度）。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.empty = not rows

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, pos: int) -> dict:
        return self._rows[pos]

    @property
    def iloc(self):
        return self


class TdxIndexTests(unittest.TestCase):
    """880/881 板块指数（.TDX 后缀，2026-11-05 接入）：资格闸门 + 日线装配 + 批量混跑。"""

    def test_tdx_suffix_gate(self) -> None:
        for ticker in ("881075.TDX", "881386.TDX", "880301.TDX"):
            self.assertTrue(is_mootdx_ticker(ticker), ticker)
        for ticker in (
            "881075",  # 缺 .TDX 后缀
            "881075.SH",  # 板块指数不是交易所证券，约定必须 .TDX 显式标识
            "888880.TDX",  # 总市值占位段（888 开头），明确不接
            "88107.TDX",  # 5 位数字
            "8810755.TDX",  # 7 位数字
        ):
            self.assertFalse(is_mootdx_ticker(ticker), ticker)

    def test_index_quote_from_two_bars(self) -> None:
        bars = _StubIndexFrame([
            {"datetime": "2026-11-04 15:00", "close": 2071.28, "open": 2050.0,
             "high": 2080.0, "low": 2040.0, "volume": 100000},
            {"datetime": "2026-11-05 15:00", "close": 2177.29, "open": 2168.46,
             "high": 2212.53, "low": 2134.16, "volume": 115820},
        ])
        quote = mootdx_source._index_quote_from_bars("881075.TDX", bars)
        self.assertEqual(quote["symbol"], "881075.TDX")
        self.assertEqual(quote["price"], 2177.29)
        self.assertEqual(quote["previousClose"], 2071.28)
        self.assertAlmostEqual(quote["changesPercentage"], 5.118091)
        self.assertEqual(quote["tradeDate"], "2026-11-05")
        self.assertEqual(quote["volume"], 115820)
        self.assertEqual(quote["source"], "mootdx")

    def test_index_quote_single_bar_keeps_price_without_change(self) -> None:
        bars = _StubIndexFrame([
            {"datetime": "2026-11-05 15:00", "close": 2006.81, "volume": 1},
        ])
        quote = mootdx_source._index_quote_from_bars("881386.TDX", bars)
        self.assertEqual(quote["price"], 2006.81)
        self.assertIsNone(quote["change"])
        self.assertIsNone(quote["changesPercentage"])

    def test_index_quote_empty_or_bad_price_returns_none(self) -> None:
        self.assertIsNone(mootdx_source._index_quote_from_bars("881075.TDX", _StubIndexFrame([])))
        self.assertIsNone(mootdx_source._index_quote_from_bars(
            "881075.TDX", _StubIndexFrame([{"datetime": "2026-11-05 15:00", "close": 0.0}])))
        # datetime 与 year/month/day 全缺：拿不到交易日，宁缺毋滥
        self.assertIsNone(mootdx_source._index_quote_from_bars(
            "881075.TDX", _StubIndexFrame([{"close": 2177.29}])))

    def test_mixed_batch_stocks_via_quotes_and_index_via_index_bars(self) -> None:
        snapshots = _StubSnapshotFrame(
            [{"code": "300750", "price": 264.06, "last_close": 252.88, "vol": 693511}]
        )
        index_calls: list[dict] = []

        class StubClient:
            def quotes(self, symbol):
                return snapshots

        def fake_call(method, **kw):
            index_calls.append({"method": method, **kw})
            return _StubIndexFrame([
                {"datetime": "2026-11-04 15:00", "close": 2071.28, "volume": 1},
                {"datetime": "2026-11-05 15:00", "close": 2177.29, "open": 2168.46,
                 "high": 2212.53, "low": 2134.16, "volume": 115820},
            ])

        with (
            patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()),
            patch.object(mootdx_source, "_bars_trade_date", return_value="2026-11-05"),
            patch.object(mootdx_source, "_mootdx_call", side_effect=fake_call),
        ):
            quotes = fetch_mootdx_quotes(["300750.SZ", "881075.TDX"])

        # 个股走快照、指数走 index_bars（不进快照请求）
        self.assertEqual(index_calls, [
            {"method": "index_bars", "symbol": "881075", "frequency": 9, "offset": 2}
        ])
        self.assertEqual([q["symbol"] for q in quotes], ["300750.SZ", "881075.TDX"])
        self.assertEqual(quotes[1]["tradeDate"], "2026-11-05")

    def test_index_failure_degrades_only_that_ticker(self) -> None:
        class StubClient:
            def quotes(self, symbol):
                return _StubSnapshotFrame(
                    [{"code": "300750", "price": 264.06, "last_close": 252.88, "vol": 1}]
                )

        with (
            patch.object(mootdx_source, "_get_mootdx_client", return_value=StubClient()),
            patch.object(mootdx_source, "_bars_trade_date", return_value="2026-11-05"),
            patch.object(
                mootdx_source, "_mootdx_call",
                side_effect=RuntimeError("index_bars 挂了"),
            ),
        ):
            quotes = fetch_mootdx_quotes(["300750.SZ", "881075.TDX"])

        self.assertEqual([q["symbol"] for q in quotes], ["300750.SZ"])


if __name__ == "__main__":
    unittest.main()
