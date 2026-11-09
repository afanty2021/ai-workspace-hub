"""跨资产例行扫描渲染测试（Q-20261109-03 德鲁肯米勒借鉴①）：

- render_cross_asset_table：按 market 分组过滤、固定顺序、rolling 注入、缺票跳过
- load_rolling_stats：本地 series 滚动计算、行数不足/缺文件/torn 行的 "—" 语义
- render_market_overview：FMP 无 key 不再渲染 6 行 N/A 死表
- movers 表 5d/20d 新列
- 模板占位符契约（CROSS_ASSET_TABLE/CROSS_ASSET_NOTE 防漂移）
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _test_paths  # noqa: F401
from generate_daily_report import (
    CROSS_ASSET_NOTE,
    load_rolling_stats,
    render_cross_asset_table,
    render_key_movers,
    render_market_overview,
    render_other_movers,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "tools" / "daily-watch" / "templates" / "daily-watchlist-report-template.md"

_QUOTES = [
    {"ticker": "600276.SH", "name": "恒瑞医药", "market": "CN", "price": 73.0,
     "changesPercentage": 1.37, "category": "医药"},
    {"ticker": "^SOX", "name": "费城半导体指数", "market": "INDEX", "price": 9390.25,
     "changesPercentage": -8.55},
    {"ticker": "DX-Y.NYB", "name": "美元指数", "market": "FX", "price": 102.2864,
     "changesPercentage": 0.76},
    {"ticker": "HG=F", "name": "伦敦铜", "market": "CMDTY", "price": 13755.5,
     "changesPercentage": -2.12},
    {"ticker": "NVDA", "name": "英伟达", "market": "US", "price": 187.59,
     "changesPercentage": 0.51},  # 美股个股：不进跨资产表
]


class CrossAssetTableTests(unittest.TestCase):
    def test_filters_by_market_and_keeps_fixed_order(self) -> None:
        text = render_cross_asset_table(_QUOTES)
        self.assertIn("| 代码 | 名称 | 最新 | 日涨跌 | 5d | 20d |", text)
        self.assertNotIn("600276.SH", text)   # CN 个股不入表
        self.assertNotIn("NVDA", text)        # US 个股不入表
        sox = text.index("^SOX")
        dxy = text.index("DX-Y.NYB")
        self.assertLess(sox, dxy)             # 固定顺序（SOX 在美元指数前）
        self.assertIn("9390.25", text)

    def test_rolling_cells_injected_and_missing_default(self) -> None:
        rolling = {"^SOX": {"5d": "-12.25", "20d": "—"}}
        text = render_cross_asset_table(_QUOTES, rolling)
        self.assertIn("-12.25", text)
        self.assertIn("-8.55", text)  # 日涨跌列仍由 format_pct 渲染
        # 未提供 rolling 的票占位 "—"
        dxy_line = [ln for ln in text.splitlines() if ln.startswith("| DX-Y.NYB")][0]
        self.assertEqual(dxy_line.count("—"), 2)

    def test_no_cross_asset_quotes_degrades_to_hint(self) -> None:
        text = render_cross_asset_table(_QUOTES[:1])  # 只有 CN 个股
        self.assertIn("未取得", text)
        self.assertIn("query_market.py liquidity", text)


class RollingStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        series = self.root / "market" / "series"
        series.mkdir(parents=True)
        # ^SOX 6 行 close 100..105：5d=(105-100)/100=+5.00，20d 不足 → —
        (series / "^SOX.jsonl").write_text(
            "".join(
                f'{{"date": "2026-11-{d:02d}", "close": {100 + i}, "source": "s"}}\n'
                for i, d in enumerate(range(2, 8))),
            encoding="utf-8")
        # torn 尾行容忍：600276.SH 2 行 + 半行
        (series / "600276.SH.jsonl").write_text(
            '{"date": "2026-11-05", "close": 72.0, "source": "mootdx"}\n'
            '{"date": "2026-11-06", "close": 73.0, "source": "mootdx"}\n'
            '{"date": "2026-11-07", "clo', encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rolling_math_and_insufficient_window(self) -> None:
        stats = load_rolling_stats(["^SOX", "600276.SH", "^TNX"], self.root)
        self.assertEqual(stats["^SOX"]["5d"], "+5.00")
        self.assertEqual(stats["^SOX"]["20d"], "—")     # 6 行 < 20
        self.assertEqual(stats["600276.SH"]["5d"], "—")  # 2 行有效（torn 跳过）
        self.assertEqual(stats["^TNX"]["5d"], "—")       # 文件缺失不炸

    def test_zero_base_close_degrades_to_dash(self) -> None:
        # 零基防御（评审 Q-20261109-03/04 M-3）：6 行且 closes[-6]=0.0 精确落在
        # 5d 基点位 → "—" 而非 ZeroDivisionError（load_rolling_stats 在
        # build_report 无条件调用，一处零基能炸整份日报）。
        (self.root / "market" / "series" / "^TNX.jsonl").write_text(
            "".join(
                f'{{"date": "2026-11-{d:02d}", "close": {c}, "source": "s"}}\n'
                for d, c in zip(range(1, 7), [0.0, 100.0, 101.0, 102.0, 103.0, 104.0])),
            encoding="utf-8")
        stats = load_rolling_stats(["^TNX"], self.root)
        self.assertEqual(stats["^TNX"]["5d"], "—")   # 基点 0.0 不炸
        self.assertEqual(stats["^TNX"]["20d"], "—")  # 行数不足

    def test_movers_tables_carry_new_columns(self) -> None:
        rolling = {"600276.SH": {"5d": "+1.37", "20d": "-3.21"}}
        key_text = render_key_movers(
            [{"ticker": "600276.SH", "name": "恒瑞医药", "changesPercentage": 1.37,
              "category": "医药"}], rolling)
        self.assertIn("| 代码 | 名称 | 涨跌幅 | 5d | 20d | 分类 | 摘要 |", key_text)
        self.assertIn("+1.37", key_text)
        other_text = render_other_movers(_QUOTES, None, rolling)
        self.assertIn("| 代码 | 名称 | 涨跌幅 | 5d | 20d |", other_text)


class MacroOverviewTests(unittest.TestCase):
    def test_no_key_degrades_to_hint_not_dead_table(self) -> None:
        # FMP 未配置（enabled 但 macro_data 空）→ 提示行，不再 6 行 N/A
        table, summary = render_market_overview({}, True)
        self.assertIn("跨资产例行扫描", table)
        self.assertNotIn("| VIX |", table)

    def test_with_data_still_renders_full_table(self) -> None:
        macro_data = {"macro": {"VIX": {"price": 15.2, "change_pct": -1.1}},
                      "sentiment": "neutral"}
        table, _ = render_market_overview(macro_data, True)
        self.assertIn("| VIX |", table)
        self.assertIn("| SPY |", table)


class TemplateContractTests(unittest.TestCase):
    def test_template_has_cross_asset_placeholders(self) -> None:
        # 占位符漂移防护：模板必须含跨资产表与口径注记两个占位符
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{CROSS_ASSET_TABLE}", text)
        self.assertIn("{CROSS_ASSET_NOTE}", text)
        self.assertIn("### 跨资产例行扫描", text)

    def test_note_mentions_dashboard_and_accumulation(self) -> None:
        # 口径注记必须带仪表指引与「积累中」语义（跨资产票 series 深度浅属预期）
        self.assertIn("liquidity-dashboard", CROSS_ASSET_NOTE)
        self.assertIn("积累", CROSS_ASSET_NOTE)


if __name__ == "__main__":
    unittest.main()
