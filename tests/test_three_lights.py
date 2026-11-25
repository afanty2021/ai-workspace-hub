"""three_lights 单测（Q-20261123-04 三灯接线）：全封闭不联网。

覆盖：新高止步连续天数、RV20 年化口径、EMA 金叉 fast/slow 对齐回归
（2026-11-23 冒烟实证：崩盘死叉曾被误报金叉——种子错位 13 根 bar）、
3c 金叉回退（连续 2 日收失守 21EMA；同日评审 I-5）、周线分组与完整周判定
（today 注入；灯2 等值=未收复的严格口径，评审 I-3）、HY OAS 否决与
灯1 熄灭联动（评审 M-1）、当日盘中快照行剔除（评审 I-4）、
日报段渲染降级、四灯总览组合逻辑。
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


class TrendStateCrossRevertTests(unittest.TestCase):
    """3c 回退（评审 I-5）：金叉后允许回踩，连续 2 日收盘失守 21EMA 才回退。"""

    def _golden_with_tail(self, tail: list[float]) -> list[float]:
        closes = _closes_series(80, lambda i: 100 * (0.99 ** i))   # 慢熊 80 日
        rec = [closes[-1]]
        for _ in range(12):
            rec.append(rec[-1] * 1.03)                              # 深反弹确立金叉
        return closes[:-1] + rec + tail

    def test_two_consecutive_closes_below_ema21_revert(self) -> None:
        ema21 = tl.trend_state(self._golden_with_tail([]))["ema21"]
        tail = [ema21 * 0.97, ema21 * 0.96]                         # 连续 2 日收失守
        state = tl.trend_state(self._golden_with_tail(tail))
        self.assertEqual(state["cross"], "golden", "EMA8 仍在 EMA21 上方（回踩非死叉）")
        self.assertTrue(state["cross_reverted"], "连续 2 日收失守 21EMA 必须回退")
        self.assertEqual(state["hold_streak"], 0)

    def test_single_dip_below_ema21_keeps_golden(self) -> None:
        base = self._golden_with_tail([])
        tail = [tl.trend_state(base)["ema21"] * 0.97, base[-1]]     # 单日回踩即收回
        state = tl.trend_state(self._golden_with_tail(tail))
        self.assertEqual(state["cross"], "golden")
        self.assertFalse(state["cross_reverted"], "单日回踩在容差内，不回退")

    def test_revert_latches_recovery_does_not_reset(self) -> None:
        """闩锁语义（Q-20261125-06 补定义）：回退后收复 21EMA 不复位——本轮金叉内
        已回退就是已回退，直到 EMA8 跌回 21EMA 下方再上穿（新交叉）才重新武装。"""
        base = self._golden_with_tail([])
        ema21 = tl.trend_state(base)["ema21"]
        tail = [ema21 * 0.97, ema21 * 0.96]                          # 连续 2 日失守 → 回退
        rec = [tail[-1]]
        for _ in range(8):
            rec.append(rec[-1] * 1.05)                               # 强收复 8 日
        state = tl.trend_state(self._golden_with_tail(tail + rec))
        self.assertEqual(state["cross"], "golden",
                         "EMA8 未跌回 21EMA 下方=无新交叉，仍在原金叉纪元")
        self.assertGreaterEqual(state["hold_streak"], 5, "收复已确立（尾部连续收在 21EMA 上）")
        self.assertTrue(state["cross_reverted"], "闩锁：收复不复位，本轮金叉内保持已回退")


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
        # 严格口径（评审 I-3）：3534.64 == 3534.64 等值=未收复——否则灯2 在崩盘
        # 当周即亮，与清单「首读窗 11-27 当周」矛盾
        self.assertFalse(state["above"])
        self.assertTrue(state["near_level"])  # 贴线标注

    def test_strictly_above_level_is_recovered(self) -> None:
        rows = self._gold_rows()
        rows[-1]["close"] = 3534.65                                # 严格高一分钱
        state = tl.gold_state(rows, today=date(2026, 11, 21))
        self.assertTrue(state["above"])
        self.assertTrue(state["near_level"])

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

    def _prepare_light1_green(self, root: Path) -> None:
        """灯1 其余腿全绿的夹具：美元 60 日冲高后回落（连续 5+ 日不创新高）、
        利率平台后缓降（<5.12）、IXIC/SOX 平稳低波动站稳 EMA21、黄金稳态高位。"""
        usd = [100 + i * 0.5 if i < 60 else 129.5 - (i - 60) * 0.5 for i in range(80)]
        rate = [5.0 if i < 60 else 5.0 - (i - 60) * 0.01 for i in range(80)]
        steady = _closes_series(80, lambda i: 100 + i * 0.05)
        _write_series(root, "^IXIC", steady)
        _write_series(root, "^SOX", steady)
        _write_series(root, "DX-Y.NYB", usd)
        _write_series(root, "^TNX", rate)
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
        # 灯1：单边新高序列 → 1a streak=0 → 灯1 ⬜；灯2：稳态高位 > 3534.64 → ✅
        overview = next(line for line in text.splitlines() if "**总览**" in line)
        self.assertIn("⬜ / 人工 / ✅ /", overview)

    def test_hy_veto_extinguishes_light1_overview(self) -> None:
        """1c 一票否决 → 灯1 熄灭（评审 M-1：此前该熔断腿零测试锁定）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_light1_green(root)
            text_clear = tl.format_three_lights(
                tl.assess_three_lights(root), "2026-11-23")
            (root / "custom" / "us-hy-oas.jsonl").write_text(
                json.dumps({"date": "2026-11-18", "value": 381.0}) + "\n" +
                json.dumps({"date": "2026-11-19", "value": 385.0}) + "\n",
                encoding="utf-8")
            text_veto = tl.format_three_lights(
                tl.assess_three_lights(root), "2026-11-23")
        overview_clear = next(ln for ln in text_clear.splitlines() if "**总览**" in ln)
        overview_veto = next(ln for ln in text_veto.splitlines() if "**总览**" in ln)
        self.assertIn("✅ / 人工 / ✅ / ✅", overview_clear)  # 前置：其余腿全绿灯1 本应亮
        self.assertIn("⬜ / 人工 / ✅ / ✅", overview_veto)   # 否决令灯1 熄灭（其余不变）
        self.assertIn("🚫 灯1 熄灭", text_veto)
        self.assertIn("否决触发", text_veto)

    def test_assess_excludes_today_intraday_snapshot_rows(self) -> None:
        """当日盘中快照行不得当收盘计入（评审 I-4）：剔除后读数用上一完成收盘。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_light1_green(root)
            with open(root / "market" / "series" / "DX-Y.NYB.jsonl", "a",
                      encoding="utf-8") as fh:  # 「当日」盘中暴涨假新高
                fh.write(json.dumps({"date": "2026-03-26", "close": 999.0,
                                     "source": "sina"}) + "\n")
            state = tl.assess_three_lights(root, today=date(2026, 3, 26))
            state_no_inject = tl.assess_three_lights(root)  # 真实今天>2026-03-26：行被计入
        self.assertEqual(state["usd"]["latest_date"], "2026-03-25")
        self.assertAlmostEqual(state["usd"]["latest"], 120.0)
        self.assertGreaterEqual(state["usd"]["streak"], 5)      # 假新高未清零连续段
        self.assertEqual(state_no_inject["usd"]["streak"], 0)   # 对照：不过滤即被污染


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
