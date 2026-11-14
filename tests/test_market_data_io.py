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


class HistoryGuardTests(unittest.TestCase):
    """Q-20261110-08 A 案：batch 写者历史行防改写（R20261110-05 静默改史修根）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "XLK.jsonl"
        # 40 行升序 series（2009-01-01 起每日一行），值=d 序数；amount 全 null
        # ——历史行补洞场景的注入位（填洞与改写在防护语义上是两类）。
        lines = [json.dumps({"date": f"2009-01-{d:02d}", "open": float(d),
                             "high": float(d), "low": float(d), "close": float(d),
                             "volume": 1000.0 * d, "amount": None,
                             "source": "yfinance"}, ensure_ascii=False)
                 for d in range(1, 41)]
        self.path.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _row(d: str, close: float, amount: float | None = None) -> dict:
        return {"date": d, "open": None, "high": None, "low": None, "close": close,
                "volume": None, "amount": amount, "source": "yfinance"}

    def _close(self, d: str) -> float:
        for r in mio.read_series_rows(self.path):
            if r["date"] == d:
                return float(r["close"])
        raise AssertionError(f"{d} 不存在")

    def test_history_overwrite_rejected_by_default(self) -> None:
        # 2009-01-05 距尾部 36 个交易日 > repair_window=3 → close 覆盖被拒
        mio.upsert_series_rows(self.path, [self._row("2009-01-05", 999.0)],
                               "batch", repair_window=3)
        self.assertEqual(self._close("2009-01-05"), 5.0)  # 旧值保留

    def test_tail_window_overwrite_allowed(self) -> None:
        # 尾部 3 个交易日（01-38/39/40）内覆盖允许——近期修订/源错误修复
        n = mio.upsert_series_rows(self.path, [self._row("2009-01-38", 999.0)],
                                   "batch", repair_window=3)
        self.assertEqual(n, 1)
        self.assertEqual(self._close("2009-01-38"), 999.0)

    def test_default_window_boundary(self) -> None:
        # 默认 repair_window=30：existing[-30:] 含倒数第 30 行（01-11），
        # 倒数第 31 行（01-10）窗外被拒——边界逐行验证
        mio.upsert_series_rows(self.path, [self._row("2009-01-11", 111.0),
                                           self._row("2009-01-10", 110.0)], "batch")
        self.assertEqual(self._close("2009-01-11"), 111.0)  # 窗内允许
        self.assertEqual(self._close("2009-01-10"), 10.0)   # 窗外拒绝

    def test_null_fill_always_allowed(self) -> None:
        # 历史行补 null 空位=填洞不是改写事实——窗外也允许（close 覆盖仍被拒）
        row = self._row("2009-01-05", 999.0, amount=55.0)
        mio.upsert_series_rows(self.path, [row], "batch", repair_window=3)
        got = {r["date"]: r for r in mio.read_series_rows(self.path)}["2009-01-05"]
        self.assertEqual(got["amount"], 55.0)   # null 补上
        self.assertEqual(got["close"], 5.0)     # 旧值保留

    def test_repair_unlocks_full_overwrite(self) -> None:
        # 显式 repair=True（--repair/--force 载体）解锁全量覆盖
        mio.upsert_series_rows(self.path, [self._row("2009-01-05", 999.0)],
                               "batch", repair_window=3, repair=True)
        self.assertEqual(self._close("2009-01-05"), 999.0)

    def test_new_date_append_unaffected(self) -> None:
        # 新日期追加（①类）与窗无关——深回补补早期缺口不受防护影响
        n = mio.upsert_series_rows(self.path, [self._row("2008-12-31", 1.0)],
                                   "batch", repair_window=3)
        self.assertEqual(n, 1)
        self.assertEqual(mio.read_series_rows(self.path)[0]["date"], "2008-12-31")

    def test_snapshot_writer_unaffected(self) -> None:
        # snapshot 档本就只补 null——历史行 close 改动既不被允许也无告警语义变化
        row = self._row("2009-01-05", 999.0, amount=55.0)
        n = mio.upsert_series_rows(self.path, [row], "snapshot", repair_window=3)
        self.assertEqual(n, 1)  # amount 补洞计 1 行
        got = {r["date"]: r for r in mio.read_series_rows(self.path)}["2009-01-05"]
        self.assertEqual(got["close"], 5.0)

    def test_source_field_also_guarded(self) -> None:
        # source 字段差异（yfinance→eastmoney）同样属历史改写，窗外拒绝
        row = {"date": "2009-01-05", "close": None, "source": "eastmoney"}
        mio.upsert_series_rows(self.path, [row], "batch", repair_window=3)
        got = {r["date"]: r for r in mio.read_series_rows(self.path)}["2009-01-05"]
        self.assertEqual(got["source"], "yfinance")


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

    def test_lock_released_when_body_raises(self) -> None:
        # finally 释放路径：with 块内炸了锁也必须删——否则一个异常票会把同票的
        # 后续写入全卡到 600s 陈旧接管才恢复
        with self.assertRaises(RuntimeError):
            with mio.series_lock(self.root, "t") as ok:
                self.assertTrue(ok)
                raise RuntimeError("boom")
        self.assertFalse((self.root / ".locks" / "t.lock").exists())
        with mio.series_lock(self.root, "t") as ok2:
            self.assertTrue(ok2)  # 释放后立刻可重取


if __name__ == "__main__":
    unittest.main()
