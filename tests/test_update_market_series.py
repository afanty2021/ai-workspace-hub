"""update_market_series 单测（mock _mootdx_call，不联网）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from _test_paths import REPO_ROOT  # noqa: F401

import update_market_series as ums  # noqa: E402
from market_data_io import (  # noqa: E402
    index_series_file,
    read_series_rows,
    sector_series_file,
    series_file,
    upsert_series_rows,
)


def _bars_frame(dates: list[str], closes: list[float], **extra: dict) -> pd.DataFrame:
    data = {"open": [c - 1 for c in closes], "high": [c + 1 for c in closes],
            "low": [c - 2 for c in closes], "close": closes,
            "volume": [100.0] * len(dates), "amount": [8.0e7] * len(dates)}
    data.update(extra)
    return pd.DataFrame(data, index=pd.to_datetime(dates))


def _stocks_frame(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["code", "name"])


class BarsToRowsTests(unittest.TestCase):
    def test_nan_amount_becomes_null(self) -> None:
        # Minor：NaN 交给 json.dumps 会落成字面量 NaN（非标 JSON，DuckDB 不认）→ 清洗为 null
        df = _bars_frame(["2026-11-02"], [71.54], amount=[float("nan")])
        rows = ums.bars_to_rows(df, source="mootdx")
        self.assertIsNone(rows[0]["amount"])
        self.assertEqual(rows[0]["close"], 71.54)


class FakeMootdx:
    """按 method 分发的 _mootdx_call 替身。用法：FakeMootdx(stocks=..., bars=..., index_bars=...)。"""

    def __init__(self, *, stocks=None, bars=None, index_bars=None) -> None:
        self.calls: list[str] = []
        self._stocks = stocks
        self._bars = bars
        self._index_bars = index_bars

    def __call__(self, method: str, **kwargs):
        self.calls.append(
            f"{method}:{kwargs.get('symbol', kwargs.get('market', ''))}:off{kwargs.get('offset')}")
        table = {"stocks": self._stocks, "bars": self._bars, "index_bars": self._index_bars}[method]
        if table is None:
            raise RuntimeError(f"unexpected call {method}")
        if method == "bars" and callable(table):
            return table(kwargs.get("symbol"))
        return table


class GateTests(unittest.TestCase):
    def test_canary_reads_last_index_bar(self) -> None:
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-02"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            self.assertEqual(ums.fetch_server_latest_trade_date(), "2026-11-02")

    def test_gate_short_circuits_whole_round(self) -> None:
        # N1：闸门只认 data/.state/ 完成标记（批量写者独占的旁路状态），
        # 数据文件有当日行也不触发（那可能是钩子写的）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ums.write_round_marker(root, "stocks", "2026-11-02")
            market = series_file(root, "600276.SH")
            market.parent.mkdir(parents=True, exist_ok=True)
            market.write_text('{"date": "2026-11-02", "close": 71.5, "source": "mootdx"}\n',
                              encoding="utf-8")
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]))
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_stocks_update(root, latest="2026-11-02")
            self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 0})  # 整轮零调用
            self.assertFalse(any(c.startswith("stocks:") for c in fake.calls))

    def test_gate_ignores_hook_written_market_files(self) -> None:
        # I7：只有日报钩子写过的 market 文件（16:30 批量未跑、无标记）不得让闸门短路
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market = series_file(root, "600276.SH")
            market.parent.mkdir(parents=True, exist_ok=True)
            market.write_text('{"date": "2026-11-02", "close": 71.5, "source": "mootdx"}\n',
                              encoding="utf-8")
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                              bars=_bars_frame(["2026-11-02"], [71.54]))
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_stocks_update(root, latest="2026-11-03")  # 服务器已有 11-03，本地钩子只写到 11-02
            self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})  # 批量照常执行

    def test_marker_written_only_for_clean_full_round(self) -> None:
        # N1 补充点①：tickers 抽查轮与 fail>0 轮都不得写标记——前者会挡住 11.7
        # 全量初始化，后者会让 cron 同日补跑被闸门吃掉。三轮日期递进，保证
        # 失败轮不被「tail==latest 逐票 skip」挡住而真打到 bars。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeMootdx(stocks=_stocks_frame([("600276", "a")]),
                              bars=_bars_frame(["2026-11-03"], [71.54]))
            with patch.object(ums, "_mootdx_call", fake):
                ums.run_stocks_update(root, tickers=["600276.SH"], latest="2026-11-03")
            self.assertIsNone(ums.last_round_date(root, "stocks"))  # tickers 轮：无标记

            def boom(symbol: str):
                raise RuntimeError("socket dead")

            with patch.object(ums, "_mootdx_call",
                              FakeMootdx(stocks=_stocks_frame([("600276", "a")]), bars=boom)):
                stats = ums.run_stocks_update(root, latest="2026-11-04")  # 服务器前进一日 → 票不被逐票 skip 挡住
            self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 1})
            self.assertIsNone(ums.last_round_date(root, "stocks"))  # fail>0 轮：无标记

            with patch.object(ums, "_mootdx_call", fake):
                ums.run_stocks_update(root, latest="2026-11-04")
            self.assertEqual(ums.last_round_date(root, "stocks"), "2026-11-04")  # 干净全量轮：写标记


class StocksUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_enumerate_filter_normalize_upsert(self) -> None:
        stocks = _stocks_frame([("600276", "恒瑞医药"), ("300476", "胜宏科技"),
                                ("880301", "板块占位"), ("204001", "回购"), ("430047", "北交所")])
        fake = FakeMootdx(stocks=stocks, bars=_bars_frame(["2026-11-01", "2026-11-02"], [70.0, 71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 2, "skip": 0, "fail": 0})
        rows = read_series_rows(series_file(self.root, "600276.SH"))
        self.assertEqual([r["date"] for r in rows], ["2026-11-01", "2026-11-02"])
        self.assertEqual(rows[-1]["source"], "mootdx")
        self.assertEqual(rows[-1]["amount"], 8.0e7)
        self.assertTrue(series_file(self.root, "300476.SZ").exists())
        self.assertFalse(series_file(self.root, "880301.SH").exists())  # 白名单外不建文件

    def test_tail_equals_latest_skips_ticket(self) -> None:
        # 与闸门的分工：闸门管「整轮」（.state 标记）；逐票 skip 管 tickers 子集等闸门旁路路径。
        # 预置行带 amount（批量写的行，写者指纹）——只有批量自己的行才允许 skip
        market = series_file(self.root, "600276.SH")
        market.parent.mkdir(parents=True, exist_ok=True)
        market.write_text(
            '{"date": "2026-11-02", "close": 71.5, "amount": 8.0e7, "source": "mootdx"}\n',
            encoding="utf-8")
        fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                          bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, tickers=["600276.SH"], latest="2026-11-02")
        self.assertEqual(stats["skip"], 1)
        self.assertFalse(any(c.startswith("bars:") for c in fake.calls))  # 没打服务器

    def test_force_bypasses_per_ticket_skip(self) -> None:
        # --force 修根（friction：尾行已最新的票挡住 backfill=800 历史回补，
        # 同病灶第 2 次——第 1 次是钩子行 skip，由 amount 指纹修；这次本来就最新）
        market = series_file(self.root, "600276.SH")
        market.parent.mkdir(parents=True, exist_ok=True)
        market.write_text(
            '{"date": "2026-11-02", "close": 71.5, "amount": 8.0e7, "source": "mootdx"}\n',
            encoding="utf-8")
        fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                          bars=_bars_frame(["2023-07-13", "2026-11-02"], [60.0, 71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, backfill=800, tickers=["600276.SH"],
                                          latest="2026-11-02", force=True)
        self.assertEqual(stats["ok"], 1)
        self.assertIn("bars:600276:off800", fake.calls)
        self.assertEqual(len(read_series_rows(market)), 2)  # 800 根历史回补后按日期归并

    def test_single_failure_counted_others_continue(self) -> None:
        def bars_by_symbol(symbol: str):
            if symbol == "600276":
                raise RuntimeError("socket dead")
            return _bars_frame(["2026-11-02"], [71.54])

        fake = FakeMootdx(stocks=_stocks_frame([("600276", "a"), ("300476", "b")]), bars=bars_by_symbol)
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 1})
        self.assertTrue(series_file(self.root, "300476.SZ").exists())

    def test_tickers_subset_overrides_enumeration(self) -> None:
        fake = FakeMootdx(bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, backfill=800, tickers=["600276.SH"], latest="2026-11-03")
        self.assertEqual(stats["ok"], 1)
        self.assertIn("bars:600276:off800", fake.calls)  # --backfill 透传到 bars offset

    def test_tickers_with_sectors_scope_rejected(self) -> None:
        # 板块是枚举制清单无子集路径，--tickers 配 --scope sectors 在 argparse 层拒绝
        with self.assertRaises(SystemExit):
            ums.main(["--scope", "sectors", "--tickers", "600276.SH"])

    def test_invalid_ticker_argument_rejected(self) -> None:
        # M3：无后缀/海外票入参在 argparse 层拒绝（600276 会被拼成错市场的 .SZ）
        for bad in ("600276", "^SOX", "00700.HK"):
            with self.assertRaises(SystemExit, msg=bad):
                ums.main(["--tickers", bad, "--scope", "stocks"])

    def test_batch_overwrites_snapshot_written_intraday_row(self) -> None:
        # spec §9 端到端（当日时序）：交易日 16:30 前钩子已写盘中价行（amount=None），
        # 16:30 批量同日跑不得 skip——重拉让 batch 档权威覆盖为收盘价，当日可达而非 T+1
        upsert_series_rows(
            series_file(self.root, "600276.SH"),
            [{"date": "2026-11-02", "open": None, "high": None, "low": None, "close": 70.01,
              "volume": None, "amount": None, "source": "mootdx"}], writer="snapshot")
        fake = FakeMootdx(bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, tickers=["600276.SH"], latest="2026-11-02")  # 同日
        self.assertEqual(stats["ok"], 1)  # 钩子行无 amount 指纹 → 不 skip，照常拉 bars
        row = read_series_rows(series_file(self.root, "600276.SH"))[-1]
        self.assertEqual(row["close"], 71.54)   # 盘中价被权威覆盖
        self.assertEqual(row["amount"], 8.0e7)  # null 被批量补齐

    def test_rerun_resumes_after_partial_failure(self) -> None:
        # spec §9 断点续传：首跑一票失败，重跑只补失败票、已成功票 skip
        stocks = _stocks_frame([("600276", "a"), ("300476", "b")])

        def bars_by_symbol(symbol: str):
            if symbol == "600276":
                raise RuntimeError("socket dead")
            return _bars_frame(["2026-11-02"], [71.54])

        with patch.object(ums, "_mootdx_call", FakeMootdx(stocks=stocks, bars=bars_by_symbol)):
            first = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(first, {"ok": 1, "skip": 0, "fail": 1})
        self.assertIsNone(ums.last_round_date(self.root, "stocks"))  # fail>0 不写标记（N1），同日补跑不被挡
        with patch.object(ums, "_mootdx_call",
                          FakeMootdx(stocks=stocks, bars=_bars_frame(["2026-11-02"], [71.54]))):
            second = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(second, {"ok": 1, "skip": 1, "fail": 0})
        self.assertEqual(ums.last_round_date(self.root, "stocks"), "2026-11-02")  # 补跑干净才写标记

    def test_lock_conflict_counts_skip_and_blocks_marker(self) -> None:
        # I2：锁被其它进程持有 ≠ ok——skip 计数，且当轮完成标记不写（标记会把锁冲突票当日掩盖）
        @contextmanager
        def fake_lock(data_root, name, *, timeout_s=1.0):
            yield False

        fake = FakeMootdx(stocks=_stocks_frame([("600276", "恒瑞医药")]),
                          bars=_bars_frame(["2026-11-02"], [71.54]))
        with patch.object(ums, "series_lock", fake_lock), patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 0, "skip": 1, "fail": 0})  # skip 不 ok
        self.assertIsNone(ums.last_round_date(self.root, "stocks"))  # 锁冲突轮：无标记
        self.assertFalse(series_file(self.root, "600276.SH").exists())  # 确实没写

    def test_empty_bars_counts_skip_but_marker_written(self) -> None:
        # I2 取舍：长期停牌/无数据票（e2e 实测 ~45 只）空返回计 skip 但不阻止标记——
        # 否则这些票天天挡标记，闸门永远不生效、非交易日零成本失效
        fake = FakeMootdx(stocks=_stocks_frame([("600276", "a")]), bars=pd.DataFrame())
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_stocks_update(self.root, latest="2026-11-02")
        self.assertEqual(stats, {"ok": 0, "skip": 1, "fail": 0})
        self.assertEqual(ums.last_round_date(self.root, "stocks"), "2026-11-02")  # 标记照写


class SectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stocks_sh(self, rows: list[tuple[str, str]]) -> pd.DataFrame:
        return _stocks_frame(rows)

    def test_build_sector_list_filters_ranges_and_sorts(self) -> None:
        df = self._stocks_sh([("888880", "新标准券"), ("880324", "概念A"), ("880301", "行业A"),
                              ("880300", "下边界"), ("880099", "风格统计"), ("881270", "二级A"),
                              ("881999", "二级Z"), ("882001", "超上界"), ("600276", "个股混入")])
        got = ums.build_sector_list(df)
        codes = [x["code"] for x in got]
        self.assertEqual(codes, ["880300", "880301", "880324", "881270", "881999"])  # 边界含+过滤+排序
        self.assertEqual(got[0]["category"], "行业/概念")
        self.assertEqual(got[3]["category"], "二级行业")

    def test_first_run_writes_sector_list(self) -> None:
        # C7：首跑分支必须落盘，否则清单永远不存在、冻结/补录全是死代码
        df = self._stocks_sh([("880301", "行业A"), ("880099", "被过滤")])
        merged, added = ums.load_or_merge_sector_list(self.root, df)
        self.assertEqual([x["code"] for x in merged], ["880301"])
        on_disk = json.loads((self.root / "sector" / "sector-list.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, merged)  # 落盘成功
        self.assertEqual([x["code"] for x in added], ["880301"])

    def test_merge_keeps_frozen_and_picks_up_new(self) -> None:
        (self.root / "sector").mkdir(parents=True)
        (self.root / "sector" / "sector-list.json").write_text(
            json.dumps([{"code": "880301", "name": "行业A", "category": "行业/概念"},
                        {"code": "880999", "name": "已消失", "category": "行业/概念"}], ensure_ascii=False),
            encoding="utf-8")
        df = self._stocks_sh([("880301", "行业A改名"), ("880324", "新概念")])
        merged, added = ums.load_or_merge_sector_list(self.root, df)
        codes = [x["code"] for x in merged]
        self.assertIn("880999", codes)  # 消失项保留（文件冻结，不删）
        self.assertEqual([x["code"] for x in added], ["880324"])
        by_code = {x["code"]: x for x in merged}
        self.assertEqual(by_code["880301"]["name"], "行业A")  # 已登记项不覆盖

    def test_sectors_update_upserts_index_bars_with_counts(self) -> None:
        (self.root / "sector").mkdir(parents=True)
        df = self._stocks_sh([("880301", "行业A")])
        with patch.object(ums, "load_or_merge_sector_list", return_value=(
                [df.iloc[0].to_dict() | {"category": "行业/概念"}], [])):
            index_df = _bars_frame(["2026-11-02"], [3300.0], up_count=[16], down_count=[15])
            fake = FakeMootdx(stocks=df, index_bars=index_df)  # stocks 必须给：清单前的枚举调用
            with patch.object(ums, "_mootdx_call", fake):
                stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        row = read_series_rows(sector_series_file(self.root, "880301"))[-1]
        self.assertEqual(row["source"], "mootdx-index")
        self.assertEqual(row["up_count"], 16)
        self.assertEqual(row["down_count"], 15)

    def test_sectors_gate_reads_own_marker_not_stocks(self) -> None:
        # N1 核心：stocks 完成标记不得挡 sectors——canary 方案的病根就是 scopes 共享一个标志位
        ums.write_round_marker(self.root, "stocks", "2026-11-03")
        df = self._stocks_sh([("880301", "行业A")])
        index_df = _bars_frame(["2026-11-03"], [3300.0], up_count=[16], down_count=[15])
        fake = FakeMootdx(stocks=df, index_bars=index_df)
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})  # stocks 标记在，sectors 照跑
        self.assertEqual(ums.last_round_date(self.root, "sectors"), "2026-11-03")  # 干净轮写自己的标记

    def test_sectors_gate_short_circuits_on_own_marker(self) -> None:
        ums.write_round_marker(self.root, "sectors", "2026-11-03")
        fake = FakeMootdx(stocks=_stocks_frame([("880301", "行业A")]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 0})  # 整轮零调用
        self.assertFalse(fake.calls)  # 连清单枚举的 stocks 调用都没有（闸门在枚举之前）

    def test_sectors_lock_conflict_counts_skip_and_blocks_marker(self) -> None:
        # I2 sectors 调用点同款：锁冲突 → skip 不 ok，当轮 sectors 标记不写
        @contextmanager
        def fake_lock(data_root, name, *, timeout_s=1.0):
            yield False

        df = self._stocks_sh([("880301", "行业A")])
        with patch.object(ums, "series_lock", fake_lock):
            with patch.object(ums, "load_or_merge_sector_list", return_value=(
                    [{"code": "880301", "name": "行业A", "category": "行业/概念"}], [])):
                index_df = _bars_frame(["2026-11-02"], [3300.0], up_count=[16], down_count=[15])
                fake = FakeMootdx(stocks=df, index_bars=index_df)
                with patch.object(ums, "_mootdx_call", fake):
                    stats = ums.run_sectors_update(self.root, latest="2026-11-03")
        self.assertEqual(stats, {"ok": 0, "skip": 1, "fail": 0})
        self.assertIsNone(ums.last_round_date(self.root, "sectors"))


class IndicesTests(unittest.TestCase):
    """交易所核心指数（2026-11-03 加入，scope=indices/并入 all）：固定清单 + index_bars。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_indices_update_upserts_all_core_indices(self) -> None:
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-03"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_indices_update(self.root, latest="2026-11-04")
        self.assertEqual(stats, {"ok": len(ums._CORE_INDICES), "skip": 0, "fail": 0})
        requested = [c for c in fake.calls if c.startswith("index_bars:")]
        self.assertEqual(len(requested), len(ums._CORE_INDICES))  # 固定清单逐个打 index_bars
        self.assertIn("index_bars:000001:off30", requested)   # 上证指数
        self.assertIn("index_bars:399001:off30", requested)   # 深证成指（SZ 段）
        row = read_series_rows(index_series_file(self.root, "000001"))[-1]
        self.assertEqual(row["date"], "2026-11-03")
        self.assertEqual(row["source"], "mootdx-index")
        self.assertEqual(ums.last_round_date(self.root, "indices"), "2026-11-04")  # 干净轮写标记

    def test_indices_gate_reads_own_marker_not_stocks_sectors(self) -> None:
        # N1 同款隔离：stocks/sectors 的完成标记不得挡 indices
        ums.write_round_marker(self.root, "stocks", "2026-11-04")
        ums.write_round_marker(self.root, "sectors", "2026-11-04")
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-03"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_indices_update(self.root, latest="2026-11-04")
        self.assertEqual(stats["ok"], len(ums._CORE_INDICES))  # 两个标记在，indices 照跑
        self.assertEqual(ums.last_round_date(self.root, "indices"), "2026-11-04")

    def test_indices_gate_short_circuits_on_own_marker(self) -> None:
        ums.write_round_marker(self.root, "indices", "2026-11-04")
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-03"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_indices_update(self.root, latest="2026-11-04")
        self.assertEqual(stats, {"ok": 0, "skip": 0, "fail": 0})
        self.assertFalse(fake.calls)  # 非交易日/已完成日零服务器调用

    def test_indices_tail_latest_skips(self) -> None:
        index_series_file(self.root, "000001").parent.mkdir(parents=True)
        index_series_file(self.root, "000001").write_text(
            '{"date": "2026-11-04", "close": 3300.0, "amount": 1.0, "source": "mootdx-index"}\n',
            encoding="utf-8")
        fake = FakeMootdx(index_bars=_bars_frame(["2026-11-04"], [3300.0]))
        with patch.object(ums, "_mootdx_call", fake):
            stats = ums.run_indices_update(self.root, latest="2026-11-04")
        self.assertEqual(stats, {"ok": len(ums._CORE_INDICES) - 1, "skip": 1, "fail": 0})


if __name__ == "__main__":
    unittest.main()
