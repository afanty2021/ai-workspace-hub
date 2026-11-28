"""update_crack_spread 单测（Q-20261128-04 能源腿，2026-11-28）：全封闭不联网。

覆盖：3-2-1 换算（字面量锁 26.4）、三腿日期交集缺腿可见、$/gal→$/bbl 单位断裂
毒行拒收、价差毒带两侧、幂等 skip、0 行可算上抛、main 退出码（I-1 fail loud）、
常量字面量锁（PAT-20261128-05：改常量必须红）、kind 登记契约。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import _test_paths  # noqa: F401
import update_crack_spread as ucs


def _legs(rb: dict[str, float], ho: dict[str, float], cl: dict[str, float]) -> dict:
    return {"rb": rb, "ho": ho, "cl": cl}


class ComputeTests(unittest.TestCase):
    def test_unit_conversion_literal(self) -> None:
        # (2×2.50 + 2.60)×42 − 3×80.00 = 319.2−240=79.2 → /3 = 26.4（字面量锁）
        rows, diag = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 2.50}, {"2026-01-05": 2.60}, {"2026-01-05": 80.00}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 26.4)
        self.assertEqual(rows[0]["date"], "2026-01-05")
        self.assertEqual(diag["missing"], [])
        self.assertEqual(diag["poisoned"], [])

    def test_missing_leg_visible_not_written(self) -> None:
        rows, diag = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 2.50, "2026-01-06": 2.50},
            {"2026-01-05": 2.60, "2026-01-06": 2.60},
            {"2026-01-05": 80.00}))  # cl 缺 01-06
        self.assertEqual([r["date"] for r in rows], ["2026-01-05"])
        self.assertEqual(len(diag["missing"]), 1)
        self.assertIn("cl", diag["missing"][0]["reason"])

    def test_unit_break_poison(self) -> None:
        # rb=100.0 落 $/bbl 量级带（20~150）=$/gal 源断裂特征，拒收可见
        rows, diag = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 100.0}, {"2026-01-05": 2.60}, {"2026-01-05": 80.00}))
        self.assertEqual(rows, [])
        self.assertEqual(len(diag["poisoned"]), 1)
        self.assertIn("单位断裂", diag["poisoned"][0]["reason"])

    def test_band_poison_cl(self) -> None:
        rows, diag = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 2.50}, {"2026-01-05": 2.60}, {"2026-01-05": 500.0}))
        self.assertEqual(rows, [])
        self.assertIn("越毒带", diag["poisoned"][0]["reason"])

    def test_crack_band_both_sides(self) -> None:
        # 上越带：(2×4.50+5.00)×42−3×25 = 588−75=513 → /3=171 > 80
        _, hi = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 4.50}, {"2026-01-05": 5.00}, {"2026-01-05": 25.0}))
        self.assertEqual(len(hi["poisoned"]), 1)
        self.assertIn("crack=171.0", hi["poisoned"][0]["reason"])
        # 下越带：(2×0.60+0.60)×42−3×100 = 75.6−300 → /3≈-74.8 < -20
        _, lo = ucs.compute_crack_rows(_legs(
            {"2026-01-05": 0.60}, {"2026-01-05": 0.60}, {"2026-01-05": 100.0}))
        self.assertEqual(len(lo["poisoned"]), 1)


class ConstantLiteralLockTests(unittest.TestCase):
    """常量字面量锁（I-10/B-M-B1 同族）：改常量必须改测试，防自引用夹具自绿。"""

    def test_bands_are_literals(self) -> None:
        self.assertEqual(ucs.GAL_TO_BBL, 42.0)
        self.assertEqual(ucs.RB_GAL_BAND, (0.5, 5.0))
        self.assertEqual(ucs.HO_GAL_BAND, (0.5, 5.5))
        self.assertEqual(ucs.CL_BBL_BAND, (20.0, 200.0))
        self.assertEqual(ucs.UNIT_BREAK_BAND, (20.0, 150.0))
        self.assertEqual(ucs.CRACK_BBL_BAND, (-20.0, 80.0))

    def test_symbols_and_series_literals(self) -> None:
        self.assertEqual((ucs.RB_SYMBOL, ucs.HO_SYMBOL, ucs.CL_SYMBOL),
                         ("RB=F", "HO=F", "CL=F"))
        self.assertEqual(ucs.CRACK_SERIES, "us-321-crack")
        self.assertEqual(ucs.CRACK_SOURCE_TAG, "yfinance-rbf-hof-clf")


class UpdateTests(unittest.TestCase):
    def _good_legs(self) -> dict:
        return _legs(
            {"2026-09-01": 2.00, "2026-11-20": 2.50},
            {"2026-09-01": 2.00, "2026-11-20": 2.60},
            {"2026-09-01": 80.00, "2026-11-20": 80.00})
        # 09-01 行：(2×2.00+2.00)×42−3×80 = 252−240=12 → /3=4.0
        # 11-20 行：26.4；42d 基期取 ≤11-20−42d=10-09 → 09-01 行 → chg_42d=+22.4

    def test_writes_and_registers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_crack_spread.fetch_product_closes",
                      return_value=self._good_legs()):
            stats = ucs.update_crack(Path(tmp), days=120)
            self.assertEqual(stats["imported"], 2)
            self.assertEqual(stats["last_value"], 26.4)
            self.assertEqual(stats["chg_42d"], 22.4)
            registry = json.loads((Path(tmp) / "custom" / "registry.json").read_text())
            self.assertIn("us-321-crack", registry)
            lines = (Path(tmp) / "custom" / "us-321-crack.jsonl").read_text().splitlines()
            self.assertEqual(json.loads(lines[-1])["value"], 26.4)
            self.assertEqual(json.loads(lines[-1])["unit"], "美元/桶")

    def test_idempotent_rerun_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_crack_spread.fetch_product_closes",
                      return_value=self._good_legs()):
            ucs.update_crack(Path(tmp), days=120)
            stats = ucs.update_crack(Path(tmp), days=120)
        self.assertEqual(stats["imported"], 0)
        self.assertEqual(stats["skipped"], 2)

    def test_zero_rows_raises(self) -> None:
        disjoint = _legs({"2026-01-05": 2.50}, {"2026-01-06": 2.60},
                         {"2026-01-07": 80.00})
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_crack_spread.fetch_product_closes", return_value=disjoint):
            with self.assertRaises(RuntimeError):
                ucs.update_crack(Path(tmp), days=30)

    def test_all_poisoned_raises(self) -> None:
        boom = _legs({"2026-01-05": 100.0}, {"2026-01-05": 100.0},
                     {"2026-01-05": 80.00})
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_crack_spread.fetch_product_closes", return_value=boom):
            with self.assertRaises(RuntimeError):
                ucs.update_crack(Path(tmp), days=30)

    def test_empty_legs_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch("update_crack_spread.fetch_product_closes",
                      return_value={"rb": {}, "ho": {}, "cl": {}}):
            with self.assertRaises(RuntimeError):
                ucs.update_crack(Path(tmp), days=30)


class _FakeFrame:
    def __init__(self, pairs: list[tuple[str, float | None]]) -> None:
        import pandas as pd

        self._frame = pd.DataFrame(
            {"Close": [p[1] for p in pairs]},
            index=pd.DatetimeIndex([p[0] for p in pairs]))

    def iterrows(self):  # 模拟 yfinance 返回结构（真 DataFrame，逐行 try 走真路径）
        return self._frame.iterrows()


class FetchTests(unittest.TestCase):
    def test_filters_nonfinite_and_formats_dates(self) -> None:
        fake = SimpleNamespace(Ticker=lambda _sym: MagicMock(
            history=lambda **_kw: _FakeFrame(
                [("2026-11-26", 2.4951), ("2026-11-27", float("nan")),
                 ("2026-11-28", None)])))
        with patch.dict(sys.modules, {"yfinance": fake}):
            out = ucs.fetch_product_closes(30)
        self.assertEqual(out["rb"], {"2026-11-26": 2.4951})
        self.assertEqual(out["ho"], {"2026-11-26": 2.4951})
        self.assertEqual(out["cl"], {"2026-11-26": 2.4951})


class MainTests(unittest.TestCase):
    def _good_legs(self) -> dict:
        return UpdateTests._good_legs(self)

    def test_main_success_and_ledger_kind_registered(self) -> None:
        import run_archive

        self.assertIn("batch-crack-spread", run_archive.KINDS)
        with tempfile.TemporaryDirectory() as tmp, \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)), \
                patch("update_crack_spread.fetch_product_closes",
                      return_value=self._good_legs()):
            code = ucs.main(["--days", "120"])
            # 断言须在 with 内：TemporaryDirectory 退出即清理（兄弟测试同口径）
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "custom" / "us-321-crack.jsonl").exists())

    def test_main_nonzero_when_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)), \
                patch("update_crack_spread.fetch_product_closes",
                      return_value={"rb": {}, "ho": {}, "cl": {}}):
            self.assertEqual(ucs.main(["--days", "30"]), 1)

    def test_main_nonzero_when_zero_computable(self) -> None:
        disjoint = _legs({"2026-01-05": 2.50}, {"2026-01-06": 2.60},
                         {"2026-01-07": 80.00})
        with tempfile.TemporaryDirectory() as tmp, \
                patch("market_data_io.resolve_data_root", return_value=Path(tmp)), \
                patch("update_crack_spread.fetch_product_closes", return_value=disjoint):
            self.assertEqual(ucs.main(["--days", "30"]), 1)


if __name__ == "__main__":
    unittest.main()
