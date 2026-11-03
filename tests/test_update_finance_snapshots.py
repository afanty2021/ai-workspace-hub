"""update_finance_snapshots 单测。重名列 fixture 验证「按位置+出现序号取数」（spec §4.3）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from _test_paths import REPO_ROOT  # noqa: F401

import update_finance_snapshots as ufs  # noqa: E402

# 19 列 fixture：重名列（净资产收益率/归母/扣非 ×2）模拟 659 列真实结构的关键陷阱
_COLS = [
    "基本每股收益", "扣除非经常性损益每股收益", "每股净资产", "净资产收益率",          # 0-3（第一次出现）
    "其中：营业收入", "归属于母公司所有者的净利润", "扣除非经常性损益后的净利润",     # 4-6（累计）
    "存货", "货币资金", "资产总计", "负债合计",                                      # 7-10
    "营业收入增长率(%)", "净利润增长率(%)", "扣非净利润同比(%)",                     # 11-13
    "业绩预告-本期净利润同比增幅下限%", "业绩预告-本期净利润同比增幅上限%",           # 14-15
    "净资产收益率", "归属于母公司所有者的净利润", "扣除非经常性损益后的净利润",       # 16-18（第二次出现=单季）
]


def _fixture_df() -> pd.DataFrame:
    data = [
        [3.63, 3.759, 38.98, 8.832, 18460532736.0, 3383763712.0, 3694268928.0,
         9249440768.0, 10276478976.0, 71296745472.0, 32984334336.0,
         30.77, 4.28, 13.74, 0.0, 0.0, 8.832, 526984832.0, 1276468352.0],   # 300476
        [60.0, 61.0, 300.0, 30.0, 1e11, 2e10, 2.1e10, 3e10, 5e10, 3e11, 1e11,
         15.0, 16.0, 17.0, 25.0, 35.0, 30.0, 2e9, 2.1e9],                     # 600519
    ]
    return pd.DataFrame(data, index=["300476", "600519"], columns=_COLS)


class ColumnMappingTests(unittest.TestCase):
    def test_positions_pin_first_occurrence(self) -> None:
        pos = ufs.column_positions(_COLS)
        self.assertEqual(pos["roe"], 3)                    # 第一次（每股指标段）
        self.assertEqual(pos["net_profit_parent"], 5)      # 累计口径
        self.assertEqual(pos["net_profit_deducted"], 6)

    def test_missing_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            ufs.column_positions(["别的列", "基本每股收益"])  # 其余映射键找不到

    def test_rows_take_cumulative_and_nullify_zero_forecast(self) -> None:
        rows = ufs.rows_from_dataframe(_fixture_df(), "2026-09-30", "deadbeef")
        row = next(r for r in rows if r["code"] == "300476")
        self.assertEqual(row["net_profit_parent"], 3383763712.0)  # 累计，不是单季 526984832
        self.assertEqual(row["net_profit_deducted"], 3694268928.0)
        self.assertIsNone(row["forecast_min"])                    # 0 视为无预告（spec §4.3）
        self.assertEqual(row["market"], "SZ")
        self.assertEqual(rows[1]["market"], "SH")                 # 600519 → SH
        self.assertEqual(row["file_hash"], "deadbeef")
        self.assertEqual(row["schema_version"], 1)


class FinanceFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.files = [
            {"filename": "gpcw20261231.zip", "hash": "future", "filesize": 164},       # 占位
            {"filename": "gpcw20260930.zip", "hash": "h1", "filesize": 5488120},       # 最新期
            {"filename": "gpcw20260630.zip", "hash": "h2", "filesize": 5300000},       # 上一期
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_hash_unchanged_skips_zero_download(self) -> None:
        meta = self.root / "finance"
        meta.mkdir()
        (meta / "_meta.json").write_text(
            json.dumps({"gpcw20260930.zip": {"hash": "h1", "rows": 5571}}), encoding="utf-8")
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw") as dl, \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 0, "skip": 1, "fail": 0})
        dl.assert_not_called()  # 零下载

    def test_changed_hash_rewrites_period_and_meta(self) -> None:
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw") as dl, \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()) as parse:
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        dl.assert_called_once()
        parse.assert_called_once()
        out = self.root / "finance" / "gpcw-2026-09-30.jsonl"
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x]
        self.assertEqual(len(rows), 2)
        meta = json.loads((self.root / "finance" / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["gpcw20260930.zip"]["hash"], "h1")
        self.assertEqual(meta["gpcw20260930.zip"]["rows"], 2)

    def test_backfill_all_processes_every_period(self) -> None:
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw"), \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root, backfill="all")
        self.assertEqual(stats, {"ok": 2, "skip": 0, "fail": 0})  # 两期都处理，占位被过滤

    def test_placeholder_filter_logs_dropped_filenames(self) -> None:
        # Minor：占位过滤只打总数不够排障——被滤文件名明细也要落日志
        with patch.object(ufs, "files_with_fallback", return_value=(self.files, None)), \
             patch.object(ufs, "download_gpcw"), \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()), \
             patch.object(ufs, "log") as fake_log:
            ufs.run_finance_update(self.root)
        joined = "\n".join(str(c.args[0]) for c in fake_log.call_args_list if c.args)
        self.assertIn("占位过滤 1 期", joined)
        self.assertIn("gpcw20261231.zip", joined)  # 被滤的是哪只空壳，名字要看得见

    def test_gp_fallback_pins_bestip_and_restores(self) -> None:
        # gp_fallback≠None 主路径此前零覆盖（复查）：ctx 内 GP 被钉住、退出恢复原值
        from mootdx import config as mootdx_config

        mootdx_config.setup()
        saved = mootdx_config.get("BESTIP")
        with ufs._affair_gp_bestip("203.0.113.7", 7709):
            self.assertEqual(mootdx_config.get("BESTIP")["GP"], ("203.0.113.7", 7709))
        self.assertEqual(mootdx_config.get("BESTIP"), saved)

    def test_run_with_gp_fallback_routes_through_pinned_channel(self) -> None:
        with patch.object(ufs, "files_with_fallback",
                          return_value=(self.files, ("203.0.113.7", 7709))), \
             patch.object(ufs, "_affair_gp_bestip", wraps=ufs._affair_gp_bestip) as gp_ctx, \
             patch.object(ufs, "download_gpcw"), \
             patch.object(ufs, "parse_gpcw", return_value=_fixture_df()):
            stats = ufs.run_finance_update(self.root)
        self.assertEqual(stats, {"ok": 1, "skip": 0, "fail": 0})
        gp_ctx.assert_called_once_with("203.0.113.7", 7709)  # download/parse 全程钉在兜底服务器

    def test_files_with_fallback_clean_error_when_both_channels_dead(self) -> None:
        # N5：负缓存窗口内 _get_mootdx_client 直接 raise——不得以 CLI traceback 收场
        with patch("mootdx.affair.Affair.files", side_effect=RuntimeError("default GP dead")), \
             patch.object(ufs, "_fallback_gp_server", side_effect=RuntimeError("全网负缓存")):
            with self.assertRaisesRegex(RuntimeError, "均不可用"):
                ufs.files_with_fallback()


if __name__ == "__main__":
    unittest.main()
