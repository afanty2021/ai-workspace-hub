"""Eastmoney / Tencent / Sina keyless CN fallback sources.

Field maps mirror the endpoints' actual payload layout (verified against a
sibling project's production usage); payloads below are minimal but keep the
real field positions so index drift breaks tests instead of reports.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

from fetch_market_data import (  # noqa: E402
    _cn_quote_symbol,
    build_quote_record,
    fetch_eastmoney_quote,
    fetch_fallback_quote,
    fetch_sina_quote,
    fetch_tencent_quote,
)

# ~-separated, >=35 fields; indexes 1/3/4/5/6/30/31/32/33/34 are load-bearing.
TENCENT_PAYLOAD = (
    'v_sh600276="1~恒瑞医药~600276~48.36~45.55~46.00~123456~x~x~x~x~x~x~x~x~x~x'
    '~x~x~x~x~x~x~x~x~x~x~x~x~x~20261028150000~2.81~6.17~49.00~45.80";'
)
# Comma-separated, >=31 fields; indexes 0..5, 8, 30 are load-bearing.
SINA_PAYLOAD = (
    'var hq_str_sh600276="恒瑞医药,46.00,45.55,48.36,49.00,45.80,48.30,48.36,'
    '12345600,567890000,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,2026-10-28,15:00:00,00";'
)
EASTMONEY_PAYLOAD = {
    "data": {
        "f43": 48.36,
        "f44": 49.00,
        "f45": 45.80,
        "f46": 46.00,
        "f47": 123456,
        "f58": "恒瑞医药",
        "f60": 45.55,
        "f86": 1774569600,
        "f169": 2.81,
        "f170": 6.17,
    }
}


def _text_response(payload: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = payload
    return response


class SymbolRuleTests(unittest.TestCase):
    def test_sh_sz_and_etf_codes_map_to_prefixed_symbols(self) -> None:
        self.assertEqual(_cn_quote_symbol("600276.SH"), "sh600276")
        self.assertEqual(_cn_quote_symbol("002415.SZ"), "sz002415")
        self.assertEqual(_cn_quote_symbol("513880.SH"), "sh513880")

    def test_non_cn_tickers_are_rejected(self) -> None:
        self.assertIsNone(_cn_quote_symbol("AAPL"))
        self.assertIsNone(_cn_quote_symbol("0700.HK"))
        self.assertIsNone(_cn_quote_symbol("601857"))


class EastmoneyQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_normalizes_quote_fields(self, mock_get: MagicMock) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = EASTMONEY_PAYLOAD
        mock_get.return_value = response

        quote = fetch_eastmoney_quote("600276.SH", "CN")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 48.36)
        self.assertEqual(quote["change"], 2.81)
        self.assertEqual(quote["changesPercentage"], 6.17)
        self.assertEqual(quote["previousClose"], 45.55)
        self.assertEqual(quote["open"], 46.00)
        self.assertEqual(quote["dayHigh"], 49.00)
        self.assertEqual(quote["dayLow"], 45.80)
        self.assertEqual(quote["volume"], 123456)
        self.assertEqual(quote["source"], "eastmoney")
        self.assertRegex(quote["tradeDate"], r"^\d{4}-\d{2}-\d{2}$")
        # SH suffix maps to exchange code 1, SZ to 0 (also for ETFs).
        self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], "1.600276")

    @patch("fetch_market_data.requests.get")
    def test_returns_none_on_empty_and_non_cn(self, mock_get: MagicMock) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": None}
        mock_get.return_value = response
        self.assertIsNone(fetch_eastmoney_quote("600276.SH", "CN"))

        self.assertIsNone(fetch_eastmoney_quote("AAPL", "US"))
        mock_get.assert_called_once()


class TencentQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_normalizes_quote_fields(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_PAYLOAD)

        quote = fetch_tencent_quote("600276.SH", "CN")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 48.36)
        self.assertEqual(quote["change"], 2.81)
        self.assertEqual(quote["changesPercentage"], 6.17)
        self.assertEqual(quote["previousClose"], 45.55)
        self.assertEqual(quote["open"], 46.00)
        # Field 33 is HIGH and 34 is LOW (the reverse of naive expectation).
        self.assertEqual(quote["dayHigh"], 49.00)
        self.assertEqual(quote["dayLow"], 45.80)
        self.assertEqual(quote["volume"], 123456)
        self.assertEqual(quote["tradeDate"], "20261028")
        self.assertEqual(quote["source"], "tencent")
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "tencent endpoint must stay HTTPS",
        )
        self.assertIn("q=sh600276", str(mock_get.call_args))

    @patch("fetch_market_data.requests.get")
    def test_returns_none_on_truncated_and_non_cn(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response('v_sh600276="1~恒瑞医药~600276~48.36";')
        self.assertIsNone(fetch_tencent_quote("600276.SH", "CN"))

        self.assertIsNone(fetch_tencent_quote("0700.HK", "HK"))
        mock_get.assert_called_once()


class SinaQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_computes_change_and_normalizes_volume(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(SINA_PAYLOAD)

        quote = fetch_sina_quote("600276.SH", "CN")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 48.36)
        self.assertAlmostEqual(quote["change"], 2.81)
        self.assertAlmostEqual(quote["changesPercentage"], 2.81 / 45.55 * 100)
        self.assertEqual(quote["previousClose"], 45.55)
        self.assertEqual(quote["dayHigh"], 49.00)
        self.assertEqual(quote["dayLow"], 45.80)
        # Sina reports volume in shares; normalize to lots like tushare/腾讯.
        self.assertEqual(quote["volume"], 123456)
        self.assertEqual(quote["tradeDate"], "2026-10-28")
        self.assertEqual(quote["source"], "sina")
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "sina endpoint must stay HTTPS",
        )

    @patch("fetch_market_data.requests.get")
    def test_returns_none_on_empty_and_non_cn(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response('var hq_str_sh600276="";')
        self.assertIsNone(fetch_sina_quote("600276.SH", "CN"))

        self.assertIsNone(fetch_sina_quote("AAPL", "US"))
        mock_get.assert_called_once()


class TradeDateNormalizationTests(unittest.TestCase):
    def test_yyyymmdd_becomes_iso_in_quote_record(self) -> None:
        entry = {"ticker": "600276.SH", "name": "", "market": "CN", "market_cap": "", "category": ""}
        raw = {"price": 1.0, "tradeDate": "20261028"}
        self.assertEqual(build_quote_record(raw, entry)["tradeDate"], "2026-10-28")
        raw["tradeDate"] = "2026-10-28"
        self.assertEqual(build_quote_record(raw, entry)["tradeDate"], "2026-10-28")
        raw["tradeDate"] = ""
        # Empty date falls through the `or timestamp` chain to None, matching
        # how other absent fields normalize.
        self.assertIsNone(build_quote_record(raw, entry)["tradeDate"])


class FallbackChainOrderTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_cn_ticker_falls_through_eastmoney_to_tencent(self, mock_get: MagicMock) -> None:
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url:
                broken = MagicMock()
                broken.raise_for_status.side_effect = RuntimeError("down")
                return broken
            assert "qt.gtimg.cn" in url
            return _text_response(TENCENT_PAYLOAD)

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "600276.SH", "market": "CN"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "tencent")

    @patch("fetch_market_data.requests.get")
    def test_us_ticker_never_touches_cn_endpoints(self, mock_get: MagicMock) -> None:
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        fetch_fallback_quote({"ticker": "AAPL", "market": "US"}, env)

        # No keyless US source beyond Nasdaq; without network mocking its real
        # call would fire, so instead verify no CN endpoint was requested.
        for call in mock_get.call_args_list:
            url = str(call.args[0] if call.args else call.kwargs.get("url", ""))
            self.assertNotIn("eastmoney", url)
            self.assertNotIn("gtimg.cn", url)
            self.assertNotIn("sinajs", url)


if __name__ == "__main__":
    unittest.main()
