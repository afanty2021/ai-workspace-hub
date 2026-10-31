"""Nasdaq index API / FRED / Sina global keyless feeds for macro tickers.

Field layouts follow akshare 1.18's production parser (hf_ feed) and two
independent DINIW references; payloads below keep the real field positions so
index drift breaks tests instead of reports.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

from fetch_market_data import (  # noqa: E402
    fetch_eastmoney_global_quote,
    fetch_fallback_quote,
    fetch_fred_series_quote,
    fetch_nasdaq_index_quote,
    fetch_sina_global_quote,
)

NASDAQ_INDEX_PAYLOAD = {
    "data": {
        "primaryData": {
            "lastSalePrice": "10,688.80",
            "netChange": "-829.40",
            "percentageChange": "-7.20%",
            "lastTradeTimestamp": "Oct 30, 2026",
            "volume": None,
        }
    }
}
FRED_CSV = "observation_date,DGS10\n2026-10-28,5.05\n2026-10-29,4.98\n"
# DINIW layout: 0=time 1=last 2=prev_close 3=open 4=vol 5=bid 6=high 7=low
# 8=ask 9=name 10=date (weekend snapshots freeze last==prev_close).
DINIW_PAYLOAD = (
    'var hq_str_DINIW="05:41:42,101.9669,101.9669,101.8857,5052,101.9016,'
    '102.0903,101.5851,101.9669,美元指数,2026-10-31";'
)
# hf_ layout per akshare: 0=current 2=bid 3=ask 4=high 5=low 6=time
# 7=last_settle 8=open 12=date 13=name.
XAU_PAYLOAD = (
    'var hq_str_hf_XAU="3876.69,4021.230,3876.69,3877.07,4026.24,3870.05,'
    '04:55:00,4021.23,4023.79,0,0,0,2026-10-31,伦敦金（现货黄金）";'
)
CAD_PAYLOAD = (
    'var hq_str_hf_CAD="14128.160,,14129.500,14132.000,14361.000,14107.000,'
    '02:59:24,14154.500,14310.000,0,1,1,2026-10-31,伦铜,23102";'
)


def _text_response(payload: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = payload
    return response


def _json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class NasdaqIndexQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_normalizes_index_fields(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _json_response(NASDAQ_INDEX_PAYLOAD)

        quote = fetch_nasdaq_index_quote("^SOX", "INDEX")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 10688.80)
        self.assertEqual(quote["change"], -829.40)
        self.assertEqual(quote["changesPercentage"], -7.20)
        self.assertAlmostEqual(quote["previousClose"], 10688.80 + 829.40, places=6)
        self.assertEqual(quote["source"], "nasdaq")
        # Index quotes use the dedicated assetclass=index endpoint.
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://api.nasdaq.com/api/quote/SOX/info?assetclass=index",
        )

    @patch("fetch_market_data.requests.get")
    def test_non_mapped_tickers_never_hit_the_index_api(self, mock_get: MagicMock) -> None:
        self.assertIsNone(fetch_nasdaq_index_quote("NVDA", "US"))
        self.assertIsNone(fetch_nasdaq_index_quote("600276.SH", "CN"))
        mock_get.assert_not_called()


class FredSeriesQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_diffs_last_two_observations(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(FRED_CSV)

        quote = fetch_fred_series_quote("^TNX", "INDEX")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 4.98)
        self.assertEqual(quote["previousClose"], 5.05)
        self.assertEqual(quote["change"], -0.07)
        self.assertAlmostEqual(quote["changesPercentage"], -0.07 / 5.05 * 100, places=6)
        self.assertEqual(quote["tradeDate"], "2026-10-29")
        self.assertEqual(quote["source"], "fred")
        self.assertEqual(mock_get.call_args.kwargs["params"]["id"], "DGS10")
        # cosd 限定近 30 天窗口，避免全量历史。
        self.assertIn("cosd", mock_get.call_args.kwargs["params"])
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "FRED endpoint must stay HTTPS",
        )

    @patch("fetch_market_data.requests.get")
    def test_skips_missing_observations_and_needs_two_valid_rows(self, mock_get: MagicMock) -> None:
        # "." is FRED's missing-observation marker; it must not become a price.
        mock_get.return_value = _text_response(
            "observation_date,DGS10\n2026-10-28,5.05\n2026-10-29,4.98\n2026-10-30,.\n"
        )
        quote = fetch_fred_series_quote("^TNX", "INDEX")
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "2026-10-29")

        mock_get.return_value = _text_response("observation_date,DGS10\n2026-10-29,4.98\n")
        self.assertIsNone(fetch_fred_series_quote("^TNX", "INDEX"))


class SinaGlobalQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_parses_diniw_dollar_index_fields(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(DINIW_PAYLOAD)

        quote = fetch_sina_global_quote("DX-Y.NYB", "FX")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 101.9669)
        self.assertEqual(quote["previousClose"], 101.9669)
        self.assertEqual(quote["change"], 0.0)
        self.assertEqual(quote["open"], 101.8857)
        self.assertEqual(quote["dayHigh"], 102.0903)
        self.assertEqual(quote["dayLow"], 101.5851)
        self.assertIsNone(quote["volume"])
        # 周六快照（2026-10-31）回滚到周五最后交易日。
        self.assertEqual(quote["tradeDate"], "2026-10-30")
        self.assertEqual(quote["source"], "sina")

    @patch("fetch_market_data.requests.get")
    def test_computes_change_against_last_settlement(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(XAU_PAYLOAD)

        quote = fetch_sina_global_quote("XAUUSD=X", "CMDTY")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 3876.69)
        self.assertEqual(quote["previousClose"], 4021.23)
        self.assertEqual(quote["change"], -144.54)
        self.assertAlmostEqual(quote["changesPercentage"], -144.54 / 4021.23 * 100, places=6)
        self.assertEqual(quote["open"], 4023.79)
        self.assertEqual(quote["dayHigh"], 4026.24)
        self.assertEqual(quote["dayLow"], 3870.05)
        self.assertEqual(quote["tradeDate"], "2026-10-30")

    @patch("fetch_market_data.requests.get")
    def test_tolerates_empty_cell_and_extra_column_in_hf_feed(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(CAD_PAYLOAD)

        quote = fetch_sina_global_quote("HG=F", "CMDTY")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 14128.16)
        self.assertEqual(quote["previousClose"], 14154.50)
        self.assertEqual(quote["change"], -26.34)
        self.assertEqual(quote["open"], 14310.00)
        self.assertEqual(quote["dayHigh"], 14361.00)
        self.assertEqual(quote["dayLow"], 14107.00)
        # hf_ 分支同样回滚周六快照（2026-10-31 -> 周五）。
        self.assertEqual(quote["tradeDate"], "2026-10-30")

    @patch("fetch_market_data.requests.get")
    def test_stays_https_with_referer_and_gates_non_mapped(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(DINIW_PAYLOAD)
        fetch_sina_global_quote("DX-Y.NYB", "FX")
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "sina global endpoint must stay HTTPS",
        )
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["Referer"],
            "https://finance.sina.com.cn",
        )

        self.assertIsNone(fetch_sina_global_quote("^IXIC", "INDEX"))
        self.assertIsNone(fetch_sina_global_quote("000660.KS", "KR"))
        self.assertEqual(mock_get.call_count, 1)

    @patch("fetch_market_data.requests.get")
    def test_weekend_snapshot_rolls_to_friday_weekday_unchanged(self, mock_get: MagicMock) -> None:
        # 周六采集、冻结周五收盘 -> 交易日标周五；周日同理。工作日日期原样保留。
        for snapshot_date, expected in [("2026-10-31", "2026-10-30"),
                                        ("2026-11-01", "2026-10-30"),
                                        ("2026-10-29", "2026-10-29")]:
            with self.subTest(snapshot_date=snapshot_date):
                mock_get.return_value = _text_response(DINIW_PAYLOAD.replace("2026-10-31", snapshot_date))
                quote = fetch_sina_global_quote("DX-Y.NYB", "FX")
                assert quote is not None
                self.assertEqual(quote["tradeDate"], expected)


class EastmoneyGlobalQuoteTests(unittest.TestCase):
    # Real payload from live verification (2026-10-31 KRX close).
    EASTMONEY_GLOBAL_PAYLOAD = {
        "f43": 1418000.0,
        "f44": 1449000.0,
        "f45": 1381000.0,
        "f46": 1444000.0,
        "f47": 4086834,
        "f60": 1526000.0,
        # 2026-10-30 22:30 UTC（= 北京 10-31 06:30）：UTC 与北京分属两天的判别边界。
        "f86": 1793399405,
        "f169": -108000.0,
        "f170": -7.08,
    }

    @patch("fetch_market_data.requests.get")
    def test_normalizes_krx_fields_and_utc_date(self, mock_get: MagicMock) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": dict(self.EASTMONEY_GLOBAL_PAYLOAD)}
        mock_get.return_value = response

        quote = fetch_eastmoney_global_quote("000660.KS", "KR")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 1418000.0)
        self.assertEqual(quote["changesPercentage"], -7.08)
        self.assertEqual(quote["previousClose"], 1526000.0)
        # KRX 周五收盘落在 UTC 晚间 = 北京周六凌晨：UTC 口径应得 10-30，
        # 若实现误用北京时区会得到 10-31 —— fixture 刻意踩在这条分界线上。
        self.assertEqual(quote["tradeDate"], "2026-10-30")
        self.assertEqual(quote["source"], "eastmoney")
        self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], "177.000660")
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "eastmoney global endpoint must stay HTTPS",
        )

    @patch("fetch_market_data.requests.get")
    def test_null_data_payload_returns_none(self, mock_get: MagicMock) -> None:
        # 东财对无效 secid 等场景返回 data:null——必须安全落到 None，不产出空行情。
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": None}
        mock_get.return_value = response

        self.assertIsNone(fetch_eastmoney_global_quote("000660.KS", "KR"))

    @patch("fetch_market_data.requests.get")
    def test_secid_mapping_for_each_venue(self, mock_get: MagicMock) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": dict(self.EASTMONEY_GLOBAL_PAYLOAD)}
        mock_get.return_value = response

        for ticker, secid in (
            ("HG=F", "109.LCPT"),
            ("^SOX", "251.SOX"),
            ("^IXIC", "100.NDX"),
        ):
            fetch_eastmoney_global_quote(ticker, "INDEX")
            self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], secid)

    @patch("fetch_market_data.requests.get")
    def test_cn_000660_sz_never_routes_to_krx(self, mock_get: MagicMock) -> None:
        # Suffix stripping must NOT decide the route here: 000660.SZ (铜陵有色)
        # shares its code with KR 000660 (SK hynix).
        self.assertIsNone(fetch_eastmoney_global_quote("000660.SZ", "CN"))
        self.assertIsNone(fetch_eastmoney_global_quote("600276.SH", "CN"))
        mock_get.assert_not_called()


class GlobalChainRoutingTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_tnx_routes_to_fred_in_the_chain(self, mock_get: MagicMock) -> None:
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "fred.stlouisfed.org" in url:
                return _text_response(FRED_CSV)
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "^TNX", "market": "INDEX"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "fred")

    @patch("fetch_market_data.requests.get")
    def test_spot_gold_routes_to_sina_global_in_the_chain(self, mock_get: MagicMock) -> None:
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "hq.sinajs.cn" in url:
                assert "hf_XAU" in url
                return _text_response(XAU_PAYLOAD)
            if "api.nasdaq.com" in url:
                raise AssertionError("^IXIC-style stocks endpoint must not serve spot gold")
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "XAUUSD=X", "market": "CMDTY"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "sina")
        self.assertEqual(quote["price"], 3876.69)

    @patch("fetch_market_data.requests.get")
    def test_krx_ticker_routes_to_eastmoney_global_in_the_chain(self, mock_get: MagicMock) -> None:
        def dispatch(url: str, **kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url:
                params = kwargs.get("params") or {}
                assert params.get("secid") == "177.000660", params
                response = MagicMock()
                response.raise_for_status.return_value = None
                response.json.return_value = {
                    "data": dict(EastmoneyGlobalQuoteTests.EASTMONEY_GLOBAL_PAYLOAD)
                }
                return response
            if "hq.sinajs.cn" in url:
                raise AssertionError("000660.KS is not a sina global code")
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "000660.KS", "market": "KR"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "eastmoney")
        self.assertEqual(quote["changesPercentage"], -7.08)


if __name__ == "__main__":
    unittest.main()
