"""A 股预约披露日历（东财 datacenter RPT_PUBLIC_BS_APPOIN）单元测试。

全封闭不联网：payload 解析、watchlist 交集、已披露/待披露分表、降级契约、
状态合并、渲染器两路源统一表。2026-11-05 接入（FMP 只覆盖美股且要 Key，
tushare disclosure_date 120 积分档实测全零行）。
"""

from __future__ import annotations

import unittest
from datetime import date
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


class MergeEarningsStatusTests(unittest.TestCase):
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
