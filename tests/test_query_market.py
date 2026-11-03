"""query_market 单测：fixture 目录树上的 DuckDB 视图查询（duckdb 未装则整文件 skip）。"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


def _make_tree(root: Path) -> None:
    (root / "market" / "series").mkdir(parents=True)
    (root / "market" / "series" / "600276.SH.jsonl").write_text(
        '{"date": "2026-11-03", "open": 71.0, "high": 73.0, "low": 70.5, "close": 72.0, "volume": 100.0, "amount": 7200000.0, "source": "mootdx"}\n'
        '{"date": "2026-11-04", "open": 72.0, "high": 74.0, "low": 71.5, "close": 73.0, "volume": 110.0, "amount": 8000000.0, "source": "mootdx"}\n',
        encoding="utf-8")
    (root / "sector" / "series").mkdir(parents=True)
    (root / "sector" / "series" / "880301.jsonl").write_text(
        '{"date": "2026-11-03", "close": 3300.0, "up_count": 16, "down_count": 15, "source": "mootdx-index"}\n'
        '{"date": "2026-11-04", "close": 3333.0, "up_count": 20, "down_count": 10, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "sector" / "series" / "881270.jsonl").write_text(
        '{"date": "2026-11-03", "close": 1000.0, "source": "mootdx-index"}\n'
        '{"date": "2026-11-04", "close": 990.0, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "index" / "series").mkdir(parents=True)
    (root / "index" / "series" / "000001.jsonl").write_text(
        '{"date": "2026-11-03", "close": 3550.0, "amount": 4.2e11, "source": "mootdx-index"}\n'
        '{"date": "2026-11-04", "close": 3599.685, "amount": 4.9e11, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "index" / "series" / "399006.jsonl").write_text(
        '{"date": "2026-11-04", "close": 2655.5, "amount": 2.1e11, "source": "mootdx-index"}\n',
        encoding="utf-8")
    (root / "finance").mkdir(parents=True)
    (root / "finance" / "gpcw-2026-09-30.jsonl").write_text(
        '{"code": "300476", "market": "SZ", "report_date": "2026-09-30", "eps_basic": 3.63, "revenue_yoy": 30.77, "file_hash": "h1", "schema_version": 1}\n',
        encoding="utf-8")
    (root / "finance" / "gpcw-2026-06-30.jsonl").write_text(  # 跨期 glob
        '{"code": "300476", "market": "SZ", "report_date": "2026-06-30", "eps_basic": 2.1, "revenue_yoy": 25.0, "file_hash": "h0", "schema_version": 1}\n',
        encoding="utf-8")
    (root / "custom").mkdir(parents=True)
    (root / "custom" / "korea-semi-export.jsonl").write_text(
        '{"date": "2026-10-21", "period": "2026-10", "value": 275.0, "unit": "亿美元", "source": "s"}\n',
        encoding="utf-8")
    (root / "custom" / "registry.json").write_text("{}", encoding="utf-8")  # 非 jsonl，不该进视图


@unittest.skipUnless(HAS_DUCKDB, "duckdb 未安装")
class QueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_tree(self.root)
        self.con = duckdb.connect(":memory:")
        import query_market as qm

        self.qm = qm

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_and_range(self) -> None:
        got = self.qm.query_quote(self.con, self.root, "600276.SH")
        self.assertEqual(got["close"], 73.0)
        rows = self.qm.query_range(self.con, self.root, "600276.SH", "2026-11-01", "2026-11-03")
        self.assertEqual([r["date"] for r in rows], ["2026-11-03"])

    def test_quote_routes_bare_code_to_sector(self) -> None:
        # I8：裸 6 位 = 板块代码 → sector_index 视图（spec §5.6 自动路由）
        got = self.qm.query_quote(self.con, self.root, "880301")
        self.assertEqual(got["close"], 3333.0)
        self.assertEqual(got["up_count"], 20)

    def test_quote_routes_bare_000_399_to_index_series(self) -> None:
        # 评审补测：裸 000/399 段 = 交易所指数 → index_series 视图（与个股 000001.SZ
        # 平安银行靠视图区分；此前零断言，路由回归无保护）
        self.assertEqual(self.qm._view_for("000001"), "index_series")
        self.assertEqual(self.qm._view_for("399006"), "index_series")
        got = self.qm.query_quote(self.con, self.root, "000001")
        self.assertEqual(got["close"], 3599.685)  # 上证指数 fixture 尾行
        self.assertEqual(self.qm.query_quote(self.con, self.root, "399006")["close"], 2655.5)

    def test_quote_bare_unknown_code_hints_suffix(self) -> None:
        # 评审 Minor5：裸深市个股码（000651 格力）落 index 视图查无 → null 退出 0 但
        # stderr 提示带后缀重试，不静默
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            rc = self.qm.main(["quote", "--ticker", "000651"])
        self.assertEqual(rc, 0)
        self.assertIn("000651.SZ", stderr.getvalue())  # 提示里给出带后缀的正确姿势
        self.assertIn("index_series", stderr.getvalue())

    def test_finance_orders_across_periods(self) -> None:
        rows = self.qm.query_finance(self.con, self.root, "300476", last=4)
        self.assertEqual([r["report_date"] for r in rows], ["2026-09-30", "2026-06-30"])  # 跨期倒序
        self.assertEqual(rows[0]["revenue_yoy"], 30.77)

    def test_sector_top_orders_by_pct(self) -> None:
        rows = self.qm.sector_top(self.con, self.root, top=10)
        self.assertEqual(rows[0]["code"], "880301")  # +1.0% 在前
        self.assertAlmostEqual(rows[0]["pct_change"], 1.0)
        self.assertEqual(rows[1]["code"], "881270")  # -1.0%
        self.assertEqual(rows[0]["up_count"], 20)

    def test_sql_view_excludes_registry(self) -> None:
        for view in self.qm._VIEW_PATTERNS:  # sql 语义：能建的都建
            try:
                self.qm.ensure_view(self.con, self.root, view)
            except RuntimeError:
                pass
        rows = self.qm.run_sql(self.con, "SELECT count(*) AS n FROM custom_series")
        self.assertEqual(rows[0]["n"], 1)  # registry.json 没混进来

    def test_missing_dir_raises_clear_error(self) -> None:
        # I1：残缺目录树（如 Step 11.1 时 finance/ 尚未生成）必须报清晰错误而非 DuckDB IO Error
        empty = self.root / "empty-tree"
        empty.mkdir()
        with self.assertRaises(RuntimeError):
            self.qm.ensure_view(self.con, empty, "finance")

    def test_view_sql_glob_and_no_union(self) -> None:
        # N4（e2e 实测定案）：~7500 文件时 union_by_name 建视图 OOM（38 GiB），显式
        # 文件列表同样 OOM——视图 SQL 必须是单条 glob 串且不带 union_by_name，
        # 防止后续为异构键集悄悄加回（异构需求应由写者纪律保证同构，见 spec §4）。
        self.qm.ensure_view(self.con, self.root, "market_quotes")
        sql = self.con.execute(
            "SELECT sql FROM duckdb_views() WHERE view_name = 'market_quotes'").fetchone()[0]
        self.assertIn("read_json_auto('", sql)      # glob 串而非显式列表
        self.assertIn("*.jsonl'", sql)
        self.assertNotIn("union_by_name", sql)      # 数千文件 schema 并集探测是 OOM 真凶
        self.assertIn("ignore_errors", sql)         # M11 torn 尾行容忍仍在

    def test_torn_tail_tolerated(self) -> None:
        # M11：read_json_auto 需 ignore_errors=true 才容忍 torn 尾行（默认坏行报错）
        market_file = self.root / "market" / "series" / "600276.SH.jsonl"
        market_file.write_text(market_file.read_text(encoding="utf-8") + '{"date": "2026-11-05", "clo',
                               encoding="utf-8")
        rows = self.qm.query_range(self.con, self.root, "600276.SH", "2026-11-01", "2026-12-31")
        self.assertEqual([r["date"] for r in rows], ["2026-11-03", "2026-11-04"])  # 半行被跳过


if __name__ == "__main__":
    unittest.main()
