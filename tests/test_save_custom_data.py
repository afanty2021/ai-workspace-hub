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


if __name__ == "__main__":
    unittest.main()
