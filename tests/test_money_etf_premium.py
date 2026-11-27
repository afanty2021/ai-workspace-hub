"""update_money_etf_premium 单测（Q-20261127-01 货币ETF折溢价温度计）：全封闭不联网。

覆盖：除权修复（F10 标签提前一日 → 前一日净值对价，2025-12-30 实录夹具）、
毒行守卫（修复后 |bp|>50 弃用）、100 元固定净值锚、净值双源降级链
（pingzhongdata→lsjz，source 按实际源标注）、幂等 skip、触发判定（连续 2 日
+双基金同向+对齐基准=511880 末 2 日期）、除权窗静默、性质标注三分支、
kind 白名单契约、main 退出码与账本记源（记源按实际写入）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import requests as _rq
import update_money_etf_premium as ump
from save_custom_data import append_record

# ---- 实录夹具（2026-11-27 会话对拍数字）----
CLOSES_880 = [
    {"date": "2025-12-29", "close": 101.195},
    {"date": "2025-12-30", "close": 101.192},  # F10 除权标签日，价格次日才除权
    {"date": "2025-12-31", "close": 100.075},
]
NAVS_880 = [
    {"date": "2025-12-29", "nav": 101.1966},
    {"date": "2025-12-30", "nav": 100.0442},   # 净值回落（除权）
    {"date": "2025-12-31", "nav": 100.0581},
]
CLOSES_990 = [{"date": "2025-12-30", "close": 99.992},
              {"date": "2025-12-31", "close": 100.004}]


def _pingzhong_response(rows: list[dict]) -> MagicMock:
    # x=北京日期当日 00:08 前的 UTC 毫秒（fetch 侧 +8h 转北京日期）：
    # base=UTC 2025-12-28 16:00 → 北京 12-29 00:00，逐行对齐 NAVS_880 日期。
    from datetime import datetime, timedelta, timezone
    base = datetime(2025, 12, 28, 16, 0, tzinfo=timezone.utc)
    arr = [{"x": int((base + timedelta(days=i)).timestamp() * 1000),
            "y": r["nav"]} for i, r in enumerate(rows)]
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.text = f"var fS_name=\"x\"; Data_netWorthTrend = {json.dumps(arr)};"
    return mock


def _lsjz_response(rows: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"Data": {"LSJZList": [
        {"FSRQ": r["date"], "DWJZ": str(r["nav"])} for r in rows]}}
    return mock


class ComputePremiumTests(unittest.TestCase):
    def test_exdiv_repair_uses_prev_nav(self) -> None:
        rows = ump.compute_premiums(CLOSES_880, NAVS_880)
        by = {r["date"]: r for r in rows}
        self.assertAlmostEqual(by["2025-12-29"]["prem_bp"], -0.16, places=2)
        # 修复：除权标签日用前一日净值 → -0.45bp（不修复=+114.73bp 假溢价）
        self.assertAlmostEqual(by["2025-12-30"]["prem_bp"], -0.45, places=2)
        self.assertTrue(by["2025-12-30"]["exdiv"])
        self.assertIn(ump.EXDIV_MARK, by["2025-12-30"]["note"])
        self.assertAlmostEqual(by["2025-12-31"]["prem_bp"], 1.69, places=2)
        self.assertFalse(by["2025-12-31"]["exdiv"])

    def test_poison_row_dropped_after_repair(self) -> None:
        # 除权标签日已是除权后价格（修复救不回）→ |prem|>50 毒行守卫弃用
        closes = [{"date": "2025-12-30", "close": 100.10}]
        navs = [{"date": "2025-12-27", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442}]
        rows = ump.compute_premiums(closes, navs)
        self.assertEqual(rows, [])

    def test_fixed_nav_anchor(self) -> None:
        rows = ump.compute_premiums(CLOSES_990, [], fixed_nav=100.0)
        self.assertEqual([r["prem_bp"] for r in rows], [-0.8, 0.4])
        self.assertFalse(any(r["exdiv"] for r in rows))

    def test_missing_nav_date_skipped(self) -> None:
        closes = [{"date": "2026-01-05", "close": 100.05}]  # 净值未披露（T+1）
        rows = ump.compute_premiums(closes, NAVS_880)
        self.assertEqual(rows, [])

    def test_nav_drop_small_interest_like_not_repair(self) -> None:
        # 净值单调上行才常态；任何回落都按除权修复（货币基金无其他回落形态）
        navs = [{"date": "2026-01-02", "nav": 100.10},
                {"date": "2026-01-05", "nav": 100.09}]
        closes = [{"date": "2026-01-05", "close": 100.095}]
        rows = ump.compute_premiums(closes, navs)
        self.assertEqual(rows[0]["nav"], 100.10)  # 用前一日净值
        self.assertTrue(rows[0]["exdiv"])


class UpsertIdempotencyTests(unittest.TestCase):
    def test_skip_on_rerun(self) -> None:
        rows = ump.compute_premiums(CLOSES_990, [], fixed_nav=100.0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = ump.upsert_premiums(root, ump.SERIES_511990,
                                        ump.NAME_511990, "mootdx+nav100anchor", rows)
            second = ump.upsert_premiums(root, ump.SERIES_511990,
                                         ump.NAME_511990, "mootdx+nav100anchor", rows)
        self.assertEqual(first["imported"], 2)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped"], 2)  # 同 (series,date) 幂等 skip


class NavFallbackTests(unittest.TestCase):
    def test_auto_fallback_to_lsjz_marks_real_source(self) -> None:
        lsjz = _lsjz_response(NAVS_880)

        def _get(url, **kwargs):
            if "pingzhongdata" in url:
                raise _rq.ConnectionError("drop")
            return lsjz

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars",
                      return_value=CLOSES_880), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            root = Path(tmp)
            stats = ump.update_511880(root, days=30)
        self.assertEqual(stats["imported"], 3)
        self.assertEqual(stats["source"], "lsjz+mootdx")  # 实际源=备份位

    def test_dual_nav_fail_raises(self) -> None:
        def _get(url, **kwargs):
            raise _rq.ConnectionError("drop")

        with patch("update_money_etf_premium._mootdx_bars",
                   return_value=CLOSES_880), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            with self.assertRaises(RuntimeError):
                ump.update_511880(Path(tempfile.mkdtemp()), days=30)


def _write_state_fixture(root: Path, rows_880: list[tuple[str, float, str]],
                         rows_990: list[tuple[str, float]]) -> None:
    for day, value, note in rows_880:
        append_record(root, series=ump.SERIES_511880, name="x", date=day,
                      value=value, unit="bp", source="test", note=note)
    for day, value in rows_990:
        append_record(root, series=ump.SERIES_511990, name="y", date=day,
                      value=value, unit="bp", source="test")


class StateTests(unittest.TestCase):
    def _state(self, rows_880, rows_990, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(root, rows_880, rows_990)
            return ump.money_etf_state(root, today="2026-11-27", **kwargs)

    def test_trigger_two_days_both_funds(self) -> None:
        st = self._state(
            [("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-25", -6.5, ), ("2026-11-26", -8.0, )])
        self.assertTrue(st["triggered"])
        self.assertFalse(st["silent"])

    def test_no_trigger_single_fund(self) -> None:
        st = self._state(
            [("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
        self.assertFalse(st["triggered"])
        self.assertIn("单基金越线", st["reason"])

    def test_no_trigger_not_consecutive(self) -> None:
        st = self._state(
            [("2026-11-25", -1.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-25", -6.0, ), ("2026-11-26", -7.0, )])
        self.assertFalse(st["triggered"])  # 880 只有 1 日越线=非连续

    def test_exdiv_window_silent(self) -> None:
        st = self._state(
            [("2026-11-25", -6.0, f"close=1 nav=2 {ump.EXDIV_MARK}"),
             ("2026-11-26", -7.0, "")],
            [("2026-11-25", -6.0, ), ("2026-11-26", -7.0, )])
        self.assertFalse(st["triggered"])
        self.assertTrue(st["silent"])
        self.assertIn("除权窗静默", st["reason"])

    def test_align_base_is_511880_not_latest(self) -> None:
        # 511990（100 锚）天然比 511880（净值 T+1）超前一日：对齐基准=511880
        # 末 2 日期，511990 同日期缺行 → 显式缺行理由，而非拿超前行硬比。
        st = self._state(
            [("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-24", -6.0, ), ("2026-11-25", -7.0, ), ("2026-11-27", -9.0, )])
        self.assertFalse(st["triggered"])
        self.assertIn("2026-11-26", st["reason"])  # 511990 缺 11-26 行

    def test_index_and_shibor_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-11-26", "close": 3476.88}) + "\n" +
                json.dumps({"date": "2026-11-27", "close": 3606.49}) + "\n",
                encoding="utf-8")
            append_record(root, series="shibor-1w", name="s", date="2026-11-26",
                          value=1.367, unit="%", source="t")
            append_record(root, series="shibor-1w", name="s", date="2026-11-27",
                          value=1.377, unit="%", source="t")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertEqual(st["index"]["chg_pct"], 3.73)
        self.assertEqual(st["shibor"]["value_pct"], 1.377)
        self.assertEqual(st["shibor"]["chg_bp"], 1.0)


class ClassifyTests(unittest.TestCase):
    def _state(self, *, triggered=True, index=None, shibor=None, reason="",
               silent=False):
        return {"triggered": triggered, "silent": silent, "reason": reason,
                "index": index, "shibor": shibor,
                "rows_880": [], "rows_990": [], "n_rows_880": 2,
                "asof": "2026-11-26", "today": "2026-11-27"}

    def test_risk_off_label(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": -1.2},
            shibor={"date": "2026-11-26", "value_pct": 1.5, "chg_bp": 4.0}))
        self.assertIn("risk-off", text)
        self.assertIn("非做多", text)

    def test_risk_on_label(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 1.1},
            shibor={"date": "2026-11-26", "value_pct": 1.4, "chg_bp": 0.5}))
        self.assertIn("risk-on", text)

    def test_unknown_direction(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 0.2}, shibor=None))
        self.assertIn("方向不明", text)

    def test_normal_when_not_triggered(self) -> None:
        text = ump.classify_state(self._state(triggered=False))
        self.assertIn("正常噪声区间", text)

    def test_silent_line(self) -> None:
        text = ump.classify_state(self._state(triggered=False, silent=True,
                                              reason="除权窗静默"))
        self.assertIn("静默", text)


class FormatSectionTests(unittest.TestCase):
    def test_normal_section(self) -> None:
        st = {"triggered": False, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-26", "value": -0.15}],
              "rows_990": [{"date": "2026-11-26", "value": 0.4}],
              "n_rows_880": 2, "asof": "2026-11-26", "today": "2026-11-27",
              "index": None, "shibor": None}
        text = ump.format_money_etf_section(st)
        self.assertIn("货币ETF场内折溢价", text)
        self.assertIn("11-26 -0.15bp", text)
        self.assertIn("正常噪声区间", text)
        self.assertNotIn("序列陈旧", text)

    def test_triggered_section_has_warning(self) -> None:
        st = {"triggered": True, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-26", "value": -7.0}],
              "rows_990": [{"date": "2026-11-26", "value": -8.0}],
              "n_rows_880": 2, "asof": "2026-11-26", "today": "2026-11-27",
              "index": {"date": "2026-11-26", "chg_pct": -1.0}, "shibor": None}
        text = ump.format_money_etf_section(st)
        self.assertIn("⚠️", text)
        self.assertIn("risk-off", text)

    def test_stale_series_marked(self) -> None:
        st = {"triggered": False, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-01", "value": 0.1}],
              "rows_990": [], "n_rows_880": 2, "asof": "2026-11-01",
              "today": "2026-11-27", "index": None, "shibor": None}
        text = ump.format_money_etf_section(st)
        self.assertIn("序列陈旧", text)


class LedgerKindContractTests(unittest.TestCase):
    """接线契约：batch-money-etf 必须在 run_archive kind 白名单（同
    batch-us-liquidity 2026-11-22 判例：不在则 open 被 sentinel 吞掉）。"""

    def test_kind_whitelisted(self) -> None:
        import batch_ledger
        run_archive = batch_ledger._load_run_archive()
        self.assertIn("batch-money-etf", run_archive.KINDS)


class MainTests(unittest.TestCase):
    def test_main_ok_records_sources_and_ledger(self) -> None:
        def bars(code, offset):
            return CLOSES_880 if code == "511880" else CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(NAVS_880)), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 0)
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
        closes = [r for r in rows if r.get("type") == "data-close"]
        self.assertEqual(len(closes), 1)
        self.assertIn("pingzhongdata+mootdx", closes[0]["sources_used"])
        self.assertIn("mootdx+nav100anchor", closes[0]["sources_used"])
        self.assertEqual(len(closes[0]["data_targets"]), 2)
        self.assertEqual(closes[0]["missing"], [])

    def test_main_nonzero_when_primary_fails_second_leg_warns_only(self) -> None:
        def bars(code, offset):
            if code == "511880":
                raise RuntimeError("mootdx down")
            return CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 1)  # 主锚失败=非零
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
        closes = [r for r in rows if r.get("type") == "data-close"]
        self.assertEqual([m["item"] for m in closes[0]["missing"]],
                         [ump.SERIES_511880])  # 第二腿失败只进 missing
        self.assertEqual(len(closes[0]["data_targets"]), 1)  # 990 照常落盘

    def test_main_zero_when_second_leg_fails_only(self) -> None:
        def bars(code, offset):
            if code == "511990":
                raise RuntimeError("mootdx down")
            return CLOSES_880

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(NAVS_880)), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 0)  # 第二腿失败不置非零


class _Noop:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def _noop():
    return _Noop()


if __name__ == "__main__":
    unittest.main()
