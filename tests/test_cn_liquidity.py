"""update_cn_liquidity 单测（Q-20261109-04 C3）：全封闭不联网。

覆盖：Shibor datacenter 解析（REPORT_DATE 截断/非数值行剔除/倒序转正序/重试）、
社融 MOFCOM 解析（YYYYMM 与 YYYY-MM 双格式/非数组响应拒绝）、append 幂等 skip。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import update_cn_liquidity as ucl
from save_custom_data import append_record


def _dc_response(rows: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"success": True, "result": {"data": rows, "pages": 1}}
    return mock


class ShiborTests(unittest.TestCase):
    @patch("update_cn_liquidity.requests.get",
           return_value=_dc_response([
               {"REPORT_DATE": "2026-11-06 00:00:00", "IR_RATE": 1.346},
               {"REPORT_DATE": "2026-11-05 00:00:00", "IR_RATE": 1.323},
               {"REPORT_DATE": None, "IR_RATE": 1.5},        # 缺日期剔除
               {"REPORT_DATE": "2026-11-04 00:00:00", "IR_RATE": "x"},  # 非数值剔除
           ]))
    def test_parse_and_reorder(self, mock_get) -> None:
        rows = ucl.fetch_shibor_rows("101")
        self.assertEqual([r["date"] for r in rows], ["2026-11-05", "2026-11-06"])
        self.assertEqual(rows[-1]["value"], 1.346)
        # filter 里嵌 indicator 码（URL 编码字面量，同财报日历拼接惯例）
        self.assertIn("INDICATOR_ID%3D%22101%22", mock_get.call_args.args[0])

    def test_success_false_raises(self) -> None:
        bad = MagicMock()
        bad.raise_for_status.return_value = None
        bad.json.return_value = {"success": False}
        with patch("update_cn_liquidity.requests.get", return_value=bad):
            with self.assertRaises(RuntimeError):
                ucl.fetch_shibor_rows("001")

    def test_retry_once_on_network_error(self) -> None:
        import requests as _rq
        good = _dc_response([{"REPORT_DATE": "2026-11-06 00:00:00", "IR_RATE": 1.3}])
        with patch("update_cn_liquidity.requests.get",
                   side_effect=[_rq.ConnectionError("drop"), good]) as mock_get, \
                patch("update_cn_liquidity.time.sleep"):
            rows = ucl.fetch_shibor_rows("001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(mock_get.call_count, 2)


class SocialFinancingTests(unittest.TestCase):
    @patch("update_cn_liquidity.requests.post", return_value=MagicMock(
        json=lambda: [{"date": "202603", "tiosfs": 52240.0},
                      {"date": "2026-04", "tiosfs": 6245.0},
                      {"date": "bad", "tiosfs": 1.0}]))
    def test_parse_both_month_formats(self, mock_post) -> None:
        rows = ucl.fetch_social_financing_rows()
        self.assertEqual([r["period"] for r in rows], ["2026-03", "2026-04"])
        self.assertEqual(rows[0]["value"], 52240.0)

    @patch("update_cn_liquidity.requests.post", return_value=MagicMock(
        json=lambda: {"unexpected": "shape"}))
    def test_non_array_response_rejected(self, mock_post) -> None:
        with self.assertRaises(RuntimeError):
            ucl.fetch_social_financing_rows()


class AppendIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_same_day_append_is_skip_not_overwrite(self) -> None:
        append_record(self.root, series="shibor-1w", name="Shibor 1周",
                      date="2026-11-06", value=1.346, unit="%", source="t")
        stats = ucl._append_many(self.root, series="shibor-1w", name="Shibor 1周",
                                 unit="%", source="t",
                                 items=[{"date": "2026-11-06", "value": 1.999},
                                        {"date": "2026-11-07", "value": 1.35}])
        self.assertEqual(stats, {"imported": 1, "skipped": 1})  # 旧日期 skip 不静默重写
        import json
        rows = [json.loads(x) for x in
                (self.root / "custom" / "shibor-1w.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["value"], 1.346)  # 人工/先写值未被覆盖


class MainDegradeTests(unittest.TestCase):
    def test_social_failure_does_not_fail_exit_code(self) -> None:
        # 降级语义：社融（MOFCOM gov 站风险）失败只告警；Shibor 失败才非零
        with patch("update_cn_liquidity.update_shibor"), \
                patch("update_cn_liquidity.update_social_financing",
                      side_effect=RuntimeError("gov down")):
            rc = ucl.main(["--only", "social"])
        self.assertEqual(rc, 0)

    def test_shibor_failure_fails_exit_code(self) -> None:
        with patch("update_cn_liquidity.update_shibor",
                   side_effect=RuntimeError("dc down")), \
                patch("update_cn_liquidity.update_social_financing"):
            rc = ucl.main(["--only", "shibor"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
