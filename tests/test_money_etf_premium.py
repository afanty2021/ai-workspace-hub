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
        # 由公式化期望消除——B 席 B-M-B7）；关键值 places=4（#29：余量收紧）
        self.assertEqual(by["2025-12-29"]["prem_bp"], _prem(101.195, 101.1966))
        self.assertAlmostEqual(by["2025-12-29"]["prem_bp"], -0.16, places=4)
        # 修复：除权标签日用前一日净值 → -0.45bp（不修复=+114.73bp 假溢价）
        self.assertEqual(by["2025-12-30"]["prem_bp"], _prem(101.192, 101.1966))
        self.assertAlmostEqual(by["2025-12-30"]["prem_bp"], -0.45, places=4)
        self.assertTrue(by["2025-12-30"]["exdiv"])
        self.assertIn("exdiv-repair", by["2025-12-30"]["note"])
        self.assertEqual(by["2025-12-31"]["prem_bp"], _prem(100.075, 100.0581))
        self.assertAlmostEqual(by["2025-12-31"]["prem_bp"], 1.69, places=4)
        self.assertFalse(by["2025-12-31"]["exdiv"])
        self.assertEqual(diag["poisoned"], [])
        self.assertEqual(diag["nav_missing"], [])

    def test_repair_failure_poisoned_not_recorded(self) -> None:
        # A-I1 二次修根回归：除权标签日已是除权后价格（修复救不回）→ 修复后
        # -108bp=修复失败（价/净值基准错位）。原 ±50bp 守卫把它静默丢弃（C1
        # 病灶）；修复波一度把它当「真实极端读数照记」锁成预期落行——2026-11-28
        # 评审 A-I1 定谳：−108bp 是价/净值基准错位，不是温度计要抓的行情
        # （基线 P5/P95=±3bp），按修复行 ±30bp 收紧=弃行显式缺行（diag+missing
        # +sidecar 可见），Q-20261128-03 ② 价/净值联合判定落地后 reason 再细化。
        closes = [{"date": "2025-12-30", "close": 100.10}]
        navs = [{"date": "2025-12-27", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(rows, [])
        self.assertEqual(len(diag["poisoned"]), 1)
        p = diag["poisoned"][0]
        self.assertEqual(p["date"], "2025-12-30")
        self.assertAlmostEqual(p["prem_bp"], _prem(100.10, 101.1966), places=4)
        self.assertAlmostEqual(p["prem_bp"], -108.36, places=2)
        self.assertIn("修复失败", p["reason"])

    def test_repair_failure_within_30bp_still_recorded(self) -> None:
        # A-I1 边界：修复行 |bp| ≤30 照记（真除权窗的正常读数域不受收紧影响）
        closes = [{"date": "2025-12-30", "close": 101.192}]
        navs = [{"date": "2025-12-29", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["exdiv"])
        self.assertEqual(diag["poisoned"], [])

    def test_exdiv_adjust_window_unrepaired_extreme_poisoned(self) -> None:
        # A-I1 F-D：标签日后 2 个交易日内价未随净值归位（隔日除权错位）→
        # 调整窗内未修复行 >±30bp 弃行显式缺行（原落 +113bp 假读数无标记）
        closes = [{"date": "2025-12-29", "close": 101.195},
                  {"date": "2025-12-30", "close": 101.192},
                  {"date": "2025-12-31", "close": 101.19},
                  {"date": "2026-01-02", "close": 100.08}]
        navs = [{"date": "2025-12-29", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442},
                {"date": "2025-12-31", "nav": 100.0581},
                {"date": "2026-01-02", "nav": 100.06}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual([r["date"] for r in rows],
                         ["2025-12-29", "2025-12-30", "2026-01-02"])
        self.assertEqual(len(diag["poisoned"]), 1)
        self.assertEqual(diag["poisoned"][0]["date"], "2025-12-31")
        self.assertIn("调整窗", diag["poisoned"][0]["reason"])
        # 窗内 ≤30bp 正常读数照记（守卫只吃异常量级）
        self.assertAlmostEqual([r for r in rows if r["date"] == "2026-01-02"][0]
                               ["prem_bp"], 2.0, places=4)

    def test_window_head_label_day_repaired_with_prepended_nav(self) -> None:
        # A-I1 F-A 化解：首拉窗头恰为除权标签日——update_511880 过滤 cutoff 时
        # 多带一行窗前净值，修复判据（需前一日净值）在窗头同样可用；原形态
        # +114.73bp 无标记假读数落盘（idx>0 守卫，协调者 M05 同点）。
        closes = [{"date": "2025-12-30", "close": 101.192},
                  {"date": "2025-12-31", "close": 100.075}]
        navs = [{"date": "2025-12-29", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 100.0442},
                {"date": "2025-12-31", "nav": 100.0581}]

        def _get(url, **kwargs):
            return _pingzhong_response(navs)

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars",
                      return_value=closes), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            root = Path(tmp)
            stats = ump.update_511880(root, days=30)
            rows = ump._read_series(root, ump.PREM_511880_SERIES, tail=5)
        # 落盘仍只含窗内两日；窗头标签日修复后 −0.45bp（不修复=+114.73bp）
        self.assertEqual([r["date"] for r in rows], ["2025-12-30", "2025-12-31"])
        self.assertAlmostEqual(rows[0]["value"], -0.45, places=2)
        self.assertEqual(stats["imported"], 2)
        self.assertEqual(stats["poisoned"], [])

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
        self.assertEqual(p["prem_bp"], _prem(97.50, 101.1966))
        self.assertIn("口径断裂", p["reason"])

    def test_poison_boundary_200bp_exact_recorded(self) -> None:
        # A-M12：98.0/100 → 恰 −200bp；浮点尘（-200.00000000000018）原使
        # abs>200 误弃边界行——先按 ROUND_BP 舍入再比较（守卫严格 >）
        closes = [{"date": "2026-01-05", "close": 98.0}]
        navs = [{"date": "2026-01-04", "nav": 100.0},
                {"date": "2026-01-05", "nav": 100.0}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual([r["prem_bp"] for r in rows], [-200.0])
        self.assertEqual(diag["poisoned"], [])
        closes = [{"date": "2026-01-05", "close": 97.999}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual(rows, [])
        self.assertEqual(len(diag["poisoned"]), 1)  # 越界一侧照弃

    def test_non_numeric_close_rejected(self) -> None:
        # F19/M046：close 非数值支（字符串）在 compute 层拒收，其余行照落
        closes = [{"date": "2026-01-05", "close": "100.0"},
                  {"date": "2026-01-06", "close": 100.0}]
        navs = [{"date": "2026-01-05", "nav": 100.0},
                {"date": "2026-01-06", "nav": 100.0}]
        rows, diag = ump.compute_premiums(closes, navs)
        self.assertEqual([r["date"] for r in rows], ["2026-01-06"])
        self.assertEqual(len(diag["poisoned"]), 1)
        self.assertIn("close 非法", diag["poisoned"][0]["reason"])

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
            # note 4 位小数的重算误差 ~0.01bp 量级——places=2 是正确容差，
            # 再紧会假红（#29：收紧只在直接断言面，重算面保持）
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

    def test_mootdx_bars_request_params_locked(self) -> None:
        # F9/M024-M027：取数参数契约——symbol 透传/frequency=9/offset 直传/
        # 空帧 RuntimeError
        with patch("update_money_etf_premium._mootdx_call",
                   return_value=None) as fake:
            with self.assertRaises(RuntimeError):
                ump._mootdx_bars("511990", offset=90)
        kwargs = fake.call_args.kwargs
        self.assertEqual(kwargs["symbol"], "511990")
        self.assertEqual(kwargs["frequency"], 9)
        self.assertEqual(kwargs["offset"], 90)

    def test_lsjz_pagination_stops_on_duplicate_page(self) -> None:
        # F10/M036：首页 20 行新鲜、次页全重复 → 恰 2 次请求即止（fresh==0=到头）
        page1 = [{"date": f"2026-01-{d:02d}", "nav": 100.0} for d in range(1, 21)]
        calls: list[int] = []

        def _get(url, params=None, **kwargs):
            calls.append(params["pageIndex"])
            return _lsjz_response(page1)  # 两页同内容=次页全重复

        with patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            rows = ump.fetch_nav_rows_lsjz("511880", pages=10)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(len(rows), 20)

    def test_lsjz_sleep_between_pages_not_after_last(self) -> None:
        # F10/M040：节流只在翻下一页前——末页后不空睡（东财 IP 级限流 footprint）
        page1 = [{"date": f"2026-01-{d:02d}", "nav": 100.0} for d in range(1, 21)]
        page2 = [{"date": f"2026-02-{d:02d}", "nav": 100.0} for d in range(1, 21)]
        pages = {1: page1, 2: page2}

        def _get(url, params=None, **kwargs):
            return _lsjz_response(pages[params["pageIndex"]])

        with patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep") as fake_sleep:
            rows = ump.fetch_nav_rows_lsjz("511880", pages=2)
        self.assertEqual(len(rows), 40)
        self.assertEqual(fake_sleep.call_count, 1)  # 请求数−1

    def test_lsjz_invalid_row_page_still_advances(self) -> None:
        # F10/M037：页内 1 行无效（DWJZ 空）+1 行新鲜 → 不中断翻页
        page1 = [{"date": "2026-01-05", "nav": None},
                 {"date": "2026-01-06", "nav": 100.0}]
        page2 = [{"date": "2026-01-07", "nav": 100.0}]
        pages = {1: page1, 2: page2}
        calls: list[int] = []

        def _get(url, params=None, **kwargs):
            calls.append(params["pageIndex"])
            return _lsjz_response(pages[params["pageIndex"]])

        with patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            rows = ump.fetch_nav_rows_lsjz("511880", pages=2)
        self.assertEqual(calls, [1, 2])  # 无效行不中断翻页、新鲜页照翻
        self.assertEqual([r["date"] for r in rows], ["2026-01-06", "2026-01-07"])

    def test_pingzhong_zero_in_window_falls_to_lsjz(self) -> None:
        # F11/M041/M084：pingzhong 返回全在窗前 → 落到 lsjz 且 source=实际源；
        # 降级链顺序=pingzhongdata 先行（首请求 URL 断言）。注意 pingzhong
        # 夹具日期由 offset 时间戳生成——窗前 720 日=2024 年
        old_rows = [{"date": "2024-01-08", "nav": 101.0}]
        urls: list[str] = []

        def _get(url, **kwargs):
            urls.append(url)
            if "pingzhongdata" in url:
                return _pingzhong_response(old_rows, day_offsets=[-720])
            return _lsjz_response(NAVS_880)

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars",
                      return_value=CLOSES_880), \
                patch("update_money_etf_premium.requests.get", side_effect=_get), \
                patch("update_money_etf_premium.time.sleep"):
            stats = ump.update_511880(Path(tmp), days=30)
        self.assertIn("pingzhongdata", urls[0])
        self.assertEqual(stats["source"], "lsjz+mootdx")
        self.assertEqual(stats["imported"], 3)

    def test_nav_nonpositive_rows_filtered_both_sources(self) -> None:
        # F12/M029/M039：nav=0/负/inf 行两侧取数层过滤，不产出毒行不抛
        rows = [{"date": "2025-12-29", "nav": 101.1966},
                {"date": "2025-12-30", "nav": 0.0},
                {"date": "2025-12-31", "nav": -1.0}]
        with patch("update_money_etf_premium.requests.get",
                   return_value=_pingzhong_response(rows)), \
                patch("update_money_etf_premium.time.sleep"):
            got = ump.fetch_nav_rows_pingzhong("511880")
        self.assertEqual([r["date"] for r in got], ["2025-12-29"])
        # pingzhong 的 inf：y=inf 行也须滤（A-M6）
        rows_inf = [{"date": "2025-12-29", "nav": 101.1966},
                    {"date": "2025-12-30", "nav": float("inf")}]
        with patch("update_money_etf_premium.requests.get",
                   return_value=_pingzhong_response(rows_inf)), \
                patch("update_money_etf_premium.time.sleep"):
            got = ump.fetch_nav_rows_pingzhong("511880")
        self.assertEqual([r["date"] for r in got], ["2025-12-29"])
        # lsjz 侧：DWJZ="NaN" → float("nan") 过滤（nan<=0 为 False，原穿透）
        with patch("update_money_etf_premium.requests.get",
                   return_value=_lsjz_response(
                       [{"date": "2025-12-29", "nav": 101.1966},
                        {"date": "2025-12-30", "nav": float("nan")}])), \
                patch("update_money_etf_premium.time.sleep"):
            got = ump.fetch_nav_rows_lsjz("511880", pages=1)
        self.assertEqual([r["date"] for r in got], ["2025-12-29"])


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

    def test_trigger_with_history_and_990_ahead(self) -> None:
        # B-I1 生产形态（M105/M106/M111 同形态）：880 有更早历史（1 行 exdiv
        # 修复行 + 1 行非越线），末 2 行双双越线；990 多一行 11-27（超前一日）。
        # 锁三处读取范围：rows_880 tail=CONSEC_DAYS（历史混入→触发不亮）、
        # rows_990 tail=CONSEC_DAYS+2（砍半→对齐缺行）、exdiv_recent 只扫窗内
        # （扫全史→历史 exdiv 行永久静默）。
        st = self._state(
            [("2026-11-20", -0.5, "close=1 nav=2 exdiv-repair"),
             ("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-24", -1.0, ), ("2026-11-25", -6.5, ),
             ("2026-11-26", -8.0, ), ("2026-11-27", -9.0, )])
        self.assertTrue(st["triggered"])
        self.assertFalse(st["silent"])
        self.assertEqual(len(st["rows_880"]), 2)
        self.assertEqual(st["asof"], "2026-11-26")  # B-I2：990 超前不夺锚（M108）

    def test_990_only_two_old_rows_missing_reason(self) -> None:
        # B-I1 负例：990 仅 2 行且早于 880 窗 → 对齐缺行显式，不硬比
        st = self._state(
            [("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-20", -6.0, ), ("2026-11-21", -7.0, )])
        self.assertFalse(st["triggered"])
        self.assertIn("缺行", st["reason"])

    def test_trigger_window_gap_missing_rows_no_trigger(self) -> None:
        # K6：末 2 行跨缺行拼接（11-05→11-27，gap 22 日 >14）不判触发，落 missing
        st = self._state(
            [("2026-11-05", -7.0, ""), ("2026-11-27", -7.0, "")],
            [("2026-11-05", -7.0, ), ("2026-11-27", -7.0, )])
        self.assertFalse(st["triggered"])
        self.assertFalse(st["sample_ok"])
        self.assertIn("不连续", st["reason"])
        self.assertIn("missing", ump.classify_state(st))

    def test_trigger_window_gap_fourteen_days_still_consecutive(self) -> None:
        # K6 边界：连续交易日日历 gap 实测最长 11 天（春节+周末）——阈值 14 之
        # 内不判缺行（恰 14 gap 双越线仍可触发）
        st = self._state(
            [("2026-11-12", -7.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-12", -7.0, ), ("2026-11-26", -7.0, )])
        self.assertTrue(st["triggered"])
        self.assertNotIn("不连续", st["reason"])

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
        # B-M2：夹具用字面量构造 exdiv-repair note（PAT-05 防线——原引用
        # ump.EXDIV_MARK，改常量时夹具跟着漂、对拍组照绿）
        st = self._state(
            [("2026-11-25", -6.0, "close=1 nav=2 exdiv-repair"),
             ("2026-11-26", -7.0, "")],
            [("2026-11-25", -6.0, ), ("2026-11-26", -7.0, )])
        self.assertFalse(st["triggered"])
        self.assertTrue(st["silent"])
        self.assertIn("除权窗静默", st["reason"])

    def test_align_base_is_511880_not_latest(self) -> None:
        # 511990（100 锚）天然比 511880（净值 T+1）超前一日：对齐基准=511880
        # 末 2 日期，511990 同日期缺行 → 显式缺行理由（A-M2：sample_ok=False
        # 落 missing，非「未触发」），而非拿超前行硬比。
        st = self._state(
            [("2026-11-25", -6.0, ""), ("2026-11-26", -7.0, "")],
            [("2026-11-24", -6.0, ), ("2026-11-25", -7.0, ), ("2026-11-27", -9.0, )])
        self.assertFalse(st["triggered"])
        self.assertIn("2026-11-26", st["reason"])  # 511990 缺 11-26 行
        self.assertFalse(st["sample_ok"])
        self.assertIn("missing", ump.classify_state(st))

    def test_empty_880_fallback_reason_visible(self) -> None:
        # M9：主序列空时 asof 回退 990 日期须显式标注，不得被读成正常态
        st = self._state([], [("2026-11-26", 0.4, )])
        self.assertEqual(st["asof"], "2026-11-26")
        self.assertIn("511880 序列空", st["reason"])
        self.assertFalse(st["sample_ok"])
        self.assertIn("missing", ump.classify_state(st))

    def test_single_row_insufficient_not_triggered(self) -> None:
        # F15/M112/M113：880 仅 1 行=样本不足，不触发且落 missing
        st = self._state([("2026-11-26", -7.0, "")], [("2026-11-26", -7.0, )])
        self.assertFalse(st["triggered"])
        self.assertFalse(st["sample_ok"])
        self.assertIn("missing", ump.classify_state(st))

    def test_index_and_shibor_context_aligned_to_asof(self) -> None:
        # C2 修根回归：语境锚=asof（11-26）当日行与前一行。夹具特意放进
        # 11-27 的 +3.73% / +1.0bp（原实现会错拿它们标注 11-26 读数），
        # 修根后必须被忽略。B-I2：990 多一行 11-27（两序列末行日期不同）
        # ——asof 锚的锁：取 990 末行的变异（M108）在此红（asof=11-27 会
        # 吃到 11-27 语境、标签翻转 risk-on）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, ),
                 ("2026-11-27", 2.5, )])
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

    def test_index_single_row_in_window_is_none(self) -> None:
        # F14/M087：窗内仅 1 行（行数 <2）→ 语境缺 None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-11-26", "close": 3477.23}) + "\n",
                encoding="utf-8")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertIsNone(st["index"])

    def test_index_bad_close_value_is_none(self) -> None:
        # F14/M091/M094：close 非数值 → 计算异常 → 语境缺 None，不炸
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-25", 1.0, ""), ("2026-11-26", 2.0, "")],
                [("2026-11-25", 1.0, ), ("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-11-25", "close": "x"}) + "\n" +
                json.dumps({"date": "2026-11-26", "close": 3477.23}) + "\n",
                encoding="utf-8")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertIsNone(st["index"])

    def test_index_context_stale_beyond_gate_is_none(self) -> None:
        # A-M9：语境序列缺 asof 行且末行距 asof 超 CONTEXT_MAX_STALE_DAYS →
        # 语境缺（旧行不得照贴新标签，PAT-02 的闸）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(
                root,
                [("2026-11-26", 1.0, "")],
                [("2026-11-26", 2.0, )])
            idx_dir = root / "index" / "series"
            idx_dir.mkdir(parents=True)
            (idx_dir / "000001.jsonl").write_text(
                json.dumps({"date": "2026-10-10", "close": 3400.0}) + "\n" +
                json.dumps({"date": "2026-10-11", "close": 3410.0}) + "\n",
                encoding="utf-8")
            st = ump.money_etf_state(root, today="2026-11-27")
        self.assertIsNone(st["index"])


class ClassifyTests(unittest.TestCase):
    def _state(self, *, triggered=True, index=None, shibor=None, reason="",
               silent=False, sample_ok=True):
        return {"triggered": triggered, "silent": silent, "reason": reason,
                "sample_ok": sample_ok,
                "index": index, "shibor": shibor,
                "rows_880": [], "rows_990": [], "n_rows_880": 2,
                "asof": "2026-11-26", "today": "2026-11-27",
                "poisoned_recent": []}

    def test_risk_off_label(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": -1.2},
            shibor={"date": "2026-11-25", "value_pct": 1.5, "chg_bp": 4.0}))
        self.assertIn("risk-off", text)
        self.assertIn("非做多", text)
        # B-M5：两源日期不同（注释自称「Shibor 日期入标注行」须真锁得住——
        # 原夹具两日期同为 11-26，删 Shibor 日期仍绿）
        self.assertIn("2026-11-26", text)
        self.assertIn("2026-11-25", text)

    def test_risk_on_label(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 1.1},
            shibor={"date": "2026-11-25", "value_pct": 1.4, "chg_bp": 0.5}))
        self.assertIn("risk-on", text)

    def test_unknown_direction(self) -> None:
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 0.2}, shibor=None))
        self.assertIn("方向不明", text)
        self.assertIn("Shibor 读数缺", text)  # F14/M138：缺 Shibor 不炸渲染路径

    def test_normal_when_not_triggered(self) -> None:
        text = ump.classify_state(self._state(triggered=False))
        self.assertIn("正常噪声区间", text)
        self.assertIn("连续2日<-5bp", text)  # 文案由常量拼装（M10）

    def test_silent_line(self) -> None:
        text = ump.classify_state(self._state(triggered=False, silent=True,
                                              reason="除权窗静默"))
        self.assertIn("静默", text)

    def test_sample_insufficient_is_missing_not_not_triggered(self) -> None:
        # M13+A-M2：「没查成」按 object-model 词表落 missing，不冒充「未触发」；
        # 归类吃 sample_ok 结构化字段（reason 子串耦合的变异 M112/M113 在此红）
        text = ump.classify_state(self._state(triggered=False, sample_ok=False,
                                              reason="样本不足（511880 行数 <2）"))
        self.assertIn("missing", text)
        self.assertNotIn("未触发", text)

    def test_plain_reason_with_sample_ok_is_not_triggered(self) -> None:
        # A-M2 反向：sample_ok=True 的普通 reason（单基金越线）仍是「未触发」
        text = ump.classify_state(self._state(triggered=False,
                                              reason="单基金越线（不同向），未触发"))
        self.assertIn("未触发", text)
        self.assertNotIn("missing", text)

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

    def test_below_both_risk_on_thresholds_unknown(self) -> None:
        # F16/M133：指数 +0.4%、Shibor +0.5bp 双双低于 risk-on 阈值 → 方向不明
        text = ump.classify_state(self._state(
            index={"date": "2026-11-26", "chg_pct": 0.4},
            shibor={"date": "2026-11-26", "value_pct": 1.4, "chg_bp": 0.5}))
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
            # B-M5：空毒行不重写文件（字节不变——「空写入静默清史」形态锁死）
            before = (root / ".state" / "money-etf-poison.json").read_bytes()
            ump._record_poison_sidecar(root, [], today="2026-11-27")
            self.assertEqual((root / ".state" / "money-etf-poison.json").read_bytes(),
                             before)
            self.assertEqual(len(ump._read_poison_sidecar(root, "2026-11-27")), 1)

    def test_sidecar_dedup_by_series_and_date(self) -> None:
        # A-M1：同 (series,date) 弃行重入去重——原每轮追加滚成「近期弃行 54 条」
        p = {"date": "2026-11-26", "prem_bp": -365.3,
             "series": ump.PREM_511880_SERIES, "reason": "口径断裂"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for _ in range(4):
                ump._record_poison_sidecar(root, [p], today="2026-11-27")
            recent = ump._read_poison_sidecar(root, today="2026-11-27")
        self.assertEqual(len(recent), 1)

    def test_sidecar_missing_or_corrupt_reads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])
            (root / ".state").mkdir()
            (root / ".state" / "money-etf-poison.json").write_text("not-json", "utf-8")
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])

    def test_sidecar_bad_shapes_read_empty(self) -> None:
        # F13/M097-M101：非 list JSON / 条目 recorded_at 非字符串 → 读回 [] 或过滤
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".state").mkdir()
            path = root / ".state" / "money-etf-poison.json"
            path.write_text(json.dumps({"a": 1}), "utf-8")
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])
            path.write_text(json.dumps([5, {"series": "s", "date": "2026-11-26",
                                            "recorded_at": 123}]), "utf-8")
            self.assertEqual(ump._read_poison_sidecar(root, "2026-11-27"), [])

    def test_sidecar_write_oserror_logs_not_raises(self) -> None:
        # F13/M100：写失败（含 A-I2 原子写 tmp 侧）只 log 不抛
        with tempfile.TemporaryDirectory() as tmp, \
                patch("pathlib.Path.write_text", side_effect=OSError("disk full")), \
                patch("update_money_etf_premium.log") as fake_log:
            ump._record_poison_sidecar(
                Path(tmp), [{"date": "2026-11-26", "prem_bp": -365.3,
                             "series": ump.PREM_511880_SERIES,
                             "reason": "口径断裂"}], today="2026-11-27")
        self.assertTrue(any("sidecar" in str(c.args) for c in fake_log.call_args_list))

    def test_sidecar_corrupt_file_plus_new_poison_survives(self) -> None:
        # A-I2：坏 JSON 文件 + 本轮有毒行 → 坏文件当空重写，不再穿出 main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".state").mkdir()
            (root / ".state" / "money-etf-poison.json").write_text('{"a":', "utf-8")
            ump._record_poison_sidecar(
                root, [{"date": "2026-11-26", "prem_bp": -365.3,
                        "series": ump.PREM_511880_SERIES,
                        "reason": "口径断裂"}], today="2026-11-27")
            recent = ump._read_poison_sidecar(root, today="2026-11-27")
        self.assertEqual(len(recent), 1)


class ConstantLiteralLockTests(unittest.TestCase):
    """自引用夹具族防线（B-M-B1，第 4 案）：夹具与断言一律用字面量，关键
    常量在此与字面量对拍——常量被误改时本组先红，而非让夹具跟着常量漂。"""

    def test_key_constants_locked_by_literals(self) -> None:
        self.assertEqual(ump.ALERT_THRESH_BP, -5.0)
        self.assertEqual(ump.CONSEC_DAYS, 2)
        self.assertEqual(ump.POISON_PREM_BP, 200.0)
        self.assertEqual(ump.REPAIR_FAIL_POISON_BP, 30.0)   # A-I1 修复行收紧
        self.assertEqual(ump.EXDIV_ADJUST_WINDOW, 2)        # A-I1 F-D 调整窗
        self.assertEqual(ump.TRIGGER_MAX_DAY_GAP, 14)       # K6 相邻交易日闸
        self.assertEqual(ump.CONTEXT_MAX_STALE_DAYS, 10)    # A-M9 语境陈旧闸
        self.assertEqual(ump.EXDIV_MARK, "exdiv-repair")
        self.assertEqual(ump.EXDIV_MIN_DROP_RATIO, 0.0005)
        self.assertEqual(ump.BASELINE_P5_BP, -0.8)
        self.assertEqual(ump.BASELINE_P95_BP, 2.8)
        self.assertEqual(ump.STALE_GAP_DAYS, 10)
        self.assertEqual(ump.PREM_511880_SERIES, "cn-money-etf-prem-511880")
        self.assertEqual(ump.PREM_511990_SERIES, "cn-money-etf-prem-511990")
        self.assertEqual(ump.NAV_511990_ANCHOR, 100.0)
        # F18/M019：标的代码与展示名常量（原不在对拍组、无兜底——B-M2）
        self.assertEqual(ump.FUND_511880, "511880")
        self.assertEqual(ump.FUND_511990, "511990")
        self.assertEqual(ump.NAME_511880,
                         "银华日利ETF(511880)场内溢价率（bp，vs 单位净值）")
        self.assertEqual(ump.NAME_511990,
                         "华宝添益ETF(511990)场内溢价率（bp，vs 100元固定净值锚）")


class LedgerKindContractTests(unittest.TestCase):
    """接线契约：batch-money-etf 必须在 run_archive kind 白名单（同
    batch-us-liquidity 2026-11-22 判例：不在则 open 被 sentinel 吞掉）。"""

    def test_kind_whitelisted(self) -> None:
        import batch_ledger
        run_archive = batch_ledger._load_run_archive()
        self.assertIn("batch-money-etf", run_archive.KINDS)


class PersistedValueTests(unittest.TestCase):
    """B-I4：落盘值端到端（M071/M042 同点）——update 层桩跑完后读回序列，
    断言 value/source/unit/note 与字面量逐位相等。常量对拍组只锁「值」，
    本组锁「使用点」：fixed_nav 用点改字面 100.02（对拍组照绿的洞）在此红。"""

    def test_511990_persisted_value_literal(self) -> None:
        closes = [{"date": "2026-01-05", "close": 100.010}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("update_money_etf_premium._mootdx_bars",
                       return_value=closes):
                ump.update_511990(root, days=30)
            rows = ump._read_series(root, ump.PREM_511990_SERIES, tail=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 1.0)  # 100.010/100−1=+1.0bp（×100 变异落 100.0）
        self.assertEqual(rows[0]["unit"], "bp")
        self.assertEqual(rows[0]["source"], "mootdx+nav100anchor")
        self.assertIn("close=100.0100 nav=100.0000", rows[0]["note"])

    def test_511880_persisted_value_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("update_money_etf_premium._mootdx_bars",
                       return_value=CLOSES_880), \
                    patch("update_money_etf_premium.requests.get",
                          return_value=_pingzhong_response(NAVS_880)), \
                    patch("update_money_etf_premium.time.sleep"):
                ump.update_511880(root, days=30)
            rows = ump._read_series(root, ump.PREM_511880_SERIES, tail=5)
        self.assertEqual(rows[0]["value"], -0.16)   # 101.195/101.1966
        self.assertEqual(rows[1]["value"], -0.45)   # 修复行（前值对价）
        self.assertEqual(rows[2]["value"], 1.69)
        self.assertIn("exdiv-repair", rows[1]["note"])
        self.assertEqual(rows[0]["source"], "pingzhongdata+mootdx")


class ReportIntegrationTests(unittest.TestCase):
    """B-I3：today / recorded_at 端到端（M018/M123/M175/M210 同点）——
    state["today"]=None、_today_iso 回 1970 型变异原全量绿。"""

    def test_render_through_real_state_shows_stale(self) -> None:
        # today 经 generate_daily_report 真实传链（gdr date.today() →
        # money_etf_state(today=...) → 陈旧提示）；夹具 asof 固定在过去，
        # 与真实墙钟的日历 gap 恒 >10 日（测试自身不埋时间炸弹）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_state_fixture(root,
                                 [("2026-11-01", 0.1, "")],
                                 [("2026-11-01", 0.2, )])
            import generate_daily_report as gdr
            text = gdr.render_money_etf_section(data_root=root)
        self.assertIn("货币ETF场内折溢价", text)   # 真渲染（降级行无「场内」）
        self.assertIn("序列陈旧", text)

    def test_sidecar_readable_next_day_after_main_run(self) -> None:
        # recorded_at 经 main() 真实落痕后「当日/15 日后」读——_today_iso 恒
        # 1970 型变异在此红（原码当日 1 条/变异 0 条）
        closes = list(CLOSES_880) + [{"date": "2026-01-05", "close": 97.50}]
        navs = NAVS_880 + [{"date": "2026-01-05", "nav": 100.0}]
        from datetime import date as _date, timedelta as _td
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars",
                      side_effect=lambda code, offset:
                          closes if code == "511880" else CLOSES_990), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(
                          navs, day_offsets=[0, 1, 2, 7])), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 0)
            self.assertEqual(
                len(ump._read_poison_sidecar(Path(tmp), today=ump._today_iso())), 1)
            later = (_date.today() + _td(days=15)).isoformat()
            self.assertEqual(ump._read_poison_sidecar(Path(tmp), today=later), [])


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

        def _no_net(url, **kwargs):
            raise _rq.ConnectionError("guard: 测试封闭面（B-M6）")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get", side_effect=_no_net), \
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
        # B-I8②/M164：第二腿失败在 data-close missing 留痕（原只断言退出码，
        # 删 :615 的 missing.append 变异全量绿）；A-M2：reason 带补数命令
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
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
        closes = [r for r in rows if r.get("type") == "data-close"]
        self.assertEqual([m["item"] for m in closes[0]["missing"]],
                         [ump.PREM_511990_SERIES])
        self.assertIn("补数", closes[0]["missing"][0]["reason"])

    def test_nav_missing_log_splits_t1_vs_stale(self) -> None:
        # B-I8①+A-M3：缺净值行可见性（删 warn 日志的变异 M069 在此红）+
        # 文案三分（最新交易日=T+1 常态用 Info、更早日期=停披用 Warning）
        import update_money_etf_premium as ump_mod
        closes = list(CLOSES_880) + [
            {"date": "2026-01-05", "close": 100.05},
            {"date": "2026-01-06", "close": 100.06}]
        def bars(code, offset):
            return closes if code == "511880" else CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(NAVS_880)), \
                patch("update_money_etf_premium.log") as fake_log, \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump_mod.main(["--days", "30"]), 0)
        texts = [str(c.args) for c in fake_log.call_args_list]
        self.assertTrue(any("停披" in t and "2026-01-05" in t for t in texts),
                        texts)
        self.assertTrue(any("T+1 常态" in t and "2026-01-06" in t for t in texts),
                        texts)

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

    def test_poison_visible_even_when_leg_fails_midway(self) -> None:
        # A-M8：腿内中途异常时，compute 已发现的毒行仍进 missing+sidecar
        # （原实现 stats 随异常丢失，毒行只剩日志）
        real_upsert = ump.upsert_premiums
        closes = list(CLOSES_880) + [{"date": "2026-01-05", "close": 97.50}]
        navs = NAVS_880 + [{"date": "2026-01-05", "nav": 100.0}]

        def flaky_upsert(data_root, series, name, source, rows, sink=None):
            real_upsert(data_root, series=series, name=name, source=source,
                        rows=rows[:1], sink=sink)
            raise RuntimeError("mid-leg boom")

        def bars(code, offset):
            return closes if code == "511880" else CLOSES_990

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_money_etf_premium._mootdx_bars", side_effect=bars), \
                patch("update_money_etf_premium.requests.get",
                      return_value=_pingzhong_response(
                          navs, day_offsets=[0, 1, 2, 7])), \
                patch("update_money_etf_premium.upsert_premiums",
                      side_effect=flaky_upsert), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            self.assertEqual(ump.main(["--days", "30"]), 1)
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
            sidecar = json.loads(
                (Path(tmp) / ".state" / "money-etf-poison.json")
                .read_text(encoding="utf-8"))
        missing = rows[-1]["missing"]
        self.assertTrue(any("毒行弃用" in m["reason"] for m in missing), missing)
        self.assertEqual(sidecar[0]["date"], "2026-01-05")


if __name__ == "__main__":
    unittest.main()
