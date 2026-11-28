"""update_us_liquidity 单测（2026-11-22 Fed 一手源接线）：全封闭不联网。

覆盖：NY Fed JSON 解析（倒序转正序/同日多轮聚合/单位换算/非法行剔除/缺结构拒绝）、
FRED CSV 解析（`.` 缺失剔除/窗口过滤/非数值剔除）、auto 降级链（主源网络错误→
FRED 补位+source 标注）、幂等 skip、main 双败退出码。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import requests as _rq
import update_us_liquidity as uul


def _nyfed_response(ops: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"repo": {"operations": ops}}
    return mock


def _fred_response(text: str) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.text = text
    return mock


class NyFedParseTests(unittest.TestCase):
    def test_parse_aggregate_and_convert(self) -> None:
        mock = _nyfed_response([
            {"operationDate": "2026-11-20", "totalAmtAccepted": 401000000},
            {"operationDate": "2026-11-20", "totalAmtAccepted": 1000000},  # 同日第二轮→聚合
            {"operationDate": "2026-11-19", "totalAmtAccepted": 405000000},
            {"operationDate": None, "totalAmtAccepted": 1.0},              # 缺日期剔除
            {"operationDate": "2026-11-18", "totalAmtAccepted": "x"},      # 非数值剔除
        ])
        with patch("update_us_liquidity.requests.get", return_value=mock) as mock_get:
            rows = uul.fetch_rrp_rows_nyfed("2026-11-01", "2026-11-30")
        self.assertEqual([r["date"] for r in rows], ["2026-11-19", "2026-11-20"])
        self.assertEqual(rows[-1]["value"], 0.402)  # (401M + 1M) / 1e9
        # 日期参数带连字符进 params（紧凑格式 API 返回 400，接线注记）
        self.assertEqual(mock_get.call_args.kwargs["params"],
                         {"startDate": "2026-11-01", "endDate": "2026-11-30"})

    def test_missing_operations_raises(self) -> None:
        bad = MagicMock()
        bad.raise_for_status.return_value = None
        bad.json.return_value = {"unexpected": True}
        with patch("update_us_liquidity.requests.get", return_value=bad):
            with self.assertRaises(RuntimeError):
                uul.fetch_rrp_rows_nyfed("2026-11-01", "2026-11-30")


class FredParseTests(unittest.TestCase):
    def test_parse_csv(self) -> None:
        csv_text = (
            "observation_date,RRPONTSYD\n"
            "2026-11-18,0.331\n"
            "2026-11-19,0.405\n"
            "2026-11-20,0.401\n"
            "2026-11-21,.\n"          # 缺失剔除
            "2026-11-22,abc\n"        # 非数值剔除
        )
        with patch("update_us_liquidity.requests.get",
                   return_value=_fred_response(csv_text)) as mock_get:
            rows = uul.fetch_rrp_rows_fred("2026-11-19", "2026-11-22")
        self.assertEqual([r["date"] for r in rows], ["2026-11-19", "2026-11-20"])
        self.assertEqual(rows[-1]["value"], 0.401)
        # r3 I-2：series id 与 cosd 走 params——服务器端限窗，不拉全量历史
        self.assertEqual(mock_get.call_args.kwargs["params"],
                         {"id": "RRPONTSYD", "cosd": "2026-11-19"})

    def test_empty_result_is_valid(self) -> None:
        csv_text = "observation_date,RRPONTSYD\n2026-11-20,0.401\n"
        with patch("update_us_liquidity.requests.get",
                   return_value=_fred_response(csv_text)):
            rows = uul.fetch_rrp_rows_fred("2020-01-01", "2020-12-31")  # 窗口外
        self.assertEqual(rows, [])


class LedgerKindContractTests(unittest.TestCase):
    """接线契约：batch-us-liquidity 必须在 run_archive kind 白名单——不在则
    open 被 sentinel 降级吞掉，数据写入不进账本（2026-11-22 接线首跑当场抓获）。"""

    def test_kind_whitelisted(self) -> None:
        import batch_ledger
        run_archive = batch_ledger._load_run_archive()  # 生产同款加载路径
        self.assertIn("batch-us-liquidity", run_archive.KINDS)


class UpdateRrpTests(unittest.TestCase):
    def test_auto_fallback_to_fred(self) -> None:
        today = date.today()
        day = (today - timedelta(days=1)).isoformat()
        csv_text = f"observation_date,RRPONTSYD\n{day},0.401\n"
        good_fred = _fred_response(csv_text)

        def _get(url, **kwargs):
            if "newyorkfed" in url:
                raise _rq.ConnectionError("drop")
            return good_fred

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_us_liquidity.requests.get", side_effect=_get), \
                patch("update_us_liquidity.time.sleep"):
            root = Path(tmp)
            stats = uul.update_rrp(root, days=30, source="auto")
            self.assertEqual(stats["imported"], 1)
            self.assertEqual(stats["source"], "fred-rrpontsyd")  # 实际源=备份位
            rows = [line for line in
                    (root / "custom" / "us-rrp-daily.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        self.assertIn('"fred-rrpontsyd"', rows[0])  # 实际源标注=备份位

    def test_idempotent_skip_on_rerun(self) -> None:
        today = date.today()
        day = (today - timedelta(days=1)).isoformat()
        ops = [{"operationDate": day, "totalAmtAccepted": 401000000}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("update_us_liquidity.requests.get",
                       return_value=_nyfed_response(ops)):
                first = uul.update_rrp(root, days=30)
                second = uul.update_rrp(root, days=30)
            self.assertEqual(first["imported"], 1)
            self.assertEqual(second["imported"], 0)
            self.assertEqual(second["skipped"], 1)  # 同 (series,date) 幂等 skip

    def test_main_nonzero_when_both_sources_fail(self) -> None:
        def _get(url, **kwargs):
            raise _rq.ConnectionError("drop")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_us_liquidity.requests.get", side_effect=_get), \
                patch("update_us_liquidity.time.sleep"), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            code = uul.main(["--days", "30"])
        self.assertEqual(code, 1)

    def test_main_records_source_only_on_write(self) -> None:
        """账本记源按实际写入（2026-11-22 评审 M-2）：FRED 降级成功记
        fred-rrpontsyd 而非主源名；全 skip 幂等重跑 sources_used 为空。"""
        today = date.today()
        day = (today - timedelta(days=1)).isoformat()
        good_fred = _fred_response(f"observation_date,RRPONTSYD\n{day},0.401\n")

        def _get(url, **kwargs):
            if "newyorkfed" in url:
                raise _rq.ConnectionError("drop")
            return good_fred

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_us_liquidity.requests.get", side_effect=_get), \
                patch("update_us_liquidity.time.sleep"), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            uul.main(["--days", "30"])  # 首跑：FRED 降级写入 1 行
            uul.main(["--days", "30"])  # 重跑：全 skip
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        closes = [row for row in rows if row.get("type") == "data-close"]
        self.assertEqual(closes[0]["sources_used"], ["fred-rrpontsyd"])
        self.assertEqual(closes[1]["sources_used"], [])   # 全 skip 不虚记源
        self.assertEqual(closes[1]["data_targets"], [])


class HyOasParseTests(unittest.TestCase):
    """HY OAS FRED 通路（Q-20261123-04）：% → bp ×100 换算 / 缺失剔除 / cosd 限窗。"""

    def test_parse_csv_bp_conversion(self) -> None:
        csv_text = (
            "observation_date,BAMLH0A0HYM2\n"
            "2026-11-18,3.47\n"
            "2026-11-19,3.52\n"        # 11-22 判定读数 352bp 的 FRED 原值
            "2026-11-20,.\n"           # FRED 缺失标记剔除
            "2026-11-21,abc\n"         # 非数值剔除
            "2026-11-22,3.60\n"        # 窗口外剔除（end=2026-11-21）
        )
        with patch("update_us_liquidity.requests.get",
                   return_value=_fred_response(csv_text)) as mock_get:
            rows = uul.fetch_hy_oas_rows_fred("2026-11-18", "2026-11-21")
        self.assertEqual([r["date"] for r in rows], ["2026-11-18", "2026-11-19"])
        self.assertEqual(rows[-1]["value"], 352.0)  # 3.52% ×100 = 352bp
        # cosd 限窗进 params（sibling RRPONTSYD 同族，1996 年起全量不拉）
        self.assertEqual(mock_get.call_args.kwargs["params"],
                         {"id": "BAMLH0A0HYM2", "cosd": "2026-11-18"})

    def test_update_idempotent_and_unit_tag(self) -> None:
        # 夹具日期随墙钟（today−1，同文件下方 test_main_hy_failure 同写法）——
        # 原写死 2026-11-19 的版本是老化时间炸弹：脚本窗口=[today−30, today]，
        # 2026-12-20 起夹具日期滑出窗口 → FRED 返回 0 行 → 全量必红（11-28 评审
        # 5.4 冻结复现：12-19 是 12 passed、12-20 起 1 failed）。
        today = date.today()
        day = (today - timedelta(days=1)).isoformat()
        csv_text = f"observation_date,BAMLH0A0HYM2\n{day},3.52\n"
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_us_liquidity.requests.get",
                      return_value=_fred_response(csv_text)):
            root = Path(tmp)
            first = uul.update_hy_oas(root, days=30)
            second = uul.update_hy_oas(root, days=30)
            rows = [line for line in
                    (root / "custom" / "us-hy-oas.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["imported"], 0)   # 同 (series,date) 幂等 skip
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(first["source"], "fred-bamlh0a0hym2")
        self.assertIn('"unit": "bp"', rows[0])
        self.assertIn(day, rows[0])

    def test_main_hy_failure_does_not_block_rrp(self) -> None:
        """降级语义（同社融）：HY OAS 失败只告警+missing，RRP 成功则退出码 0。"""
        today = date.today()
        day = (today - timedelta(days=1)).isoformat()
        ops = [{"operationDate": day, "totalAmtAccepted": 401000000}]

        def _get(url, **kwargs):
            if "fred" in url:
                raise _rq.ConnectionError("fred drop")  # HY OAS 恒走 FRED → 失败
            return _nyfed_response(ops)                 # RRP 主源成功

        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_us_liquidity.requests.get", side_effect=_get), \
                patch("update_us_liquidity.time.sleep"), \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)):
            code = uul.main(["--days", "30"])
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in
                    (Path(tmp) / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        close = [row for row in rows if row.get("type") == "data-close"][-1]
        self.assertEqual([m["item"] for m in close["missing"]], ["us-hy-oas"])


if __name__ == "__main__":
    unittest.main()
