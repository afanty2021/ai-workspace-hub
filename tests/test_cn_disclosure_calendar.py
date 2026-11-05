"""A 股预约披露日历（东财 datacenter RPT_PUBLIC_BS_APPOIN）单元测试。

全封闭不联网：payload 解析、watchlist 交集、已披露/待披露分表、降级契约、
状态合并、渲染器两路源统一表。2026-11-05 接入（FMP 只覆盖美股且要 Key，
tushare disclosure_date 120 积分档实测全零行）。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

import fetch_market_data as fmd  # noqa: E402
import generate_daily_report as gdr  # noqa: E402

WATCHLIST_MAP = {
    "300476.SZ": {"name": "胜宏科技", "market": "CN", "category": "PCB"},
    "600276.SH": {"name": "恒瑞医药", "market": "CN", "category": "医药-创新药"},
    "NVDA": {"name": "英伟达", "market": "US", "category": "半导体-AI"},
}


def _dc_payload(rows: list[dict]) -> dict:
    return {"version": "x", "success": True,
            "result": {"pages": 1, "count": len(rows), "data": rows}}


def _row(code: str, name: str, appoint: str, actual: str | None,
         report_date: str = "2026-09-30", type_name: str = "2026年 三季报") -> dict:
    return {
        "SECURITY_CODE": code, "SECURITY_NAME_ABBR": name,
        "REPORT_DATE": f"{report_date} 00:00:00",
        "APPOINT_PUBLISH_DATE": f"{appoint} 00:00:00",
        "ACTUAL_PUBLISH_DATE": f"{actual} 00:00:00" if actual else None,
        "REPORT_TYPE_NAME": type_name, "IS_PUBLISH": "1" if actual else "0",
    }


class FetchCnDisclosureCalendarTests(unittest.TestCase):
    def test_parses_rows_intersects_watchlist_and_splits_disclosed(self) -> None:
        payload = _dc_payload([
            _row("300476", "胜宏科技", "2026-10-30", "2026-10-30"),
            _row("600276", "恒瑞医药", "2026-11-20", None),
            _row("000001", "平安银行", "2026-11-15", None),  # 不在池内，应剔除
        ])
        with patch.object(fmd.requests, "get") as mock_get:
            mock_get.return_value.json.return_value = payload
            rows = fmd.fetch_cn_disclosure_calendar(
                WATCHLIST_MAP, today=date(2026, 11, 5))

        self.assertEqual([r["ticker"] for r in rows], ["300476.SZ", "600276.SH"])
        disclosed, upcoming = rows[0], rows[1]
        self.assertTrue(disclosed["isPublished"])
        self.assertEqual(disclosed["actualDate"], "2026-10-30")
        self.assertEqual(disclosed["date"], "2026-10-30")
        self.assertFalse(upcoming["isPublished"])
        self.assertEqual(upcoming["appointDate"], "2026-11-20")
        self.assertEqual(upcoming["date"], "2026-11-20")
        self.assertEqual(upcoming["daysUntil"], 15)
        self.assertEqual(upcoming["name"], "恒瑞医药")

    def test_sh_suffix_for_sh_exchange_codes(self) -> None:
        payload = _dc_payload([_row("600276", "恒瑞医药", "2026-11-20", None)])
        with patch.object(fmd.requests, "get") as mock_get:
            mock_get.return_value.json.return_value = payload
            rows = fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, today=date(2026, 11, 5))
        self.assertEqual(rows[0]["ticker"], "600276.SH")

    def test_status_ok_with_window(self) -> None:
        status: dict = {}
        with patch.object(fmd.requests, "get") as mock_get:
            mock_get.return_value.json.return_value = _dc_payload([])
            fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, status, today=date(2026, 11, 5))
        self.assertEqual(status["state"], "ok")
        self.assertEqual(status["source"], "eastmoney-disclosure")
        self.assertEqual(status["period_start"], "2026-09-26")
        self.assertEqual(status["period_end"], "2026-12-10")

    def test_http_failure_degrades_to_empty_and_failed_status(self) -> None:
        status: dict = {}
        with patch.object(fmd.requests, "get", side_effect=ConnectionError("反爬断连")):
            rows = fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, status, today=date(2026, 11, 5))
        self.assertEqual(rows, [])
        self.assertEqual(status["state"], "failed")

    def test_transient_drop_retries_once(self) -> None:
        # 东财偶发空响应（反爬抖动）：第一次失败第二次成功应拿到数据
        good = type("R", (), {"raise_for_status": staticmethod(lambda: None),
                              "json": staticmethod(lambda: _dc_payload([]))})()
        with patch.object(fmd.requests, "get",
                          side_effect=[ConnectionError("drop"), good]) as mock_get:
            with patch.object(fmd.time, "sleep"):
                rows = fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, today=date(2026, 11, 5))
        self.assertEqual(rows, [])
        self.assertEqual(mock_get.call_count, 2)

    def test_failure_payload_returns_empty(self) -> None:
        with patch.object(fmd.requests, "get") as mock_get:
            mock_get.return_value.json.return_value = {"success": False, "message": "x"}
            rows = fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, today=date(2026, 11, 5))
        self.assertEqual(rows, [])

    def test_malformed_dates_skip_row_not_whole_batch(self) -> None:
        # 评审 #3：非 ISO / 形合法但无效的日期只跳过该行，好行照常返回。
        # 坏行必须用池内票：池外票在票池交集处就被剔除，永远走不到日期
        # 解析的 except 防线（复查 N-4 测试盲区的修根）
        payload = _dc_payload([
            _row("300476", "胜宏科技", "2026-10-30", "2026-10-30"),
            _row("600276", "恒瑞医药", "2026/11/20", None),   # 非 ISO 分隔符
            _row("300476", "胜宏科技", "2026-13-99", None),   # 形合法但无效月日（池内票）
        ])
        with patch.object(fmd.requests, "get") as mock_get:
            mock_get.return_value.json.return_value = payload
            rows = fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, today=date(2026, 11, 5))
        self.assertEqual([r["ticker"] for r in rows], ["300476.SZ"])

    def test_pages_gt_one_logs_truncation_warning(self) -> None:
        # 评审 #4：pageSize=100 单页，pages>1 时最旧行被静默截断——必须有告警
        payload = _dc_payload([])
        payload["result"]["pages"] = 3
        with patch.object(fmd.requests, "get") as mock_get, \
             patch.object(fmd, "log") as mock_log:
            mock_get.return_value.json.return_value = payload
            fmd.fetch_cn_disclosure_calendar(WATCHLIST_MAP, today=date(2026, 11, 5))
        self.assertTrue(any("pages" in str(c.args[0]) for c in mock_log.call_args_list))


class SignalGateAndMarkerTests(unittest.TestCase):
    """评审 #2 双管齐下：marker 事件日幂等 + 事件级闸门（渲染不受影响）。"""

    HYPOTHESES = [{"id": "H1", "title": "AI PCB", "tickers": ["300476.SZ"]}]

    def test_marker_uses_event_date_for_earnings(self) -> None:
        signal = {"signal_type": "earnings", "ref": "300476.SZ",
                  "hypothesis_id": "H1", "event_date": "2026-10-30"}
        # 报告日不同、事件日相同 → marker 相同（跨日幂等）
        self.assertEqual(
            gdr.build_signal_marker("2026-11-05", signal),
            gdr.build_signal_marker("2026-11-06", signal))
        self.assertEqual(
            gdr.build_signal_marker("2026-11-05", signal),
            "DW-2026-10-30-earnings-300476-sz-h1")

    def test_marker_without_event_date_keeps_report_date(self) -> None:
        # 其他信号类型 / 旧条目格式不受影响
        signal = {"signal_type": "mover", "ref": "300476.SZ", "hypothesis_id": "H1"}
        self.assertEqual(
            gdr.build_signal_marker("2026-11-05", signal),
            "DW-2026-11-05-mover-300476-sz-h1")

    def _collect(self, earning: dict) -> list[dict]:
        # today 固定注入：闸门距今天数不能依赖真实日历（复查 N-1 时间炸弹）
        return gdr.collect_hypothesis_signals(
            self.HYPOTHESES, {}, [],
            [dict(earning, ticker="300476.SZ", source="eastmoney-disclosure",
                  name="胜宏科技", market="CN", category="PCB")],
            today=date(2026, 11, 5))

    def test_far_future_appointment_excluded_from_signals(self) -> None:
        earning = {"reportTypeName": "2026年 年报", "appointDate": "2026-12-05",
                   "actualDate": None, "daysUntil": 30}
        self.assertEqual(self._collect(earning), [])

    def test_near_appointment_and_recent_actual_included(self) -> None:
        near = {"reportTypeName": "2026年 年报", "appointDate": "2026-11-08",
                "actualDate": None, "daysUntil": 3}
        recent = {"reportTypeName": "2026年 三季报", "appointDate": "2026-11-01",
                  "actualDate": "2026-11-03", "daysUntil": -4}
        for earning in (near, recent):
            signals = self._collect(earning)
            self.assertEqual(len(signals), 1, earning)
            # 事件日进 signal，marker 幂等的上游
            self.assertEqual(signals[0]["event_date"],
                             earning["actualDate"] or earning["appointDate"])

    def test_future_actual_date_rejected(self) -> None:
        # 复查 N-3：actualDate 晚于今天是脏数据（未来不可能已披露）。
        # 漏洞窗口是「未来 0~7 天」——更远的未来连 abs 版都会被 days 上限
        # 拦住，测不出方向性；用 +3 天才有区分度
        future = {"reportTypeName": "2026年 三季报", "appointDate": "2026-10-01",
                  "actualDate": "2026-11-08", "daysUntil": -35}
        self.assertEqual(self._collect(future), [])
        self.assertFalse(gdr._within_days("2026-11-08", "2026-11-05", 7))
        self.assertTrue(   # 当天 / 过去 7 天内仍放行
            gdr._within_days("2026-11-05", "2026-11-05", 7))


class ApplyWritebackDedupTests(unittest.TestCase):
    """复查 N-1/N-2 链路级验收：同一财报事件跨两个报告日，时间线条目与
    证据文件都只落一次（marker 事件日幂等 + 去重判断先于证据写入）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.hyp_path = self.root / "hypothesis" / "H1.md"
        self.hyp_path.parent.mkdir(parents=True)
        self.hyp_path.write_text(
            "---\nid: H1\nstatus: active\n---\n\n# H1\n\n## 证据时间线\n",
            encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _signal() -> dict:
        # event_date 固定 = 财报事件日；报告日由 apply 的 date_text 决定
        return {"hypothesis_id": "H1", "signal_type": "earnings", "ref": "300476.SZ",
                "event_date": "2026-11-03", "summary": "胜宏科技三季报已披露",
                "auto_writeback": True, "market": "CN",
                "observed_trade_date": "2026-11-03"}

    def _apply(self, report_day: str) -> int:
        hypotheses = [{"id": "H1", "title": "AI PCB", "path": str(self.hyp_path),
                       "tickers": ["300476.SZ"]}]
        report_path = (self.root / "output" / "daily-watch" / "2026-11"
                       / f"{report_day}.md")
        return gdr.apply_hypothesis_updates(
            self.root, hypotheses, [self._signal()], report_path, report_day)

    def test_same_event_two_report_days_writes_once(self) -> None:
        first = self._apply("2026-11-05")
        second = self._apply("2026-11-06")
        self.assertEqual((first, second), (1, 0))
        # 证据文件只有一个（第一报告日创建；第二日 marker 命中不再新建）
        evidence_files = sorted(
            p.name for p in (self.root / "evidence").rglob("E-*.md"))
        self.assertEqual(len(evidence_files), 1, evidence_files)
        self.assertTrue(evidence_files[0].startswith("E-20261105-"))
        # 时间线 marker 只出现一次
        timeline = self.hyp_path.read_text(encoding="utf-8")
        self.assertEqual(
            timeline.count("DW-2026-11-03-earnings-300476-sz-h1"), 1)


class MergeEarningsStatusTests(unittest.TestCase):
    def test_ok_merge_carries_both_channels_windows(self) -> None:
        # 评审 #1：merge 曾把 period_start/period_end 一并 clear 丢掉，
        # 渲染端必现「未提供 至 未提供」——两通道窗口必须分开带出
        fmp_status: dict = {"state": "ok", "period_start": "2026-11-02",
                            "period_end": "2026-11-06"}
        cn_status: dict = {"state": "ok", "period_start": "2026-09-26",
                           "period_end": "2026-12-10"}
        fmd._merge_earnings_status([], fmp_status, cn_status)
        self.assertEqual(fmp_status["fmp_period_start"], "2026-11-02")
        self.assertEqual(fmp_status["fmp_period_end"], "2026-11-06")
        self.assertEqual(fmp_status["cn_period_start"], "2026-09-26")
        self.assertEqual(fmp_status["cn_period_end"], "2026-12-10")

    def test_renderer_shows_dual_windows_not_placeholder(self) -> None:
        meta = {"state": "ok", "sources": ["fmp", "eastmoney-disclosure"],
                "fmp_period_start": "2026-11-02", "fmp_period_end": "2026-11-06",
                "cn_period_start": "2026-09-26", "cn_period_end": "2026-12-10"}
        coverage = gdr.render_data_coverage(
            {"meta": {"quotes": {}, "earnings": meta}, "quotes": []}, {"meta": {}},
            {"earnings": True, "macro": False})
        self.assertIn("美股 2026-11-02 至 2026-11-06", coverage)
        self.assertIn("A 股 2026-09-26 至 2026-12-10", coverage)
        self.assertNotIn("未提供 至 未提供", coverage)

    def test_either_ok_means_ok(self) -> None:
        earnings = [{"source": "eastmoney-disclosure"}, {"source": "fmp"}]
        fmp_status: dict = {"state": "not_configured", "source": "fmp"}
        cn_status: dict = {"state": "ok", "source": "eastmoney-disclosure"}
        out = fmd._merge_earnings_status(earnings, fmp_status, cn_status)
        self.assertEqual(out, earnings)
        self.assertEqual(fmp_status["state"], "ok")
        self.assertEqual(fmp_status["sources"], ["eastmoney-disclosure"])

    def test_failed_beats_not_configured(self) -> None:
        fmp_status: dict = {"state": "not_configured", "source": "fmp"}
        cn_status: dict = {"state": "failed", "source": "eastmoney-disclosure"}
        fmd._merge_earnings_status([], fmp_status, cn_status)
        self.assertEqual(fmp_status["state"], "failed")
        self.assertEqual(fmp_status["sources"], [])

    def test_ok_status_records_sources_and_count(self) -> None:
        fmp_status: dict = {"state": "not_configured", "source": "fmp"}
        cn_status: dict = {"state": "ok", "source": "eastmoney-disclosure"}
        fmd._merge_earnings_status([{"source": "eastmoney-disclosure"}], fmp_status, cn_status)
        self.assertEqual(fmp_status["state"], "ok")
        self.assertEqual(fmp_status["sources"], ["eastmoney-disclosure"])
        self.assertEqual(fmp_status["cn_count"], 1)


class RenderEarningsSectionsTests(unittest.TestCase):
    def test_cn_rows_render_into_unified_tables(self) -> None:
        earnings = [
            {"ticker": "600276.SH", "name": "恒瑞医药", "source": "eastmoney-disclosure",
             "reportTypeName": "2026年 三季报", "reportDate": "2026-09-30",
             "appointDate": "2026-11-20", "actualDate": None, "daysUntil": 15},
            {"ticker": "300476.SZ", "name": "胜宏科技", "source": "eastmoney-disclosure",
             "reportTypeName": "2026年 三季报", "reportDate": "2026-09-30",
             "appointDate": "2026-10-30", "actualDate": "2026-10-29"},
        ]
        reported, upcoming = gdr.render_earnings_sections(
            earnings, True, {"state": "ok"})
        self.assertIn("| 300476.SZ | 胜宏科技 | 2026年 三季报 | 2026-10-29 | 预约 2026-10-30 |", reported)
        self.assertIn("| 600276.SH | 恒瑞医药 | 2026年 三季报 | 2026-11-20 | 距今 15 天 |", upcoming)

    def test_week_flag_for_soon_disclosure(self) -> None:
        earnings = [{"ticker": "600276.SH", "name": "恒瑞医药", "source": "eastmoney-disclosure",
                     "reportTypeName": "2026年 三季报", "appointDate": "2026-11-07",
                     "actualDate": None, "daysUntil": 2}]
        _, upcoming = gdr.render_earnings_sections(earnings, True, {"state": "ok"})
        self.assertIn("距今 2 天（本周）", upcoming)

    def test_fmp_eps_rows_keep_details_in_remark(self) -> None:
        earnings = [
            {"ticker": "NVDA", "name": "英伟达", "date": "2026-11-19",
             "eps": 1.25, "epsEstimated": 1.10},
            {"ticker": "AAPL", "name": "苹果", "date": "2026-11-20",
             "eps": None, "epsEstimated": 1.6},
        ]
        reported, upcoming = gdr.render_earnings_sections(earnings, True, {"state": "ok"})
        self.assertIn("EPS 实际 1.25 / 预期 1.1（surprise 0.15）", reported)
        self.assertIn("预期 EPS 1.6", upcoming)

    def test_status_fallback_text_unchanged(self) -> None:
        reported, _ = gdr.render_earnings_sections([], True, {"state": "not_configured"})
        self.assertEqual(reported, "> 未配置财报数据源，本轮未检查")
        reported, _ = gdr.render_earnings_sections([], True, {"state": "failed"})
        self.assertEqual(reported, "> 财报获取失败，不能判断是否有财报")


class MetaPayloadContractTests(unittest.TestCase):
    def test_collect_output_carries_earnings_key(self) -> None:
        # fetch 输出顶层结构契约：earnings 由渲染器与报告模板共同依赖
        source = (REPO_ROOT / "tools" / "daily-watch" / "scripts" / "fetch_market_data.py").read_text("utf-8")
        self.assertIn('"earnings": earnings,', source)
        self.assertIn("fetch_cn_disclosure_calendar", source)


if __name__ == "__main__":
    unittest.main()
