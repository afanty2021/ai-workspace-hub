"""update_money_etf_premium 单测（Q-20261127-01 货币ETF折溢价温度计）：全封闭不联网。

覆盖：除权修复（F10 标签提前一日 → 前一日净值对价，2025-12-30 实录夹具）
与下修不误标（I-7：回落幅度 ≥EXDIV_MIN_DROP_RATIO 才算除权）、毒行守卫
（修复后 |bp|>200 口径断裂弃用但必可见——diag+missing+sidecar，2026-11-28
C1 修根；±200bp 内真实极端读数照记）、100 元固定净值锚、净值双源降级链
（pingzhongdata→lsjz，source 按实际源标注+请求参数锁定）、幂等 skip、
触发判定（连续 2 日+双基金同向+对齐基准=511880 末 2 日期）、除权窗静默、
性质标注三分支（语境按 asof 对齐 T−1，2026-11-28 C2 修根；阈值恰等边界
族，I-11）、关键常量字面量对拍（自引用夹具族防线）、kind 白名单契约、
main 退出码与账本记源（记源按实际写入；kind/run_id 断言，I-9；腿内中途
失败 source 不丢，S6）、毒行进 missing+sidecar 端到端（C1）。
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

# ---- 夹具 ----
# 511880 实录（2025-12-29/30/31 真实收盘与净值，2026-11-27 会话对拍数字）
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
# 511990 构造值（非实录——12-30/12-31 真实收盘=100.002/100.022，B 席 B-M-B3
# 实证原「实录」标注不实；本夹具取邻期实测值拼合以获得 -0.8/+0.4 双符号读数）
CLOSES_990 = [{"date": "2025-12-30", "close": 99.992},
              {"date": "2025-12-31", "close": 100.004}]


def _pingzhong_response(rows: list[dict],
                        day_offsets: list[int] | None = None) -> MagicMock:
    # x=北京日期当日 00:08 前的 UTC 毫秒（fetch 侧 +8h 转北京日期）：
    # base=UTC 2025-12-28 16:00 → 北京 12-29 00:00，逐行对齐 NAVS_880 日期。
    # day_offsets 缺省逐日连排；跨月夹具用显式 offsets（12-29+3=01-01 陷阱）。
    from datetime import datetime, timedelta, timezone
    base = datetime(2025, 12, 28, 16, 0, tzinfo=timezone.utc)
    offsets = day_offsets if day_offsets is not None else list(range(len(rows)))
    arr = [{"x": int((base + timedelta(days=o)).timestamp() * 1000),
            "y": r["nav"]} for o, r in zip(offsets, rows)]
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


def _prem(close: float, nav: float) -> float:
    return round((close / nav - 1.0) * 10000.0, 2)


class ComputePremiumTests(unittest.TestCase):
    def test_exdiv_repair_uses_prev_nav(self) -> None:
        rows, diag = ump.compute_premiums(CLOSES_880, NAVS_880)
        by = {r["date"]: r for r in rows}
        # 期望值由夹具字面量按公式现算（不依赖 eyeball 常数；舍入翻转点敏感度
        # 由公式化期望消除——B 席 B-M-B7）
        self.assertEqual(by["2025-12-29"]["prem_bp"], _prem(101.195, 101.1966))
        self.assertAlmostEqual(by["2025-12-29"]["prem_bp"], -0.16, places=2)
        # 修复：除权标签日用前一日净值 → -0.45bp（不修复=+114.73bp 假溢价）
        self.assertEqual(by["2025-12-30"]["prem_bp"], _prem(101.192, 101.1966))
        self.assertAlmostEqual(by["2025-12-30"]["prem_bp"], -0.45, places=2)
        self.assertTrue(by["2025-12-30"]["exdiv"])
        self.assertIn("exdiv-repair", by["2025-12-30"]["note"])
        self.assertEqual(by["2025-12-31"]["prem_bp"], _prem(100.075, 100.0581))
        self.assertAlmostEqual(by["2025-12-31"]["prem_bp"], 1.69, places=2)
        self.assertFalse(by["2025-12-31"]["exdiv"])
        self.assertEqual(diag["poisoned"], [])
        self.assertEqual(diag["nav_missing"], [])

    def test_repair_failure_extreme_recorded_not_dropped(self) -> None:
        # C1 修根回归：除权标签日已是除权后价格（修复救不回）→ 修复后 -108bp。
        # 原 ±50bp 守卫把它静默丢弃；±200bp 口径下这是「真实极端读数照记」域，
        # 落行+无弃行（它本就是温度计要抓的行情形态）。
        closes = [{"date": "2025-12-30", "close": 100.10}]
        navs = [{"date": "2025-12-27", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prem_bp"], _prem(100.10, 101.1966))
        self.assertAlmostEqual(rows[0]["prem_bp"], -108.36, places=2)
        self.assertTrue(rows[0]["exdiv"])  # 修复照标（回落真实发生）
        self.assertEqual(diag["poisoned"], [])

    def test_poison_row_dropped_above_200bp_visible(self) -> None:
        # 修复后仍 >±200bp = 口径断裂毒行：弃用不落盘，但必进 diag（C1 可见化）
        closes = [{"date": "2025-12-30", "close": 97.50}]
        navs = [{"date": "2025-12-27", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(rows, [])
        self.assertEqual(len(diag["poisoned"]), 1)
        p = diag["poisoned"][0]
        self.assertEqual(p["date"], "2025-12-30")
        self.assertAlmostEqual(p["prem_bp"], _prem(97.50, 101.1966), places=2)
        self.assertIn("口径断裂", p["reason"])

    def test_real_extreme_minus60bp_recorded(self) -> None:
        # C1 端到端病灶的最小复现：两日 -60bp 真实折价原被 ±50bp 守卫吞掉，
        # 修根后照记（温度计的存在意义就是抓这个）。
        closes = [{"date": "2026-01-05", "close": 99.40}]
        navs = [{"date": "2026-01-04", "nav": 100.0},
                {"date": "2026-01-05", "nav": 100.0}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual([r["prem_bp"] for r in rows], [-60.0])
        self.assertEqual(diag["poisoned"], [])

    def test_fixed_nav_anchor(self) -> None:
        rows, diag = ump.compute_premiums(CLOSES_990, [], fixed_nav=100.0)
        self.assertEqual([r["prem_bp"] for r in rows], [-0.8, 0.4])
        self.assertFalse(any(r["exdiv"] for r in rows))
        self.assertEqual(diag["poisoned"], [])

    def test_missing_nav_date_skipped_visibly(self) -> None:
        closes = [{"date": "2026-01-05", "close": 100.05}]  # 净值未披露（T+1）
        rows, diag = ump.compute_premiums(closes, NAVS_880)
        self.assertEqual(rows, [])
        self.assertEqual(diag["nav_missing"], ["2026-01-05"])  # 不再静默

    def test_small_nav_revision_not_repair(self) -> None:
        # I-7：净值小幅下修（100.10→100.09，回落 0.01%<0.05% 阈值）是数据
        # 修订非除权——不修复、不标 exdiv（原实现误标，末 2 行会毒化真触发；
        # 原测试名 test_nav_drop_small_interest_like_not_repair 断言的却是
        # 「会被修复」，名实相反一并修）
        navs = [{"date": "2026-01-02", "nav": 100.10},
                {"date": "2026-01-05", "nav": 100.09}]
        closes = [{"date": "2026-01-05", "close": 100.095}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(rows[0]["nav"], 100.09)  # 用当日披露净值
        self.assertFalse(rows[0]["exdiv"])
        self.assertNotIn(ump.EXDIV_MARK, rows[0]["note"])
        self.assertEqual(diag["poisoned"], [])

    def test_exdiv_min_drop_ratio_boundary(self) -> None:
        # I-11：回落幅度跨 EXDIV_MIN_DROP_RATIO 两侧行为翻转。ratio 是浮点
        # 比较，「恰等」在 float 语义下无歧义点——取阈值两侧 1e-8 夹逼的两点
        # （0.05000001 ≥ 0.0005 修复 / 0.04999999 < 0.0005 不修复）。
        def rows_for(nav_today: float) -> tuple[list, dict]:
            navs = [{"date": "2026-01-02", "nav": 100.0},
                    {"date": "2026-01-05", "nav": nav_today}]
            return ump.compute_premiums([{"date": "2026-01-05", "close": nav_today}],
                                        navs)
        rows_hi, _ = rows_for(100.0 - 0.05000001)   # 回落 0.05000001/100 ≥ 阈值 → 修复
        rows_lo, _ = rows_for(100.0 - 0.04999999)   # 回落 0.04999999/100 < 阈值 → 不修复
        self.assertTrue(rows_hi[0]["exdiv"])
        self.assertFalse(rows_lo[0]["exdiv"])

    def test_nan_close_rejected_in_compute(self) -> None:
        # 原实现 NaN 穿透 compute（abs(nan)>50 为 False）到 append_record 才
        # 炸整腿；修根后在 compute 层拒收进 poisoned，腿内其余行照常落盘
        closes = [{"date": "2026-01-05", "close": float("nan")},
                  {"date": "2026-01-06", "close": 100.0}]
        navs = [{"date": "2026-01-05", "nav": 100.0},
                {"date": "2026-01-06", "nav": 100.0}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual([r["date"] for r in rows], ["2026-01-06"])
        self.assertEqual(len(diag["poisoned"]), 1)
        self.assertIn("close 非法", diag["poisoned"][0]["reason"])

    def test_note_roundtrip_precision(self) -> None:
        # note 4 位小数可逐位复算（2026-11-28 M1：原 %g 截断致 511880 存量
        # 484/539 行不可重算）；修复行另存 nav_raw=当日披露净值
        rows, _ = ump.compute_premiums(CLOSES_880, NAVS_880)
        by = {r["date"]: r for r in rows}
        for day, row in by.items():
            note = row["note"]
            close_part = float(note.split("close=")[1].split(" ")[0])
            nav_part = float(note.split("nav=")[1].split(" ")[0])
            self.assertEqual(close_part, row["close"])
            self.assertEqual(nav_part, row["nav"])
            recomputed = (close_part / nav_part - 1.0) * 10000.0
            self.assertAlmostEqual(recomputed, row["prem_bp"], places=2)
        self.assertIn("nav_raw=100.0442", by["2025-12-30"]["note"])
        self.assertNotIn("nav_raw", by["2025-12-29"]["note"])


class UpsertIdempotencyTests(unittest.TestCase):
    def test_skip_on_rerun(self) -> None:
        rows, _ = ump.compute_premiums(CLOSES_990, [], fixed_nav=100.0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = ump.upsert_premiums(root, ump.PREM_511990_SERIES,
                                        ump.NAME_511990, "mootdx+nav100anchor", rows)
            second = ump.upsert_premiums(root, ump.PREM_511990_SERIES,
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
        self.assertEqual(stats["poisoned"], [])

    def test_lsjz_request_params_locked(self) -> None:
        # B-M-B2：取数层 mock 原按 URL 子串匹配不锁参数（fundCode/pageSize/
        # pageIndex 算式测不出）——对 lsjz 请求参数逐项锁死
        calls: list[tuple[str, dict | None]] = []
        lsjz = _lsjz_response(NAVS_880)

        def _get(url, params=None, **kwargs):
            calls.append((url, params))
            if "pingzhongdata" in url:
                raise _rq.ConnectionError("drop")
            return lsjz

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars",
                      return_value=CLOSES_880), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            ump.update_511880(Path(tmp), days=30)
        lsjz_calls = [(u, p) for u, p in calls if "/f10/lsjz" in u]
        self.assertTrue(lsjz_calls, "lsjz 降级链未被触发")
        url, params = lsjz_calls[0]
        self.assertIn("api.fund.eastmoney.com/f10/lsjz", url)
        self.assertEqual(params["fundCode"], "511880")
        self.assertEqual(params["pageSize"], 20)
        self.assertEqual(params["pageIndex"], 1)

    def test_dual_nav_fail_raises(self) -> None:
        def _get(url, **kwargs):
            raise _rq.ConnectionError("drop")

        with patch("update_money_etf_premium._mootdx_bars",
                   return_value=CLOSES_880), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            with self.assertRaises(RuntimeError):
                ump.update_511880(Path(tempfile.mkdtemp()), days=30)

    def test_mootdx_offset_capped_at_800(self) -> None:
        # M11 下半：offset 超 800 截断并记 warning（原实现超限行为未定义）
        with patch("update_money_etf_premium._mootdx_call",
                   return_value=None) as fake_call, \
                patch("update_money_etf_premium.log") as fake_log:
            with self.assertRaises(RuntimeError):
                ump._mootdx_bars("511880", offset=900)
        self.assertEqual(fake_call.call_args.kwargs["offset"], 800)
        self.assertTrue(any("800" in str(c.args) for c in fake_log.call_args_list))


def _write_state_fixture(root: Path, rows_880: list[tuple[str, float, str]],
                         rows_990: list[tuple[str, float]]) -> None:
    for day, value, note in rows_880:
        append_record(root, series=ump.PREM_511880_SERIES, name="x", date=day,
                      value=value, unit="bp", source="test", note=note)
    for day, value in rows_990:
        append_record(root, series=ump.PREM_511990_SERIES, name="y", date=day,
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

    def test_alert_threshold_equal_boundary_not_triggered(self) -> None:
        # I-11：恰等阈值不越线（触发判据为严格 <）
        st = self._state(
            [("2026-11-25", -5.0, ""), ("2026-11-26", -5.0, "")],
            [("2026-11-25", -5.0, ), ("2026-11-26", -5.0, )])
        self.assertFalse(st["triggered"])
        self.assertEqual(st["reason"], "")  # 非「单基金越线」也非静默——正常态
        self.assertIn("正常噪声区间", ump.classify_state(st))

    def test_alert_threshold_just_below_boundary_triggers(self) -> None:
        st = self._state(
            [("2026-11-25", -5.001, ""), ("2026-11-26", -5.001, "")],
            [("2026-11-25", -5.001, ), ("2026-11-26", -5.001, )])
        self.assertTrue(st["triggered"])

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

    def test_empty_880_fallback_reason_visible(self) -> None:
        # M9：主序列空时 asof 回退 990 日期须显式标注，不得被读成正常态
        st = self._state([], [("2026-11-26", 0.4, )])
        self.assertEqual(st["asof"], "2026-11-26")
        self.assertIn("511880 序列空", st["reason"])
        self.assertIn("missing", ump.classify_state(st))

    def test_index_and_shibor_context_aligned_to_asof(self) -> None:
        # C2 修根回归：语境锚=asof（11-26）当日行与前一行。夹具特意放进
        # 11-27 的 +3.73% / +1.0bp（原实现会错拿它们标注 11-26 读数），
        # 修根后必须被忽略。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-11-25", "close": 3476.88}) + "\n" +
                json.dumps({"date": "2026-11-26", "close": 3477.23}) + "\n" +
                json.dumps({"date": "2026-11-27", "close": 3606.49}) + "\n",
                encoding="utf-8")
            append_record(root, series="shibor-1w", name="s", date="2026-11-25",
                          value=1.373, unit="%", source="t")
            append_record(root, series="shibor-1w", name="s", date="2026-11-26",
                          value=1.367, unit="%", source="t")
            append_record(root, series="shibor-1w", name="s", date="2026-11-27",
                          value=1.377, unit="%", source="t")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertEqual(st["asof"], "2026-11-26")
        self.assertEqual(st["index"]["date"], "2026-11-26")
        self.assertEqual(st["index"]["chg_pct"], 0.01)   # 对齐 T−1（原锁死 +3.73）
        self.assertEqual(st["shibor"]["date"], "2026-11-26")
        self.assertEqual(st["shibor"]["value_pct"], 1.367)
        self.assertEqual(st["shibor"]["chg_bp"], -0.6)   # 对齐 T−1（原锁死 +1.0）

    def test_context_without_asof_rows_is_none(self) -> None:
        # 指数/Shibor 序列尚无 ≤asof 的两行 → 语境缺（None），不拿未来行硬凑
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-11-27", "close": 3606.49}) + "\n",
                encoding="utf-8")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertIsNone(st["index"])

    def test_index_torn_line_skipped_not_whole_section(self) -> None:
        # M4：指数文件单行 torn JSON 跳过该行，不整段降级
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                '{"date": "2026-11-25", "close": 3476.88}\n' +
                '{"date": "2026-11-26", "clo\n' +          # torn 行
                '{"date": "2026-11-26", "close": 3477.23}\n',
                encoding="utf-8")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertIsNotNone(st["index"])
        self.assertEqual(st["index"]["chg_pct"], 0.01)


class ClassifyTests(unittest.TestCase):
    def _state(self, *, triggered=True, index=None, shibor=None, reason="",
               silent=False):
        return {"triggered": triggered, "silent": silent, "reason": reason,
                "index": index, "shibor": shibor,
                "rows_880": [], "rows_990": [], "n_rows_880": 2,
                "asof": "2026-11-26", "today": "2026-11-27",
                "poisoned_recent": []}

    def test_risk_off_label(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": -1.2},
            shibor={"date": "2026-11-26", "value_pct": 1.5, "chg_bp": 4.0}))
        self.assertIn("risk-off", text)
        self.assertIn("非做多", text)
        self.assertIn("2026-11-26", text)  # Shibor 日期入标注行（M5）

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
        self.assertIn("连续2日<-5bp", text)  # 文案由常量拼装（M10）

    def test_silent_line(self) -> None:
        text = ump.classify_state(self._state(triggered=False, silent=True,
                                              reason="除权窗静默"))
        self.assertIn("静默", text)

    def test_sample_insufficient_is_missing_not_not_triggered(self) -> None:
        # M13：「没查成」按 object-model 词表落 missing，不冒充「未触发」
        text = ump.classify_state(self._state(triggered=False,
                                              reason="样本不足（511880 行数 <2）"))
        self.assertIn("missing", text)
        self.assertNotIn("未触发", text)

    # ---- I-11：每阈值一个「恰等于边界」用例 ----
    def test_risk_off_shibor_equal_3bp(self) -> None:
        text = ump.classify_state(self._state(
            index=None, shibor={"date": "2026-11-26", "value_pct": 1.5,
                                "chg_bp": 3.0}))
        self.assertIn("risk-off", text)

    def test_shibor_just_below_3bp_not_risk_off(self) -> None:
        text = ump.classify_state(self._state(
            index=None, shibor={"date": "2026-11-26", "value_pct": 1.5,
                                "chg_bp": 2.9}))
        self.assertIn("方向不明", text)

    def test_risk_off_index_equal_minus_half(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": -0.5}, shibor=None))
        self.assertIn("risk-off", text)

    def test_index_just_above_minus_half_not_risk_off(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": -0.49}, shibor=None))
        self.assertIn("方向不明", text)

    def test_risk_on_boundary_index_half_shibor_one_bp(self) -> None:
        # risk_on = 股指 ≥+0.5 且 Shibor ≤+1.0：双边界恰等即亮
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 0.5},
            shibor={"date": "2026-11-26", "value_pct": 1.4, "chg_bp": 1.0}))
        self.assertIn("risk-on", text)

    def test_risk_on_broken_by_shibor_above_one_bp(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 0.5},
            shibor={"date": "2026-11-26", "value_pct": 1.4, "chg_bp": 1.1}))
        self.assertIn("方向不明", text)


class FormatSectionTests(unittest.TestCase):
    def test_normal_section(self) -> None:
        st = {"triggered": False, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-26", "value": -0.15}],
              "rows_990": [{"date": "2026-11-26", "value": 0.4}],
              "n_rows_880": 2, "asof": "2026-11-26", "today": "2026-11-27",
              "index": None, "shibor": None, "poisoned_recent": []}
        text = ump.format_money_etf_section(st)
        self.assertIn("货币ETF场内折溢价", text)
        self.assertIn("11-26 -0.15bp", text)
        self.assertIn("正常噪声区间", text)
        self.assertNotIn("序列陈旧", text)
        self.assertNotIn("近期弃行", text)

    def test_triggered_section_has_warning(self) -> None:
        st = {"triggered": True, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-26", "value": -7.0}],
              "rows_990": [{"date": "2026-11-26", "value": -8.0}],
              "n_rows_880": 2, "asof": "2026-11-26", "today": "2026-11-27",
              "index": {"date": "2026-11-26", "chg_pct": -1.0}, "shibor": None,
              "poisoned_recent": []}
        text = ump.format_money_etf_section(st)
        self.assertIn("⚠️", text)
        self.assertIn("risk-off", text)

    def test_poisoned_recent_line_rendered(self) -> None:
        # C1 可见化的日报面：sidecar 近期弃行 → 显式提示行
        st = {"triggered": False, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-26", "value": 0.1}],
              "rows_990": [], "n_rows_880": 2, "asof": "2026-11-26",
              "today": "2026-11-27", "index": None, "shibor": None,
              "poisoned_recent": [{"date": "2026-11-26", "prem_bp": -365.3,
                                   "series": ump.PREM_511880_SERIES}]}
        text = ump.format_money_etf_section(st)
        self.assertIn("近期弃行 1 条", text)
        self.assertIn("2026-11-26", text)
        self.assertIn("口径断裂", text)

    def test_stale_series_marked(self) -> None:
        st = {"triggered": False, "silent": False, "reason": "",
              "rows_880": [{"date": "2026-11-01", "value": 0.1}],
              "rows_990": [], "n_rows_880": 2, "asof": "2026-11-01",
              "today": "2026-11-27", "index": None, "shibor": None,
              "poisoned_recent": []}
        text = ump.format_money_etf_section(st)
        self.assertIn("序列陈旧", text)

    def test_stale_gap_boundary_ten_days_not_marked(self) -> None:
        # I-11：陈旧阈值恰等 10 日历日不告警（严格 >），11 日才告警
        for asof, expect_stale in (("2026-11-17", False),   # gap=10
                                   ("2026-11-16", True),    # gap=11
                                   ("2026-11-22", False)):  # gap=5 正常滞后
            st = {"triggered": False, "silent": False, "reason": "",
                  "rows_880": [{"date": asof, "value": 0.1}],
                  "rows_990": [], "n_rows_880": 2, "asof": asof,
                  "today": "2026-11-27", "index": None, "shibor": None,
                  "poisoned_recent": []}
            text = ump.format_money_etf_section(st)
            self.assertEqual("序列陈旧" in text, expect_stale, msg=asof)


class SidecarTests(unittest.TestCase):
    def test_poison_sidecar_roundtrip_and_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ump._record_poison_sidecar(
                root, [{"date": "2026-11-26", "prem_bp": -365.3,
                        "series": ump.PREM_511880_SERIES,
                        "reason": "口径断裂"}], today="2026-11-27")
            recent = ump._read_poison_sidecar(root, today="2026-11-27")
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["date"], "2026-11-26")
            # 回看窗（14 日历日）外的不提示
            self.assertEqual(ump._read_poison_sidecar(root, today="2026-12-20"), [])
            # 空毒行不写文件
            ump._record_poison_sidecar(root, [], today="2026-11-27")
            self.assertEqual(len(ump._read_poison_sidecar(root, "2026-11-27")), 1)

    def test_sidecar_missing_or_corrupt_reads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])
            (root / ".state").mkdir()
            (root / ".state" / "money-etf-poison.json").write_text("not-json", "utf-8")
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])


class ConstantLiteralLockTests(unittest.TestCase):
    """自引用夹具族防线（B-M-B1，第 4 案）：夹具与断言一律用字面量，关键
    常量在此与字面量对拍——常量被误改时本组先红，而非让夹具跟着常量漂。"""

    def test_key_constants_locked_by_literals(self) -> None:
        self.assertEqual(ump.ALERT_THRESH_BP, -5.0)
        self.assertEqual(ump.CONSEC_DAYS, 2)
        self.assertEqual(ump.POISON_PREM_BP, 200.0)
        self.assertEqual(ump.EXDIV_MARK, "exdiv-repair")
        self.assertEqual(ump.EXDIV_MIN_DROP_RATIO, 0.0005)
        self.assertEqual(ump.BASELINE_P5_BP, -0.8)
        self.assertEqual(ump.BASELINE_P95_BP, 2.8)
        self.assertEqual(ump.STALE_GAP_DAYS, 10)
        self.assertEqual(ump.PREM_511880_SERIES, "cn-money-etf-prem-511880")
        self.assertEqual(ump.PREM_511990_SERIES, "cn-money-etf-prem-511990")
        self.assertEqual(ump.NAV_511990_ANCHOR, 100.0)


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
        # I-9：账本 kind/run_id 字面量断言（原 M69 零锁——改成合法白名单值
        # batch-liquidity 全量绿的洞）
        opens = [r for r in rows if r.get("type") == "open"]
        self.assertEqual(opens[0]["kind"], "batch-money-etf")
        self.assertTrue(closes[0]["run_id"].endswith("-batch-money-etf"))

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
                         [ump.PREM_511880_SERIES])  # 第二腿失败只进 missing
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

    def test_sources_used_recorded_on_mid_leg_failure(self) -> None:
        # S6/M8：腿内中途失败时，已写入行的 source 仍进 sources_used
        real_upsert = ump.upsert_premiums

        def flaky_upsert(data_root, series, name, source, rows, sink=None):
            real_upsert(data_root, series=series, name=name, source=source,
                        rows=rows[:1], sink=sink)
            raise RuntimeError("mid-leg boom")

        def bars(code, offset):
            return CLOSES_880 if code == "511880" else CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(NAVS_880)), \
                patch("update_money_etf_premium.upsert_premiums",
                      side_effect=flaky_upsert), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 1)  # 主锚半途炸=非零
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
        closes = [r for r in rows if r.get("type") == "data-close"]
        self.assertIn("pingzhongdata+mootdx", closes[0]["sources_used"])
        self.assertIn("mootdx+nav100anchor", closes[0]["sources_used"])
        self.assertEqual(len(closes[0]["data_targets"]), 2)  # 各腿半途已写 1 行

    def test_poison_row_lands_in_missing_and_sidecar(self) -> None:
        # C1 端到端：毒行弃用 → data-close missing（口径断裂属 missing 词表）
        # + sidecar 落痕，不再静默变瞎
        closes = list(CLOSES_880) + [{"date": "2026-01-05", "close": 97.50}]
        navs = NAVS_880 + [{"date": "2026-01-05", "nav": 100.0}]

        def bars(code, offset):
            return closes if code == "511880" else CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(
                          navs, day_offsets=[0, 1, 2, 7])), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 0)  # 弃行≠失败
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
            sidecar = json.loads(
                (Path(tmp) / ".state" / "money-etf-poison.json")
                .read_text(encoding="utf-8"))
        missing = rows[-1]["missing"]
        self.assertTrue(any("毒行弃用" in m["reason"] for m in missing), missing)
        self.assertTrue(any(m["item"] == ump.PREM_511880_SERIES and "毒行" in m["reason"]
                            for m in missing))
        self.assertEqual(sidecar[0]["series"], ump.PREM_511880_SERIES)
        self.assertEqual(sidecar[0]["date"], "2026-01-05")
        self.assertIn("recorded_at", sidecar[0])


if __name__ == "__main__":
    unittest.main()
