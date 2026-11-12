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

    def test_bare_index_codes_route_to_index_series_unconditionally(self) -> None:
        # C-1 修根锁（2026-11-12 max 评审）：裸 000/399 段路由必须无条件先于
        # path.exists()——persist 钩子曾写出 market/series/000300.jsonl 影子
        # （东财快照序列），旧序「影子存在→不回退」让快照序列静默顶掉权威
        # mootdx 管道、当日日报 5d/20d 误出「—」。变异：把路由改回
        # `not path.exists() and` 前置守卫 → 000300 读到影子 +2.50/—，测试红。
        index_dir = self.root / "index" / "series"
        index_dir.mkdir(parents=True)
        # 权威 index/series/000300.jsonl：21 行，closes[-21]=80、末 6 行 100..105
        # → 5d=+5.00、20d=(105-80)/80=+31.25（20d 只在权威文件凑得够 21 行）。
        closes = [80.0] + [90.0] * 14 + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        (index_dir / "000300.jsonl").write_text(
            "".join(
                f'{{"date": "2026-10-{d:02d}", "close": {c}, "source": "mootdx-index"}}\n'
                for d, c in zip(range(1, 22), closes)),
            encoding="utf-8")
        # 影子：market/series/000300.jsonl 6 行 200..205（被误读时 5d=+2.50）。
        (self.root / "market" / "series" / "000300.jsonl").write_text(
            "".join(
                f'{{"date": "2026-11-{d:02d}", "close": {200 + i}, "source": "eastmoney"}}\n'
                for i, d in enumerate(range(2, 8))),
            encoding="utf-8")
        # 反向案例：裸码只有 market/series 影子、无权威文件 → 一律 "—"（宁缺勿假，
        # 旧序会读影子算出 +X.XX 假值）。
        (self.root / "market" / "series" / "399006.jsonl").write_text(
            '{"date": "2026-11-06", "close": 2655.5, "source": "eastmoney"}\n'
            '{"date": "2026-11-07", "close": 2660.0, "source": "eastmoney"}\n', encoding="utf-8")
        stats = load_rolling_stats(["000300", "399006"], self.root)
        self.assertEqual(stats["000300"]["5d"], "+5.00")    # 权威管道，非影子的 +2.50
        self.assertEqual(stats["000300"]["20d"], "+31.25")
        self.assertEqual(stats["399006"]["5d"], "—")         # 裸码无视 market/series 影子

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

    def test_note_mentions_dashboard_and_backfill_depth(self) -> None:
        # 口径注记必须带仪表指引 + 回补全窗语义（2026-11-09 起七票 ~2024-09 全深度，
        # 「—」仅新增票积累期出现——旧文案「2026-11-03 起积累中」已过时，防回退）
        self.assertIn("liquidity-dashboard", CROSS_ASSET_NOTE)
        self.assertIn("回补", CROSS_ASSET_NOTE)
        self.assertIn("积累期", CROSS_ASSET_NOTE)


if __name__ == "__main__":
    unittest.main()


class DerivedRowTests(unittest.TestCase):
    """派生行（Q-20261112-24）：COMEX-LME 价差 / 金铜比。

    期望值硬编码（换算系数 2204.62 lb/公吨 若被误改如 2000，本组全红）。
    """

    @staticmethod
    def _q(extra: list[dict]) -> list[dict]:
        return list(_QUOTES) + extra  # _QUOTES 已含 HG=F 伦敦铜 13755.5

    def test_comex_lme_spread_cents_scale(self) -> None:
        # HG00Y 报美分/磅（东财 101.HG00Y 实测刻度）：629¢/lb
        # 629 × 2204.62 / 100 = 13,867.06 USD/t；− 13,755.5 = +111.56 → 升水
        quotes = self._q([{"ticker": "HG00Y", "name": "COMEX铜连续", "market": "CMDTY",
                           "price": 629.0, "changesPercentage": 0.1}])
        text = render_cross_asset_table(quotes)
        self.assertIn("| COMEX-LME | 铜价差（关税交易仪表） | +112 USD/t | 升水 |", text)

    def test_comex_lme_spread_usd_scale_normalized(self) -> None:
        # 同价以美元/磅刻度（6.29 USD/lb）出现 → <20 归一 ×100，结果须与上例逐位一致
        quotes = self._q([{"ticker": "HG00Y", "name": "COMEX铜连续", "market": "CMDTY",
                           "price": 6.29, "changesPercentage": 0.1}])
        self.assertIn("+112 USD/t | 升水", render_cross_asset_table(quotes))

    def test_comex_lme_backwardation(self) -> None:
        # LME 抬到 14,000 → 13,867.06 − 14,000 = −132.94 → 倒挂
        quotes = self._q([{"ticker": "HG00Y", "name": "COMEX铜连续", "market": "CMDTY",
                           "price": 629.0, "changesPercentage": 0.1},
                          {"ticker": "HG=F", "name": "伦敦铜", "market": "CMDTY",
                           "price": 14000.0, "changesPercentage": 0.0}])
        self.assertIn("-133 USD/t | 倒挂", render_cross_asset_table(quotes))

    def test_gold_copper_ratio_and_missing_comex_leg(self) -> None:
        # 缺 HG00Y：COMEX-LME 整行跳过；金铜比（金 4000 / 铜 13755.5 = 0.2908）仍在
        quotes = self._q([{"ticker": "XAUUSD=X", "name": "伦敦金", "market": "CMDTY",
                           "price": 4000.0, "changesPercentage": 0.0}])
        text = render_cross_asset_table(quotes)
        rows = [ln for ln in text.splitlines() if ln.startswith("| COMEX-LME")]
        self.assertEqual(rows, [])
        self.assertIn("| 金铜比 | 伦敦金/伦铜 | 0.2908 | — | — | — |", text)

    def test_no_cmdty_legs_no_derived_rows(self) -> None:
        # 无 HG=F（也删金铜比腿）：两派生行都不出
        quotes = [q for q in _QUOTES if q["ticker"] != "HG=F"]
        text = render_cross_asset_table(quotes)
        self.assertNotIn("COMEX-LME | 铜价差", text)
        self.assertNotIn("金铜比", text)
