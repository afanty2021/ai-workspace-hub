"""Eastmoney / Tencent / Sina keyless CN fallback sources.

Field maps mirror the endpoints' actual payload layout (verified against a
sibling project's production usage); payloads below are minimal but keep the
real field positions so index drift breaks tests instead of reports.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

import fetch_market_data  # noqa: E402
from fetch_market_data import (  # noqa: E402
    _cn_quote_symbol,
    _us_quote_symbol,
    DEFAULT_THRESHOLDS,
    build_quote_record,
    build_snapshot,
    fetch_eastmoney_quote,
    fetch_fallback_quote,
    fetch_sina_quote,
    fetch_tencent_quote,
    get_cached_tushare_client,
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
# Same ~-layout as CN but timestamp is 'YYYY/MM/DD HH:MM:SS' (live: hk03800).
TENCENT_HK_PAYLOAD = (
    'v_hk03800="100~协鑫科技~03800~0.640~0.660~0.645~152697900~x~x~0.640~x~x~x~x'
    '~x~x~x~x~x~x~x~x~x~x~x~x~x~x~x~x~2026/11/06 16:08:54~-0.020~-3.03~0.675~0.630";'
)
# Same layout for US equities (live: usFCX, probe 2026-11-08). Timestamp is
# 'YYYY-MM-DD HH:MM:SS' (ET); volume in shares; fields 35+ carry the USD
# marker(35) / PE(39) / market cap(44/45, $mn) / EPS(47) / PB(51) / div%(52)
# which the fetcher deliberately ignores — all kept here at real probed
# values so the fixture mirrors the live 73-field layout.
TENCENT_US_PAYLOAD = (
    'v_usFCX="200~自由港麦克莫兰~FCX.N~59.42~57.90~59.09~16248755~x~x~59.65'
    + "~x" * 20
    + '~2026-11-06 16:03:41~1.52~2.63~60.52~58.30~USD~16248755~967400696~x~24.97'
    '~x~39.09~x~3.83~848.88379~853.28161~Freeport-McMoRan Inc~2.38~80.09~38.15'
    '~0~4.07~1.01";'
)
# Exactly 34 fields (< the len>=35 gate): fields[30..33] are placeholders, so
# a gate regression (35 -> 30) would let this parse instead of rejecting.
TENCENT_US_TRUNCATED_PAYLOAD = (
    'v_usFCX="200~x~FCX.N~59.42~57.90~59.09~16248755' + "~x" * 27 + '";'
)
EASTMONEY_PAYLOAD = {
    "data": {
        "f43": 48.36,
        "f44": 49.00,
        "f45": 45.80,
        "f46": 46.00,
        "f47": 123456,
        "f60": 45.55,
        "f86": 1774569600,
        "f169": 2.81,
        "f170": 6.17,
    }
}
# Live HK shape with fltt=2 (116.03800): plain decimals, same as CN —
# f43=0.64 HKD. Without fltt the same endpoint returns per-mille integers
# (640/-20/-303); the fetcher always sends fltt=2, so no rescaling here.
EASTMONEY_HK_PAYLOAD = {
    "data": {
        "f43": 0.64,
        "f44": 0.675,
        "f45": 0.63,
        "f46": 0.645,
        "f47": 152697900,
        "f60": 0.66,
        "f86": 1793952531,
        "f169": -0.02,
        "f170": -3.03,
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

    def test_us_symbols_gate_on_market_and_reject_dots(self) -> None:
        self.assertEqual(_us_quote_symbol("NVDA", "US"), "NVDA")
        self.assertEqual(_us_quote_symbol("nvda", "US"), "NVDA")
        # Gate on the market column, not the bare-ticker shape: on any other
        # market a bare US ticker must not leak into a us* request.
        self.assertIsNone(_us_quote_symbol("NVDA", "CN"))
        self.assertIsNone(_us_quote_symbol("NVDA", ""))
        # Dotted class tickers (BRK.B) have an unverified Tencent encoding.
        self.assertIsNone(_us_quote_symbol("BRK.B", "US"))
        # Documented tradeoff: a purely numeric base on a US row (mismatched
        # watchlist input, e.g. 600276) passes isalnum and only produces an
        # empty us600276 probe — kept for parity with fetch_nasdaq_quote's
        # handling of the same mismatched row rather than special-cased here.
        self.assertEqual(_us_quote_symbol("600276", "US"), "600276")

    def test_hk_codes_require_five_digits(self) -> None:
        # HKEX codes are 5-digit zero-padded (03800); shorter legacy forms (0700)
        # stay rejected so a malformed ticker can never hit the 116 secid map.
        from fetch_market_data import _hk_quote_code

        self.assertEqual(_hk_quote_code("03800.HK"), "03800")
        self.assertIsNone(_hk_quote_code("0700.HK"))
        self.assertIsNone(_hk_quote_code("600276.SH"))
        self.assertIsNone(_hk_quote_code("AAPL"))


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

    @patch("fetch_market_data.requests.get")
    def test_hk_ticker_parses_fltt2_decimal_fields_unscaled(self, mock_get: MagicMock) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = EASTMONEY_HK_PAYLOAD
        mock_get.return_value = response

        quote = fetch_eastmoney_quote("03800.HK", "HK")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 0.64)
        self.assertEqual(quote["change"], -0.02)
        self.assertEqual(quote["changesPercentage"], -3.03)
        self.assertEqual(quote["previousClose"], 0.66)
        self.assertEqual(quote["open"], 0.645)
        self.assertEqual(quote["dayHigh"], 0.675)
        self.assertEqual(quote["dayLow"], 0.63)
        self.assertEqual(quote["volume"], 152697900)
        self.assertEqual(quote["source"], "eastmoney")
        self.assertRegex(quote["tradeDate"], r"^\d{4}-\d{2}-\d{2}$")
        # 5-digit HKEX code rides the 116 market prefix (not 0/1 like CN).
        self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], "116.03800")

    @patch("fetch_market_data.requests.get")
    def test_short_hk_code_is_rejected_without_request(self, mock_get: MagicMock) -> None:
        self.assertIsNone(fetch_eastmoney_quote("0700.HK", "HK"))
        mock_get.assert_not_called()


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
    def test_hk_ticker_maps_to_hk_prefix_and_slash_date(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_HK_PAYLOAD)

        quote = fetch_tencent_quote("03800.HK", "HK")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 0.64)
        self.assertEqual(quote["change"], -0.02)
        self.assertEqual(quote["changesPercentage"], -3.03)
        self.assertEqual(quote["previousClose"], 0.66)
        self.assertEqual(quote["dayHigh"], 0.675)
        self.assertEqual(quote["dayLow"], 0.63)
        # 'YYYY/MM/DD HH:MM:SS' normalizes to ISO, not the CN [:8] slice.
        self.assertEqual(quote["tradeDate"], "2026-11-06")
        self.assertEqual(quote["source"], "tencent")
        self.assertIn("q=hk03800", str(mock_get.call_args))

    @patch("fetch_market_data.requests.get")
    def test_us_ticker_maps_to_us_prefix_and_iso_date(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_US_PAYLOAD)

        # Lowercase input locks the .upper() normalization at the symbol
        # assembly layer too (not just inside _us_quote_symbol).
        quote = fetch_tencent_quote("fcx", "US")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 59.42)
        self.assertEqual(quote["change"], 1.52)
        self.assertEqual(quote["changesPercentage"], 2.63)
        self.assertEqual(quote["previousClose"], 57.90)
        self.assertEqual(quote["dayHigh"], 60.52)
        self.assertEqual(quote["dayLow"], 58.30)
        self.assertEqual(quote["volume"], 16248755)
        # US timestamps are 'YYYY-MM-DD HH:MM:SS' (ET) — ISO slice, not CN [:8].
        self.assertEqual(quote["tradeDate"], "2026-11-06")
        self.assertEqual(quote["source"], "tencent")
        self.assertIn("q=usFCX", str(mock_get.call_args))

    @patch("fetch_market_data.requests.get")
    def test_truncated_us_payload_is_rejected_cleanly(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_US_TRUNCATED_PAYLOAD)
        # 34 fields (< 35 gate): rejection must be the clean length check, not
        # an IndexError on fields[34] swallowed by the except handler. The two
        # paths are externally identical (both -> None), so the discriminator
        # is _note_fetch_failure: only the exception path records a failure.
        # A gate regression (35 -> 30) flips this to the exception path.
        with patch("fetch_market_data._note_fetch_failure") as mock_note:
            self.assertIsNone(fetch_tencent_quote("FCX", "US"))
        mock_note.assert_not_called()

    @patch("fetch_market_data.requests.get")
    def test_us_ticker_requires_us_market_gate(self, mock_get: MagicMock) -> None:
        # Without the market gate a bare US ticker on any market row hits the
        # us branch directly and fires a us* request — assert_not_called locks
        # exactly that regression (verified red under gate-removal mutation).
        self.assertIsNone(fetch_tencent_quote("NVDA", "CN"))
        self.assertIsNone(fetch_tencent_quote("NVDA", ""))
        mock_get.assert_not_called()

    @patch("fetch_market_data.requests.get")
    def test_dotted_us_class_ticker_is_rejected_without_request(self, mock_get: MagicMock) -> None:
        self.assertIsNone(fetch_tencent_quote("BRK.B", "US"))
        mock_get.assert_not_called()

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


class MootdxOutageDegradationTests(unittest.TestCase):
    """mootdx 全网不可用时 build_snapshot 必须优雅降级，不得让整份日报 fail。

    mock 边界：批量与按票 mootdx 全部抛错（模拟负缓存快速失败），
    链内 tushare 用 dummy client + patch 掉单票请求——这样 missing 票
    会真实穿过 fallback 链（mootdx 按票重试 → tushare），而不是被
    批量层 mock 提前截走。
    """

    def test_mootdx_batch_failure_falls_through_chain_to_tushare(self) -> None:
        watchlist = [
            {
                "ticker": "600276.SH",
                "name": "恒瑞医药",
                "market": "CN",
                "market_cap": "Large",
                "category": "医药",
            }
        ]
        tushare_raw = {
            "symbol": "600276.SH",
            "price": 48.46,
            "changesPercentage": 0.0,
            "tradeDate": "20261030",
            "source": "tushare",
        }
        with (
            patch(
                "fetch_market_data.fetch_mootdx_quotes",
                side_effect=RuntimeError("mootdx 通达信服务器不可用（模拟批量）"),
            ),
            # 按票重试同样快速失败——patch 掉防止真实联网
            patch(
                "fetch_market_data.fetch_mootdx_quote",
                side_effect=RuntimeError("mootdx 通达信服务器不可用（模拟按票）"),
            ),
            patch("fetch_market_data.fetch_fmp_quotes", return_value=[]),
            # 主源层 tushare 本来就空（CN 票路由给了 mootdx）；返回 [] 保真
            patch("fetch_market_data.fetch_tushare_quotes", return_value=[]),
            # 链内 tushare：dummy client + 单票请求 patch
            patch("fetch_market_data.get_cached_tushare_client", return_value=object()),
            patch("fetch_market_data.fetch_tushare_quote", return_value=tushare_raw),
        ):
            snapshot = build_snapshot(
                watchlist=watchlist,
                api_key="",
                tushare_token="dummy-token",
                env={"TUSHARE_TOKEN": "dummy-token", "DISABLE_MOOTDX": ""},
                thresholds=DEFAULT_THRESHOLDS,
                max_workers=2,
                include_earnings=False,
            )

        self.assertEqual(snapshot["meta"]["quotes"]["state"], "ok")
        self.assertEqual(snapshot["meta"]["quotes"]["missing_tickers"], [])
        self.assertEqual(len(snapshot["quotes"]), 1)
        # 票真实穿过 fallback 链后由 tushare 接住。
        self.assertEqual(snapshot["quotes"][0]["source"], "tushare")
        self.assertEqual(snapshot["quotes"][0]["tradeDate"], "2026-10-30")


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
    @patch("fetch_market_data.fetch_mootdx_quote", return_value=None)
    @patch("fetch_market_data.requests.get")
    def test_cn_ticker_falls_through_eastmoney_to_tencent(self, mock_get: MagicMock, _mock_mootdx: MagicMock) -> None:
        # mootdx 升主源后，降级链里 CN 票先按票重试 mootdx（这里模拟未命中），
        # 再 tushare（无 token 跳过）→ 东财 → 腾讯。本测试锁定东财挂时腾讯兜底。
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
    def test_cn_ticker_tries_mootdx_before_cn_fallbacks(self, mock_get: MagicMock) -> None:
        # mootdx 按票重试命中时，链条就地停住：任何 HTTP 端点都不该被碰。
        with patch(
            "fetch_market_data.fetch_mootdx_quote",
            return_value={"symbol": "600276.SH", "price": 48.0, "source": "mootdx"},
        ):
            quote = fetch_fallback_quote(
                {"ticker": "600276.SH", "market": "CN"},
                {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""},
            )

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "mootdx")
        mock_get.assert_not_called()

    @patch("fetch_market_data.requests.get")
    def test_disable_mootdx_env_skips_the_mootdx_retry(self, mock_get: MagicMock) -> None:
        # DISABLE_MOOTDX=1 时按票重试必须被跳过（连调用都不发生），直接落 tushare
        # （无 token）→ 东财。
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            assert "push2.eastmoney.com" in url
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"data": {"f43": 48.36, "f60": 45.55}}
            return response

        mock_get.side_effect = dispatch
        with patch(
            "fetch_market_data.fetch_mootdx_quote",
            side_effect=AssertionError("mootdx must not be called when disabled"),
        ) as mock_mootdx:
            quote = fetch_fallback_quote(
                {"ticker": "600276.SH", "market": "CN"},
                {
                    "FINNHUB_API_KEY": "",
                    "EOD_API_KEY": "",
                    "ENABLE_YFINANCE": "",
                    "DISABLE_MOOTDX": "1",
                },
            )

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "eastmoney")
        mock_mootdx.assert_not_called()

    @patch("fetch_market_data.requests.get")
    def test_us_ticker_tencent_is_the_keyless_backup_after_nasdaq(self, mock_get: MagicMock) -> None:
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        def _route(url, **_kwargs):
            url = str(url)
            if "nasdaq" in url:
                resp = MagicMock()
                resp.raise_for_status.return_value = None
                resp.json.return_value = {"data": None}
                return resp
            if "gtimg" in url:
                return _text_response(TENCENT_US_PAYLOAD)
            raise AssertionError(f"unexpected endpoint requested for US ticker: {url}")

        mock_get.side_effect = _route
        with patch("fetch_market_data.fetch_mootdx_quote", return_value=None):
            quote = fetch_fallback_quote({"ticker": "FCX", "market": "US"}, env)

        # Keyless US chain since 2026-11-08: nasdaq -> tencent (us prefix).
        # Eastmoney's US 105/106 codes stay unwired and sina stays CN-only, so
        # those endpoints must still never see a US ticker.
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "tencent")
        self.assertEqual(quote["price"], 59.42)
        requested = [str(c.args[0] if c.args else c.kwargs.get("url", "")) for c in mock_get.call_args_list]
        self.assertTrue(any("api.nasdaq.com" in u for u in requested))
        self.assertTrue(any("gtimg.cn" in u for u in requested))
        # Whitelist, not blacklist: every fetcher wraps exceptions, so the
        # _route AssertionError sentinel only surfaces as a swallowed warning
        # log — an unexpected endpoint (e.g. fred via a map-gate regression)
        # would stay silent under a blacklist-only check. The exact count
        # locks both order and completeness.
        for url in requested:
            self.assertTrue(
                "api.nasdaq.com" in url or "gtimg.cn" in url,
                f"unexpected endpoint requested for US ticker: {url}",
            )
        self.assertEqual(len(requested), 2)


class CachedTushareClientTests(unittest.TestCase):
    """get_cached_tushare_client 的缓存语义：token 键控复用、换 token 重建、失败不缓存。"""

    def setUp(self) -> None:
        # 模块级缓存会跨用例泄漏，每个用例从空缓存起步。
        fetch_market_data._TUSHARE_CLIENT_CACHE.clear()

    def test_empty_token_returns_none_without_loading(self) -> None:
        with patch("fetch_market_data.load_tushare_client") as mock_load:
            self.assertIsNone(get_cached_tushare_client(""))
        mock_load.assert_not_called()

    def test_same_token_reuses_the_cached_client(self) -> None:
        sentinel = object()
        with patch(
            "fetch_market_data.load_tushare_client", return_value=sentinel
        ) as mock_load:
            first = get_cached_tushare_client("tok")
            second = get_cached_tushare_client("tok")
        self.assertIs(first, sentinel)
        self.assertIs(second, sentinel)
        self.assertEqual(mock_load.call_count, 1)

    def test_token_change_rebuilds_and_replaces_cache(self) -> None:
        old, new = object(), object()
        with patch(
            "fetch_market_data.load_tushare_client", side_effect=[old, new]
        ) as mock_load:
            self.assertIs(get_cached_tushare_client("tok-a"), old)
            self.assertIs(get_cached_tushare_client("tok-b"), new)
        self.assertEqual(mock_load.call_count, 2)

    def test_failed_init_returns_none_and_retries_next_call(self) -> None:
        # 初始化失败不写缓存：下一次调用重试，而不是钉死在 None。
        with patch(
            "fetch_market_data.load_tushare_client", return_value=None
        ) as mock_load:
            self.assertIsNone(get_cached_tushare_client("tok"))
            self.assertIsNone(get_cached_tushare_client("tok"))
        self.assertEqual(mock_load.call_count, 2)


if __name__ == "__main__":
    unittest.main()
