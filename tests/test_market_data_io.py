"""market_data_io 单测（全封闭 tmp 目录）。三档 upsert 是 spec §5.2 的根规则。"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from _test_paths import REPO_ROOT  # noqa: F401

import market_data_io as mio  # noqa: E402


class NamingTests(unittest.TestCase):
    def test_normalize_market_suffix(self) -> None:
        self.assertEqual(mio.normalize_cn_symbol("600276", 1), "600276.SH")
        self.assertEqual(mio.normalize_cn_symbol("300476", 0), "300476.SZ")

    def test_whitelist_positive(self) -> None:
        for code, market in (("600519", 1), ("688981", 1), ("513880", 1),
                             ("512000", 1), ("560010", 1), ("002545", 0),
                             ("301358", 0), ("159915", 0), ("162411", 0)):
            self.assertTrue(mio.is_cn_series_symbol(code, market), (code, market))

    def test_whitelist_negative(self) -> None:
        # SH: 88/89 板块段、20x 回购、50x LOF（有意不对称，spec §5.2）
        for code in ("880301", "890001", "204001", "500001"):
            self.assertFalse(mio.is_cn_series_symbol(code, 1), code)
        # SZ: 债券/回购、B股、指数
        for code in ("120400", "131810", "200004", "399106", "100001"):
            self.assertFalse(mio.is_cn_series_symbol(code, 0), code)
        # 北交所 43/83/87/92 在两个市场表里都不该过
        for code in ("430047", "830799", "872925", "920002"):
            self.assertFalse(mio.is_cn_series_symbol(code, 0), code)
            self.assertFalse(mio.is_cn_series_symbol(code, 1), code)
        self.assertFalse(mio.is_cn_series_symbol("6002", 1))  # 非 6 位


class TradeDateTests(unittest.TestCase):
    def test_digits_and_iso(self) -> None:
        self.assertEqual(mio.parse_trade_date("20261102"), "2026-11-02")
        self.assertEqual(mio.parse_trade_date("2026-11-02"), "2026-11-02")

    def test_epoch_seconds_and_millis(self) -> None:
        # 1761950400 = 2025-10-31 22:40 UTC = 18:40 EDT（美东收盘后），两时区同日
        self.assertEqual(mio.parse_trade_date(1761950400), "2025-10-31")
        self.assertEqual(mio.parse_trade_date(1761950400000), "2025-10-31")

    def test_english_long_stamp(self) -> None:
        self.assertEqual(mio.parse_trade_date("November 2, 2026 4:00PM ET"), "2026-11-02")
        self.assertEqual(mio.parse_trade_date("November 2, 2026"), "2026-11-02")

    def test_nasdaq_abbreviated_month_real_payload(self) -> None:
        # C1：真实 payload 逐字拷贝（data/market/daily/2026-11-03.json：NVDA 12:03、^IXIC/^SOX 12:01）。
        # 修正前三格式全 %B 全拼月 → "Nov 2, ..." 全失配，NVDA/指数 series 零积累（只进快照）
        self.assertEqual(mio.parse_trade_date("Nov 2, 2026 12:03 PM ET"), "2026-11-02")
        self.assertEqual(mio.parse_trade_date("Nov 2, 2026 12:01 PM ET"), "2026-11-02")

    def test_calendar_invalid_dates_return_none(self) -> None:
        # I3：形状合法但日历上不存在的日期不得成为 date 主键
        for bad in ("0000-00-00", "2026-11-31", "20261131"):
            self.assertIsNone(mio.parse_trade_date(bad), bad)

    def test_garbage_and_empty_return_none(self) -> None:
        for bad in ("", None, "垃圾", "Nov-x"):
            self.assertIsNone(mio.parse_trade_date(bad), bad)


class UpsertTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "600276.SH.jsonl"
        self.path.write_text(
            '{"date": "2026-10-30", "open": 71.0, "high": 73.0, "low": 70.0, "close": 71.0, "volume": 100, "amount": null, "source": "mootdx"}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_new_date_inserted_in_order(self) -> None:
        n = mio.upsert_series_rows(self.path, [self._row("2026-10-28", close=69.0)], "batch")
        self.assertEqual(n, 1)
        dates = [r["date"] for r in mio.read_series_rows(self.path)]
        self.assertEqual(dates, ["2026-10-28", "2026-10-30"])  # 升序插入非纯 append

    def test_batch_authoritative_overwrites(self) -> None:
        n = mio.upsert_series_rows(self.path, [self._row("2026-10-30", close=99.9)], "batch")
        self.assertEqual(n, 1)
        self.assertEqual(mio.read_series_rows(self.path)[-1]["close"], 99.9)

    def test_snapshot_fills_null_never_overwrites(self) -> None:
        # 预置行 amount=null（批量未跑过）；钩子行 close=99.9、amount=7100：
        # snapshot 档只补 null 空位 → amount 补上、close 保留 71.0，n==1
        row = self._row("2026-10-30", close=99.9, amount=7100.0)
        n = mio.upsert_series_rows(self.path, [row], "snapshot")
        self.assertEqual(n, 1)
        got = mio.read_series_rows(self.path)[-1]
        self.assertEqual(got["close"], 71.0)     # 非空没被覆盖
        self.assertEqual(got["amount"], 7100.0)  # null 被补上

    def test_no_change_returns_zero(self) -> None:
        row = self._row("2026-10-30", close=71.0, amount=None)  # 与预置行一致（amount 均 null）
        n = mio.upsert_series_rows(self.path, [row], "batch")
        self.assertEqual(n, 0)

    def test_torn_tail_tolerated_middle_raises(self) -> None:
        ok = self.root / "a.jsonl"
        ok.write_text('{"date": "2026-11-01", "close": 1.0}\n{"date": "2026-11', encoding="utf-8")
        self.assertEqual(len(mio.read_series_rows(ok)), 1)
        bad = self.root / "b.jsonl"
        bad.write_text('{"date": "2026-11-01", "close": 1.0}\n坏行\n{"date": "2026-11-02", "close": 2.0}\n', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            mio.read_series_rows(bad)

    def _row(self, d: str, close: float, amount: float | None = 7100.0) -> dict:
        return {"date": d, "open": None, "high": None, "low": None, "close": close,
                "volume": None, "amount": amount, "source": "mootdx"}


class AtomicAndLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_leaves_no_tmp(self) -> None:
        p = self.root / "sub" / "x.jsonl"
        mio.atomic_write_text(p, "hello\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(list((self.root / "sub").glob("*.tmp")), [])

    def test_lock_exclusive_and_stale_takeover(self) -> None:
        with mio.series_lock(self.root, "t") as ok:
            self.assertTrue(ok)
            with mio.series_lock(self.root, "t", timeout_s=0.2) as ok2:
                self.assertFalse(ok2)  # 同名锁非阻塞拿不到
        lock = self.root / ".locks" / "t.lock"
        lock.write_text("dead", encoding="utf-8")
        os.utime(lock, (time.time() - 700, time.time() - 700))  # 伪装 10 分钟前的陈旧锁
        with mio.series_lock(self.root, "t") as ok3:
            self.assertTrue(ok3)  # 陈旧锁被接管


if __name__ == "__main__":
    unittest.main()
