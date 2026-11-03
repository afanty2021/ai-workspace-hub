"""save_custom_data 单测。语义与行情层相反：默认拒绝覆盖（spec §5.4）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401

import market_data_io as mio  # noqa: E402
import save_custom_data as scd  # noqa: E402


class CustomSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_registers_and_records(self) -> None:
        scd.append_record(self.root, series="korea-semi-export", name="韩国半导体出口",
                          date="2026-11-01", period="2026-10", value=275.0,
                          unit="亿美元", source="韩国关税厅 1-20 日初步")
        registry = json.loads((self.root / "custom" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["korea-semi-export"]["unit"], "亿美元")
        rows = scd.show_series(self.root, "korea-semi-export")
        self.assertEqual(rows[0]["period"], "2026-10")
        self.assertIn("recorded_at", rows[0])
        self.assertIsNone(rows[0].get("note"))

    def test_duplicate_rejected_unless_overwrite(self) -> None:
        kwargs = dict(series="x", name="X", date="2026-11-01", value=1.0,
                      unit="件", source="s")
        scd.append_record(self.root, **kwargs)
        with self.assertRaises(ValueError):
            scd.append_record(self.root, **dict(kwargs, value=2.0))  # kwargs 已含 value，必须 dict 覆盖而非重复传参
        scd.append_record(self.root, **dict(kwargs, value=2.0), overwrite=True)
        self.assertEqual(scd.show_series(self.root, "x")[-1]["value"], 2.0)
        self.assertEqual(len(scd.show_series(self.root, "x")), 1)  # 覆盖不追加

    def test_series_slug_whitelist_blocks_write_through(self) -> None:
        # I1：series 名零校验时 "../market/series/600276.SH" 会把行情序列文件当
        # custom 序列整文件重写（写穿污染）——与 save_news_snapshot 的 slug 守卫同构
        market = self.root / "market" / "series" / "600276.SH.jsonl"
        market.parent.mkdir(parents=True)
        market.write_text('{"date": "2026-11-02", "close": 71.0}\n', encoding="utf-8")
        for bad in ("../market/series/600276.SH", "UPPER", "a/b", "-lead"):
            with self.assertRaises(ValueError, msg=bad):
                scd.append_record(self.root, series=bad, name="x", date="2026-11-02",
                                  value=1.0, unit="u", source="s")
        self.assertEqual(market.read_text(encoding="utf-8"),
                         '{"date": "2026-11-02", "close": 71.0}\n')  # 行情文件未被碰
        self.assertFalse((self.root / "custom").exists())  # 校验在读 registry 之前，连目录都不建

    def test_nan_inf_value_rejected_before_any_write(self) -> None:
        # NaN 补靶（修错对象后的真靶点）：--value nan 经 argparse type=float 直达这里，
        # json.dumps 默认放行非标 NaN 字面量，一条毒行让 query_market 读整条 series 失败；
        # 校验在读 registry 之前，坏值连目录都不建（与 slug 守卫同位）
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                scd.append_record(self.root, series="x", name="X", date="2026-11-03",
                                  value=bad, unit="件", source="s")
        self.assertFalse((self.root / "custom").exists())

    def test_import_csv_bad_series_name_rejected_whole_batch(self) -> None:
        # Minor②：坏 series 名循环前整批拒绝——旧行为逐行落进 except ValueError 计
        # skipped、退出 0，用户以为导入成功
        csv = self.root / "in.csv"
        csv.write_text("date,value,unit,source\n2026-11-03,1.0,件,s\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            scd.import_csv(self.root, "../market/series/600276.SH", csv)
        self.assertFalse((self.root / "custom").exists())  # 校验在任何写之前

    def test_csv_import_maps_columns_and_skips_existing(self) -> None:
        scd.append_record(self.root, series="x", name="X", date="2026-10-01",
                          value=9.0, unit="件", source="seed")
        csv = self.root / "in.csv"
        csv.write_text("date,period,value,unit,source,note,junk\n"
                       "2026-09-01,2026-09,3.0,件,s1,n1,忽略我\n"
                       "2026-10-01,,9.5,件,s2,,撞已有\n"
                       ",,坏行没日期,,,\n"
                       "2026-08-01,,不是数,件,s3,,\n", encoding="utf-8")
        stats = scd.import_csv(self.root, "x", csv)
        self.assertEqual(stats, {"imported": 1, "skipped": 3})
        rows = {r["date"]: r for r in scd.show_series(self.root, "x")}
        self.assertEqual(rows["2026-10-01"]["value"], 9.0)   # 撞已有跳过，没被改
        self.assertEqual(rows["2026-09-01"]["period"], "2026-09")
        self.assertNotIn("junk", rows["2026-09-01"])         # 其余列忽略

    def test_csv_import_overwrite_updates_existing(self) -> None:
        # --overwrite 路径此前零覆盖：撞已有日期应整行覆盖而非 skipped
        scd.append_record(self.root, series="x", name="X", date="2026-10-01",
                          value=9.0, unit="件", source="seed")
        csv = self.root / "in.csv"
        csv.write_text("date,value,unit,source\n2026-10-01,9.5,件,s2\n", encoding="utf-8")
        stats = scd.import_csv(self.root, "x", csv, overwrite=True)
        self.assertEqual(stats, {"imported": 1, "skipped": 0})
        rows = scd.show_series(self.root, "x")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 9.5)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_duplicate_append_cli_returns_1_not_traceback(self) -> None:
        # 与 update_finance_snapshots 同款干净收口：ValueError → log + 退出码 1，不出 CLI traceback
        argv = ["append", "--series", "x", "--name", "X", "--date", "2026-11-01",
                "--value", "1.0", "--unit", "件", "--source", "s"]
        with patch.object(mio, "resolve_data_root", return_value=self.root):
            self.assertEqual(scd.main(argv), 0)                    # 首次 append 成功
            self.assertEqual(scd.main(argv), 1)                    # 重复 append 被拒：干净退出 1

    def test_nan_inf_cli_returns_1_no_poison_row(self) -> None:
        # CLI 负样本：--value nan/inf 复用 main 的 ValueError 收口干净退出 1，毒行不落盘
        for bad in ("nan", "inf"):
            argv = ["append", "--series", "x", "--name", "X", "--date", "2026-11-03",
                    "--value", bad, "--unit", "件", "--source", "s"]
            with patch.object(mio, "resolve_data_root", return_value=self.root):
                self.assertEqual(scd.main(argv), 1, msg=bad)
        self.assertFalse((self.root / "custom" / "x.jsonl").exists())

    def test_csv_import_bad_series_cli_returns_1(self) -> None:
        # Minor② CLI 面：csv-import 坏 series 名干净退出 1，不出 traceback
        csv = self.root / "in.csv"
        csv.write_text("date,value,unit,source\n2026-11-03,1.0,件,s\n", encoding="utf-8")
        argv = ["csv-import", "--series", "BAD/NAME", "--file", str(csv)]
        with patch.object(mio, "resolve_data_root", return_value=self.root):
            self.assertEqual(scd.main(argv), 1)


if __name__ == "__main__":
    unittest.main()
