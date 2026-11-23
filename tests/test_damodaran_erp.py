"""update_damodaran_erp 单测（Q-20261123-05 达摩达兰隐含 ERP 月度通路）：全封闭不联网。

覆盖：xlsx 表头名定位解析（% 换算/note token/残缺行跳过/schema 漂移拒绝）、
幂等落盘+unit 标注、run_archive kind 白名单、main 失败非零+账本记源按实际写入、
erp_state 分位/陈旧标注（today 注入防时间炸弹）、日报段渲染降级。
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import _test_paths  # noqa: F401
import requests as _rq
import update_damodaran_erp as ude

# 模板占位符契约在 test_cross_asset_report.TemplateContractTests 断言 {ERP_SECTION}

_HEADERS = ["Start of month", "S&P 500", "T.Bond Rate", "$ Riskfree Rate",
            "Ten-year average CF", "CF (Trailing 12 month)", "Normalized CF",
            "Expected growth rate", "ERP (T12 m with sustainable payout)",
            "ERP (T12m)", "ERP (T12m) with adj riskfree rate", "ERP (Smoothed)",
            "ERP (Normalized)", "ERP (Net Cash Yield)", "ERP (Covid Adjusted)",
            "Expected Return", "Notes"]

# 2026-11-23 实拉真值锚（workbook 首尾两行）
_REAL_ROWS = [
    {"month": datetime(2026, 10, 1), "sp": 7652, "tb": 0.0529,
     "sust": 0.0420, "erp": 0.0370, "er": 0.0899},
    {"month": datetime(2026, 11, 1), "sp": 7580, "tb": 0.0494,
     "sust": 0.0441, "erp": 0.0379, "er": 0.0873},
]


def _workbook_bytes(rows: list[dict], sheet: str = "Historical ERP") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(_HEADERS)
    for r in rows:
        line: list = [None] * len(_HEADERS)
        line[0] = r["month"]
        line[1] = r.get("sp")
        line[2] = r.get("tb")
        line[8] = r.get("sust")
        line[9] = r.get("erp")
        line[15] = r.get("er")
        ws.append(line)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ParseTests(unittest.TestCase):
    def test_parse_header_map_and_pct_conversion(self) -> None:
        rows = ude.parse_erp_rows(_workbook_bytes(_REAL_ROWS))
        self.assertEqual([r["date"] for r in rows],
                         ["2026-10-01", "2026-11-01"])   # 正序
        self.assertEqual(rows[-1]["erp"], 3.79)           # 0.0379 ×100
        note = rows[-1]["note"]
        for token in ("SP=7580", "TB=4.94%", "sust=4.41%", "ER=8.73%"):
            self.assertIn(token, note)

    def test_parse_skips_incomplete_rows_and_omits_missing_tokens(self) -> None:
        rows = [{"month": datetime(2025, 12, 1),
                 "sp": 6900, "tb": 0.041, "erp": None}] + _REAL_ROWS + [
                {"month": datetime(2026, 12, 1), "sp": 7500, "tb": 0.048,
                 "erp": 0.0401}]  # sust/ER 缺 → 保留行但 token 省略
        parsed = ude.parse_erp_rows(_workbook_bytes(rows))
        self.assertEqual([r["date"] for r in parsed],
                         ["2026-10-01", "2026-11-01", "2026-12-01"])
        self.assertIn("sust=4.41%", parsed[-2]["note"])
        self.assertNotIn("sust", parsed[-1]["note"])   # 缺列 token 省略
        self.assertIn("TB=4.80%", parsed[-1]["note"])

    def test_missing_sheet_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            ude.parse_erp_rows(_workbook_bytes(_REAL_ROWS, sheet="Other"))

    def test_missing_erp_header_raises(self) -> None:
        # schema 漂移：同名表但缺 ERP (T12m) 表头 → 拒绝解析，不静默错位
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Historical ERP"
        ws.append(["Start of month", "S&P 500"])
        ws.append([datetime(2026, 11, 1), 7580])
        buf = io.BytesIO()
        wb.save(buf)
        with self.assertRaises(RuntimeError):
            ude.parse_erp_rows(buf.getvalue())


class UpdateTests(unittest.TestCase):
    def test_update_idempotent_and_unit_tag(self) -> None:
        payload = _workbook_bytes(_REAL_ROWS)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ude, "fetch_erp_workbook", return_value=payload):
            root = Path(tmp)
            first = ude.update_damodaran_erp(root)
            second = ude.update_damodaran_erp(root)
            rows = [line for line in
                    (root / "custom" / "us-erp-monthly.jsonl").read_text().splitlines()
                    if line.strip()]
        self.assertEqual(first["imported"], 2)
        self.assertEqual(second["imported"], 0)   # 同 (series,date) 幂等 skip
        self.assertEqual(second["skipped"], 2)
        self.assertIn('"unit": "%"', rows[-1])
        self.assertIn("damodaran-nyu-stern", rows[-1])


class KindContractTests(unittest.TestCase):
    """接线契约：batch-damodaran-erp 必须在 run_archive kind 白名单——不在则
    open 被 sentinel 降级吞掉，数据写入不进账本（batch-us-liquidity 同案先例）。"""

    def test_kind_whitelisted(self) -> None:
        import batch_ledger
        run_archive = batch_ledger._load_run_archive()  # 生产同款加载路径
        self.assertIn("batch-damodaran-erp", run_archive.KINDS)


class MainTests(unittest.TestCase):
    def test_main_nonzero_when_fetch_fails(self) -> None:
        def _get(url, **kwargs):
            raise _rq.ConnectionError("drop")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_damodaran_erp.requests.get", side_effect=_get), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            code = ude.main([])  # 显式空 argv（bare 调用会吃 pytest 参数）
            self.assertEqual(code, 1)  # 唯一载荷失败=非零（同 RRP 主系列语义）
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl").read_text().splitlines()
                    if line.strip()]
        close = [row for row in rows if row.get("type") == "data-close"][-1]
        self.assertEqual([m["item"] for m in close["missing"]], ["us-erp-monthly"])

    def test_main_records_source_only_on_write(self) -> None:
        payload = _workbook_bytes(_REAL_ROWS)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ude, "fetch_erp_workbook", return_value=payload), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            ude.main([])  # 首跑：写入 2 行（显式空 argv，bare 调用吃 pytest 参数）
            ude.main([])  # 重跑：全 skip
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl").read_text().splitlines()
                    if line.strip()]
        closes = [row for row in rows if row.get("type") == "data-close"]
        self.assertEqual(closes[0]["sources_used"], ["damodaran-nyu-stern"])
        self.assertEqual(closes[1]["sources_used"], [])  # 全 skip 不虚记源
        self.assertEqual(closes[1]["data_targets"], [])


class StateFormatTests(unittest.TestCase):
    def test_state_and_format_percentile_ok_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 24 个月历史（值 4.0~5.2 全高于 3.79）+ 1 个更低的旧月（3.70）
            months = [date(2024, 11, 1) + timedelta(days=30 * i)
                      for i in range(24)]
            from save_custom_data import append_record
            for i, day in enumerate(months):
                append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                              date=day.isoformat(), value=4.0 + i * 0.05,
                              unit="%", source="test")
            append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                          date="2025-06-01", value=3.70, unit="%", source="test")
            append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                          date="2026-11-01", value=3.79, unit="%", source="test",
                          note="SP=7580 TB=4.94% sust=4.41% ER=8.73%")
            state = ude.erp_state(root, today=date(2026, 11, 23))
            text = ude.format_erp_section(state)
        self.assertTrue(state["ok"])
        self.assertEqual(state["n_lower"], 1)
        self.assertIn("达摩达兰隐含 ERP（T12m）：3.79%", text)
        self.assertIn("2026-11-01 读数", text)
        self.assertIn("SP=7580 TB=4.94%", text)
        self.assertIn("中仅 1 个月更低", text)
        self.assertNotIn("检查通路", text)  # 22 天 < 45 天陈旧线

    def test_format_missing_series_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = ude.format_erp_section(ude.erp_state(Path(tmp)))
        self.assertIn("暂无本地读数", text)
        self.assertIn("update_damodaran_erp", text)

    def test_stale_reading_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            months = [date(2024, 5, 1) + timedelta(days=30 * i)
                      for i in range(28)]
            from save_custom_data import append_record
            for i, day in enumerate(months):
                append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                              date=day.isoformat(), value=4.5, unit="%",
                              source="test")
            state = ude.erp_state(root, today=date(2026, 11, 23))
            text = ude.format_erp_section(state)
        self.assertGreater(state["stale_days"], ude.STALE_DAYS)
        self.assertIn("天未更新", text)
        self.assertIn("检查通路", text)

    def test_small_series_omits_percentile_clause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from save_custom_data import append_record
            for i in range(3):
                append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                              date=(date(2026, 9, 1) + timedelta(days=30 * i)).isoformat(),
                              value=4.5, unit="%", source="test")
            text = ude.format_erp_section(ude.erp_state(root, today=date(2026, 11, 23)))
        self.assertNotIn("个月中仅", text)  # n<24 不谈分位


class ReportIntegrationTests(unittest.TestCase):
    def test_render_section_degrades_on_error(self) -> None:
        import generate_daily_report as gdr
        with patch("update_damodaran_erp.erp_state",
                   side_effect=RuntimeError("boom")):
            text = gdr.render_damodaran_erp_section(Path("/nonexistent"))
        self.assertIn("达摩达兰隐含 ERP 读数本轮渲染失败", text)
        self.assertIn("update_damodaran_erp.py", text)

    def test_render_section_ok_path(self) -> None:
        import generate_daily_report as gdr
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from save_custom_data import append_record
            append_record(root, series=ude.ERP_SERIES, name=ude.ERP_SERIES_NAME,
                          date="2026-11-01", value=3.79, unit="%",
                          source="damodaran-nyu-stern", note="SP=7580")
            text = gdr.render_damodaran_erp_section(root)
        self.assertIn("达摩达兰隐含 ERP（T12m）：3.79%", text)


if __name__ == "__main__":
    unittest.main()
