"""three_lights 单测（Q-20261123-04 三灯接线）：全封闭不联网。

覆盖：新高止步连续天数、RV20 年化口径、EMA 金叉 fast/slow 对齐回归
（2026-11-23 冒烟实证：崩盘死叉曾被误报金叉——种子错位 13 根 bar）、
周线分组与完整周判定（today 注入）、HY OAS 否决、日报段渲染降级、
四灯总览组合逻辑。
"""

from __future__ import annotations

import json
import math
import statistics
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import _test_paths  # noqa: F401
import three_lights as tl


def _closes_series(n: int, fn) -> list[float]:
    return [float(fn(i)) for i in range(n)]


def _write_series(root: Path, ticker: str, closes: list[float],
                  start: str = "2026-01-05") -> None:
    """按自然日连续写 series（周五周六周日也在内——周分组用 ISO 键，无碍）。"""
    from datetime import timedelta

    path = root / "market" / "series" / f"{ticker}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    day0 = date.fromisoformat(start)
    lines = [json.dumps({"date": (day0 + timedelta(days=i)).isoformat(),
                         "close": c, "source": "test"})
             for i, c in enumerate(closes)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class StreakNotNewHighTests(unittest.TestCase):
    def test_new_high_today_is_zero(self) -> None:
        closes = _closes_series(70, lambda i: 100 + i * 0.1)  # 单边新高
        self.assertEqual(tl.streak_not_new_high(closes, 60), 0)

    def test_falling_tail_counts(self) -> None:
        closes = _closes_series(70, lambda i: 100 + i * 0.1)  # 涨到顶
        closes[-1] = closes[-2] - 1.0                          # 末日回落
        self.assertEqual(tl.streak_not_new_high(closes, 60), 1)

    def test_insufficient_samples_zero(self) -> None:
        self.assertEqual(tl.streak_not_new_high([1.0, 2.0, 3.0], 60), 0)


class RvTests(unittest.TestCase):
    def test_constant_return_zero_vol(self) -> None:
        closes = [100.0 * (1.001 ** i) for i in range(25)]
        self.assertAlmostEqual(tl.compute_rv_annpct(closes), 0.0, places=9)

    def test_matches_statistics_stdev(self) -> None:
        closes = _closes_series(30, lambda i: 100 * math.exp(0.01 * math.sin(i)))
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(10, 30)]
        expect = statistics.stdev(rets) * math.sqrt(252) * 100
        self.assertAlmostEqual(tl.compute_rv_annpct(closes), expect, places=6)

    def test_insufficient_none(self) -> None:
        self.assertIsNone(tl.compute_rv_annpct([100.0] * 20))

    def test_below_streak_counts_calm_tail(self) -> None:
        calm = [100.0 * (1.0001 ** i) for i in range(30)]     # 全程极低波动
        self.assertGreaterEqual(tl.rv_below_streak(calm), 5)

    def test_wild_vol_streak_zero(self) -> None:
        wild = [100.0 * (1.0 + (0.03 if i % 2 else -0.03)) for i in range(30)]
        self.assertEqual(tl.rv_below_streak(wild), 0)


class EmaTests(unittest.TestCase):
    def test_seed_sma_and_recursion(self) -> None:
        self.assertEqual(tl.ema_series([1.0, 2.0, 3.0, 4.0, 5.0], 3), [2.0, 3.0, 4.0])

    def test_insufficient_empty(self) -> None:
        self.assertEqual(tl.ema_series([1.0, 2.0], 3), [])


class TrendStateAlignmentRegressionTests(unittest.TestCase):
    """金叉对齐回归：fast/slow EMA 种子错位 13 根 bar 曾把崩盘死叉报成金叉。"""

    def test_crash_tail_is_dead_cross(self) -> None:
        # 79 日 +1% 慢牛积累 EMA8/21 差 ~6.7%，5×3% 收不完（差值衰减实测）——
        # 6×5% 才足以死叉；参数经数值求解，勿改小
        closes = _closes_series(80, lambda i: 100 * (1.01 ** i))
        crash = [closes[-1]]
        for _ in range(6):
            crash.append(crash[-1] * 0.95)
        closes = closes[:-1] + crash
        state = tl.trend_state(closes)
        self.assertTrue(state["ok"])
        self.assertEqual(state["cross"], "dead", "崩盘尾部必须判死叉（对齐回归）")
        self.assertIsNotNone(state["cross_days_ago"])
        self.assertLessEqual(state["cross_days_ago"], 6)

    def test_recovery_makes_golden_cross(self) -> None:
        closes = _closes_series(80, lambda i: 100 * (0.99 ** i))   # 慢熊 80 日
        rec = [closes[-1]]
        for _ in range(8):
            rec.append(rec[-1] * 1.02)                              # 强反弹 8 日
        closes = closes[:-1] + rec
        state = tl.trend_state(closes)
        self.assertEqual(state["cross"], "golden", "强反弹尾部必须判金叉")

    def test_hold_and_flat_counts(self) -> None:
        closes = _closes_series(60, lambda i: 100.0)                # 恒定盘
        state = tl.trend_state(closes)
        self.assertEqual(state["flat_streak"], 35)  # t=39..5（EMA21 共 40 点）
        self.assertEqual(state["hold_streak"], 0)   # close==EMA21 属「不高于」→ 不站稳


class WeeklyGoldTests(unittest.TestCase):
    def _gold_rows(self) -> list[dict]:
        # 2026-11-16(一)~11-20(五) 一周 + 前两周周五：11-06、11-13
        rows = []
        for day, close in (("2026-11-06", 4000.0), ("2026-11-13", 3879.92),
                           ("2026-11-16", 3700.0), ("2026-11-17", 3650.0),
                           ("2026-11-18", 3600.0), ("2026-11-19", 3560.0),
                           ("2026-11-20", 3534.64)):
            rows.append({"date": day, "close": close})
        return rows

    def test_weekend_saturday_last_week_completed(self) -> None:
        state = tl.gold_state(self._gold_rows(), today=date(2026, 11, 21))  # 周六
        self.assertTrue(state["ok"])
        self.assertEqual(state["week_end"], "2026-11-20")
        self.assertAlmostEqual(state["weekly_close"], 3534.64)
        self.assertTrue(state["above"])       # 3534.64 >= 3534.64（机械口径）
        self.assertTrue(state["near_level"])  # 贴线标注

    def test_friday_same_week_still_in_progress(self) -> None:
        state = tl.gold_state(self._gold_rows(), today=date(2026, 11, 19))  # 周四
        self.assertTrue(state["ok"])
        self.assertEqual(state["week_end"], "2026-11-13")  # 判的是上一完整周
        self.assertAlmostEqual(state["weekly_close"], 3879.92)
        self.assertTrue(state["above"])
        self.assertFalse(state["near_level"])

    def test_only_current_week_insufficient(self) -> None:
        rows = [{"date": "2026-11-18", "close": 3600.0}]
        state = tl.gold_state(rows, today=date(2026, 11, 19))
        self.assertFalse(state["ok"])
        self.assertEqual(state["reason"], "无完整周（样本仅本周）")


class HyOasStateTests(unittest.TestCase):
    def test_veto_requires_two_days(self) -> None:
        rows = [{"date": "2026-11-19", "value": 381.0},
                {"date": "2026-11-20", "value": 382.0}]
        state = tl.hy_oas_state(rows)
        self.assertTrue(state["veto"])

    def test_single_day_over_not_veto(self) -> None:
        rows = [{"date": "2026-11-18", "value": 350.0},
                {"date": "2026-11-19", "value": 381.0}]
        self.assertFalse(tl.hy_oas_state(rows)["veto"])

    def test_under_veto_line_clear(self) -> None:
        rows = [{"date": "2026-11-19", "value": 352.0}]
        state = tl.hy_oas_state(rows)
        self.assertFalse(state["veto"])
        self.assertEqual(state["value_bp"], 352.0)

    def test_empty_rows_not_ok(self) -> None:
        self.assertFalse(tl.hy_oas_state([])["ok"])


class FormatAndAssessTests(unittest.TestCase):
    def _prepare(self, root: Path) -> None:
        steady = _closes_series(80, lambda i: 100 + i * 0.05)
        _write_series(root, "^IXIC", steady)
        _write_series(root, "^SOX", steady)
        _write_series(root, "DX-Y.NYB", steady)
        _write_series(root, "^TNX", _closes_series(80, lambda i: 5.0))
        _write_series(root, "XAUUSD=X", _closes_series(80, lambda i: 3600.0 + i * 0.5))
        custom = root / "custom"
        custom.mkdir(parents=True, exist_ok=True)
        (custom / "us-hy-oas.jsonl").write_text(
            json.dumps({"date": "2026-11-19", "value": 352.0}) + "\n", encoding="utf-8")

    def test_assess_and_format_renders_overview_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare(root)
            state = tl.assess_three_lights(root)
            text = tl.format_three_lights(state, "2026-11-23")
        self.assertIn("**总览**", text)
        self.assertIn("FedWatch", text)          # 人工槽位
        self.assertIn("BTC 周线", text)          # 人工槽位
        self.assertIn("352.0bp", text)           # HY OAS 读数
        self.assertIn("RV20=", text)
        self.assertIn("12-09 FOMC 前为观察期", text)

    def test_missing_files_render_insufficient_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = tl.assess_three_lights(Path(tmp))
            text = tl.format_three_lights(state, "2026-11-23")
        self.assertIn("样本不足", text)
        self.assertIn("总览", text)

    def test_light2_gold_above_and_light1_not_lit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare(root)
            state = tl.assess_three_lights(root)
            text = tl.format_three_lights(state, "2026-11-23")
        # 灯1：单边新高序列 → 1a streak=0 → 灯1 ⬜；灯2：稳态高位 ≥ 3534.64 → ✅
        overview = next(line for line in text.splitlines() if "**总览**" in line)
        self.assertIn("⬜ / 人工 / ✅ /", overview)


class ReportIntegrationTests(unittest.TestCase):
    def test_render_section_degrades_on_error(self) -> None:
        import generate_daily_report as gdr
        # 传入不存在路径下不可读的 data_root（文件系统异常路径走 except 分支）
        with patch("three_lights.assess_three_lights",
                   side_effect=RuntimeError("boom")):
            text = gdr.render_three_lights_section(Path("/nonexistent"))
        self.assertIn("三灯读数本轮计算失败", text)
        self.assertIn("tech-reentry-three-lights.md", text)

    def test_render_section_ok_path(self) -> None:
        import generate_daily_report as gdr
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steady = _closes_series(80, lambda i: 100 + i * 0.05)
            _write_series(root, "^IXIC", steady)
            _write_series(root, "^SOX", steady)
            _write_series(root, "DX-Y.NYB", steady)
            _write_series(root, "^TNX", _closes_series(80, lambda i: 5.0))
            _write_series(root, "XAUUSD=X", steady)
            text = gdr.render_three_lights_section(root)
        self.assertIn("科技回补三灯读数", text)


if __name__ == "__main__":
    unittest.main()
