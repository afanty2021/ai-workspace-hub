from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

import check_setup  # noqa: E402
from check_setup import initialize_config  # noqa: E402
from fetch_market_data import fetch_eod_quote, fetch_nasdaq_quote, load_env  # noqa: E402
from workspace_paths import find_workspace_root, resolve_reports_dir  # noqa: E402


class WorkspacePathTests(unittest.TestCase):
    def test_integrated_workspace_is_found_before_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace").mkdir()
            (root / "workspace" / "workspace-config.md").write_text(
                "# Workspace Config\n", encoding="utf-8"
            )
            script_dir = root / "tools" / "daily-watch" / "scripts"
            script_dir.mkdir(parents=True)
            self.assertEqual(find_workspace_root(script_dir), root.resolve())

    def test_standalone_workspace_falls_back_to_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "daily-watchlist.yaml").write_text(
                "modules: {}\n", encoding="utf-8"
            )
            script_dir = root / "scripts"
            script_dir.mkdir()
            self.assertEqual(find_workspace_root(script_dir), root.resolve())

    def test_initialize_config_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = initialize_config(root)
            second = initialize_config(root)
            self.assertEqual(len(first), 5)
            self.assertEqual(second, [])
            self.assertTrue((root / "config" / "daily-watchlist.yaml").is_file())

    def test_initialize_config_seeds_empty_watchlist_not_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_config(root)
            watchlist = (root / "config" / "daily-watchlist-watchlist.md").read_text(
                encoding="utf-8"
            )
            # The demo example (AAPL/MSFT/...) must not leak into a fresh
            # workspace; only the empty template with its table header ships.
            self.assertNotIn("AAPL", watchlist)
            self.assertNotIn("NVDA", watchlist)
            self.assertIn("| Ticker |", watchlist)
            self.assertIn("唯一执行股票池", watchlist)

    def test_setup_check_surfaces_free_source_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace").mkdir()
            (root / "workspace/workspace-config.md").write_text(
                "# Workspace Config\n", encoding="utf-8"
            )
            stream = StringIO()
            with (
                patch("sys.argv", ["check_setup.py", "--init"]),
                patch("workspace_paths.find_workspace_root", return_value=root),
                patch.dict("os.environ", {}, clear=True),
                redirect_stdout(stream),
            ):
                result = check_setup.main()
            output = stream.getvalue()
            self.assertEqual(result, 0)
            self.assertIn("Nasdaq 无 Key 美股基础行情", output)
            self.assertIn("FINNHUB_API_KEY", output)
            self.assertIn("EOD_API_KEY", output)
            self.assertIn("yfinance 无 Key 备用行情", output)
            self.assertIn("DATA-SOURCES.md", output)

    def test_reports_use_compact_output_path_for_new_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_reports_dir(root), root / "output/daily-watch")

    def test_reports_keep_legacy_path_when_it_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "daily-watchlist-reports"
            legacy.mkdir()
            (root / "output/daily-watch").mkdir(parents=True)
            self.assertEqual(resolve_reports_dir(root), legacy)

    def test_placeholder_api_keys_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "daily-watchlist.env"
            env_file.write_text(
                "FMP_API_KEY=your_fmp_api_key\nTUSHARE_TOKEN=your_tushare_token\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                values = load_env(env_file)
            self.assertEqual(values["FMP_API_KEY"], "")
            self.assertEqual(values["TUSHARE_TOKEN"], "")

    @patch("fetch_market_data.requests.get")
    def test_nasdaq_fallback_normalizes_quote(self, mock_get) -> None:
        response = mock_get.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": {
                "primaryData": {
                    "lastSalePrice": "$297.01",
                    "netChange": "-1.00",
                    "percentageChange": "-0.34%",
                    "lastTradeTimestamp": "Jun 22, 2026",
                    "volume": "44,880,180",
                }
            }
        }
        quote = fetch_nasdaq_quote("AAPL", "US")
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 297.01)
        self.assertEqual(quote["changesPercentage"], -0.34)
        self.assertEqual(quote["volume"], 44880180.0)
        self.assertEqual(quote["source"], "nasdaq")

    @patch("fetch_market_data.request_json")
    def test_eodhd_free_eod_fallback_normalizes_quote(self, request_json) -> None:
        request_json.return_value = [
            {
                "date": "2026-08-28",
                "open": 600.0,
                "high": 612.0,
                "low": 598.0,
                "close": 610.0,
                "volume": 123456,
            },
            {"date": "2026-08-27", "close": 600.0},
        ]
        quote = fetch_eod_quote("0700.HK", "HK", "free-key")
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 610.0)
        self.assertEqual(quote["change"], 10.0)
        self.assertAlmostEqual(quote["changesPercentage"], 10 / 600 * 100)
        self.assertEqual(quote["tradeDate"], "2026-08-28")
        self.assertEqual(quote["source"], "eod")
        request_json.assert_called_once()
        self.assertIn("/api/eod/0700.HK", request_json.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
