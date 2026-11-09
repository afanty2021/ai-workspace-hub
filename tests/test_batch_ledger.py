"""batch_ledger 单测（friction-log 2026-11-09 三漂移修根，用户拍板①）：全封闭不联网。

闭环验收：open_batch → close_batch 后 run-archive verify_ledger 干净（孤儿/未申报
均 0——孤儿判定接受 data-close 为下文是本设计的前提）；锚定语义（sha256=
row_anchor_hash）、同 path 去重取最晚锚、jsonl 缺锚剔除不炸、open 失败 sentinel
不抛；main 型集成走 update_cross_asset_history.main（batch-crossasset run 落账本，
anchor=upsert 后尾行日期）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import batch_ledger
import update_cross_asset_history as ucah

# run_archive 经 batch_ledger 自己的注入路径取（顺带锁住「跨目录导入可用」这一前提）
run_archive = batch_ledger._load_run_archive()


def _kline_response(klines: list[str]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"data": {"klines": klines}}
    return mock


class LedgerRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)      # 伪仓库根
        self.data = self.root / "data"        # 真实 data_root（_repo_rel 的语义前提）
        self.series_dir = self.data / "market" / "series"
        self.series_dir.mkdir(parents=True)
        # 两行 series（锚定哈希语义：date ≤ anchor 的行拼接）
        rows = [{"date": "2026-11-06", "close": 4078.23, "source": "eastmoney-kline"},
                {"date": "2026-11-09", "close": 4040.73, "source": "tencent"}]
        self.series_path = self.series_dir / "HSTECH.jsonl"
        self.data.mkdir(parents=True, exist_ok=True)
        self.series_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _read_rows(self) -> list[dict]:
        text = (self.data / ".state" / "run-log.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def test_open_close_roundtrip_verify_clean(self) -> None:
        run_id = batch_ledger.open_batch("batch-series", self.data)
        self.assertTrue(run_id and "batch-series" in run_id)
        batch_ledger.close_batch(run_id, [(self.series_path, "2026-11-09")], self.data,
                                 sources=["eastmoney-kline"])

        rows = self._read_rows()
        self.assertEqual([r["type"] for r in rows], ["open", "data-close"])
        target = rows[1]["data_targets"][0]
        self.assertEqual(target["path"], "data/market/series/HSTECH.jsonl")
        self.assertEqual(target["anchor_date"], "2026-11-09")
        self.assertEqual(target["sha256"],
                         run_archive.row_anchor_hash(self.series_path, "2026-11-09"))
        self.assertEqual(rows[1]["sources_used"], ["eastmoney-kline"])
        # 闭环验收：无孤儿（data-close 即下文）、无未申报修订
        report = run_archive.verify_ledger(self.data)
        self.assertEqual(report["orphan_opens"], [])
        self.assertEqual(report["undeclared"], [])

    def test_dedup_takes_latest_anchor_per_path(self) -> None:
        run_id = batch_ledger.open_batch("batch-series", self.data)
        batch_ledger.close_batch(run_id, [(self.series_path, "2026-11-06"),
                                          (self.series_path, "2026-11-09")], self.data)
        targets = self._read_rows()[1]["data_targets"]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["anchor_date"], "2026-11-09")

    def test_jsonl_missing_anchor_dropped_not_fatal(self) -> None:
        run_id = batch_ledger.open_batch("batch-series", self.data)
        other = self.series_dir / "NEW.jsonl"
        other.write_text(json.dumps({"date": "2026-11-09", "close": 1.0}) + "\n",
                         encoding="utf-8")
        batch_ledger.close_batch(run_id, [(self.series_path, None),  # 缺锚：剔除
                                          (other, "2026-11-09")], self.data)
        targets = self._read_rows()[1]["data_targets"]
        self.assertEqual([t["path"] for t in targets], ["data/market/series/NEW.jsonl"])

    def test_non_jsonl_target_gets_whole_file_hash(self) -> None:
        meta = self.data / "finance" / "_meta.json"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text("{}", encoding="utf-8")
        run_id = batch_ledger.open_batch("batch-series", self.data)
        batch_ledger.close_batch(run_id, [(meta, None)], self.data)
        target = self._read_rows()[1]["data_targets"][0]
        self.assertNotIn("anchor_date", target)
        self.assertEqual(target["sha256"], run_archive.file_sha256(meta))

    def test_open_failure_returns_none_and_close_is_noop(self) -> None:
        with patch.object(batch_ledger, "_load_run_archive",
                          side_effect=RuntimeError("boom")):
            self.assertIsNone(batch_ledger.open_batch("batch-series", self.data))
        batch_ledger.close_batch(None, [(self.series_path, "2026-11-09")], self.data)
        self.assertFalse((self.data / ".state" / "run-log.jsonl").exists())
        # open 失败留 sentinel（可感知降级）
        self.assertTrue((self.data / ".state" / "run-log.error").exists())

    def test_close_failure_writes_sentinel_not_raise(self) -> None:
        run_id = batch_ledger.open_batch("batch-series", self.data)
        with patch.object(batch_ledger, "_load_run_archive",
                          side_effect=RuntimeError("boom")):
            batch_ledger.close_batch(run_id, [(self.series_path, "2026-11-09")], self.data)
        self.assertTrue((self.data / ".state" / "run-log.error").exists())


class CrossAssetMainLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "data"   # data_root（伪仓库根的 data/）

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_main_writes_batch_crossasset_ledger_rows(self) -> None:
        # ^TNX 走东财 klines；mock 两行 → series 落盘 → 账本 open+data-close
        with patch("update_cross_asset_history.requests.get",
                   return_value=_kline_response(["2026-11-05,1,2,4.84,1,0,0",
                                                 "2026-11-06,1,2,4.80,1,0,0"])), \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            rc = ucah.main(["--tickers", "^TNX", "--throttle", "0"])
        self.assertEqual(rc, 0)
        ledger = self.root / ".state" / "run-log.jsonl"
        self.assertTrue(ledger.exists(), "main 必须落运行账本")
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        self.assertEqual([r["type"] for r in rows], ["open", "data-close"])
        self.assertIn("batch-crossasset", rows[0]["run_id"])
        target = rows[1]["data_targets"][0]
        self.assertEqual(target["path"], "data/market/series/^TNX.jsonl")
        self.assertEqual(target["anchor_date"], "2026-11-06")  # upsert 后尾行日期
        series_path = self.root / "market" / "series" / "^TNX.jsonl"
        self.assertEqual(target["sha256"],
                         run_archive.row_anchor_hash(series_path, "2026-11-06"))
        # M-3：sources_used=实际写入行内 source 指纹（非分发意图）
        self.assertEqual(rows[1]["sources_used"], ["eastmoney-kline"])
        report = run_archive.verify_ledger(self.root)
        self.assertEqual(report["orphan_opens"] + report["undeclared"], [])

    def test_main_records_missing_for_failed_ticker(self) -> None:
        # XAUUSD=X 无 secid：主源失败 → fail 票进 data-close 的 missing（不炸账本）
        with patch("update_cross_asset_history.requests.get",
                   side_effect=RuntimeError("network down")), \
                patch("market_data_io.resolve_data_root", return_value=self.root):
            rc = ucah.main(["--tickers", "XAUUSD=X", "--throttle", "0"])
        self.assertEqual(rc, 1)
        rows = [json.loads(line) for line in
                (self.root / ".state" / "run-log.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        self.assertEqual(rows[-1]["type"], "data-close")
        self.assertEqual(rows[-1]["missing"],
                         [{"item": "XAUUSD=X", "reason": "cross-asset batch update fail"}])
        # 失败轮也有账本下文：不产生孤儿
        report = run_archive.verify_ledger(self.root)
        self.assertEqual(report["orphan_opens"], [])


if __name__ == "__main__":
    unittest.main()
