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
    fetch_cnbc_quote,
    fetch_eastmoney_global_quote,
    fetch_fallback_quote,
    fetch_fred_series_quote,
    fetch_nasdaq_index_quote,
    fetch_sina_bond_quote,
    fetch_sina_global_quote,
    fetch_tencent_global_quote,
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
# 原油/纳指期货 fixtures（2026-11-26 live probe，字段位保留真实位；field 1
# 新浪恒空、腾讯填涨跌幅%——解析器一律不锚它，change 自算）。
CL_PAYLOAD_SINA = (
    'var hq_str_hf_CL="84.039,,84.09,84.10,84.48,83.80,09:30:00,83.68,84.09,0,0,0,'
    '2026-11-25,WTI原油";'
)
CL_PAYLOAD_TENCENT = (
    'v_hf_CL="84.04,0.43,84.09,84.10,84.48,83.80,09:30:00,83.68,84.09,0,0,0,'
    '2026-11-25,WTI原油";'
)
BZ_PAYLOAD_SINA = (
    'var hq_str_hf_OIL="90.828,,90.90,90.95,91.10,90.35,09:30:00,90.64,90.90,0,0,0,'
    '2026-11-25,布伦特原油";'
)
NQ_PAYLOAD_SINA = (
    'var hq_str_hf_NQ="26286.77,,26288.00,26290.00,26350.00,26080.00,09:30:00,'
    '26100.25,26200.00,0,0,0,2026-11-25,纳指连续";'
)
# CNBC quote.htm（Tradeweb 美十债，% 原值非雅虎 ×10 指数）；last_time 带 ET 偏移，
# tradeDate 取其日期段。
CNBC_PAYLOAD = {
    "QuickQuoteResult": {
        "QuickQuote": [
            {
                "symbol": "US10Y",
                "name": "US 10 YR",
                "last": "4.864",
                "change": "-0.038",
                "change_pct": "-0.775",
                "previous_day_closing": "4.902",
                "open": "4.900",
                "high": "4.912",
                "low": "4.850",
                "last_time": "2026-11-25T17:05:00.000-0500",
            }
        ]
    }
}
# globalbd 布局：0=名称 1=今开 2=昨收 3=最新 4=最高 5=最低 6=量 7=涨跌幅% 8=涨跌
# 9/10=买卖(恒0) 11=unix ts 12=日期 13=时间。ts=1795656000=2026-11-26 01:20 UTC
# （北京 09:20 快照）。
GLOBALBD_PAYLOAD = (
    'var hq_str_globalbd_usg10y="美国10年期国债收益率,4.899,4.844,4.886,4.894,4.799,'
    '0,0.87,0.042,0,0,1795656000,2026-11-26,09:20:00";'
)


def _cnbc_payload(last: str = "4.864") -> dict:
    payload = {
        "QuickQuoteResult": {"QuickQuote": [dict(CNBC_PAYLOAD["QuickQuoteResult"]["QuickQuote"][0])]}
    }
    payload["QuickQuoteResult"]["QuickQuote"][0]["last"] = last
    return payload


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


class CrudeHfQuoteTests(unittest.TestCase):
    """CL=F/BZ=F/NQ00Y 新浪 hf_ 族（2026-11-26 接线，东财断连当日缺口回归）。"""

    @patch("fetch_market_data.requests.get")
    def test_parses_wti_fields_against_last_settlement(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(CL_PAYLOAD_SINA)

        quote = fetch_sina_global_quote("CL=F", "CMDTY")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 84.039)
        self.assertEqual(quote["previousClose"], 83.68)  # 昨结
        self.assertEqual(quote["change"], 0.359)
        self.assertAlmostEqual(quote["changesPercentage"], 0.359 / 83.68 * 100, places=6)
        self.assertEqual(quote["open"], 84.09)
        self.assertEqual(quote["dayHigh"], 84.48)
        self.assertEqual(quote["dayLow"], 83.80)
        self.assertIsNone(quote["volume"])
        self.assertEqual(quote["tradeDate"], "2026-11-25")  # 工作日原样
        self.assertEqual(quote["source"], "sina")

    @patch("fetch_market_data.requests.get")
    def test_parses_brent_and_nq_continuous(self, mock_get: MagicMock) -> None:
        for payload, ticker, price, settle in (
            (BZ_PAYLOAD_SINA, "BZ=F", 90.828, 90.64),
            (NQ_PAYLOAD_SINA, "NQ00Y", 26286.77, 26100.25),
        ):
            with self.subTest(ticker=ticker):
                mock_get.return_value = _text_response(payload)
                quote = fetch_sina_global_quote(ticker, "INDEX")
                assert quote is not None
                self.assertEqual(quote["price"], price)
                self.assertEqual(quote["previousClose"], settle)
                self.assertEqual(quote["change"], round(price - settle, 6))
                self.assertEqual(quote["tradeDate"], "2026-11-25")

    @patch("fetch_market_data.requests.get")
    def test_weekend_snapshot_rolls_wti_to_friday(self, mock_get: MagicMock) -> None:
        # 周六采集（11-28）冻结周五收盘 -> 交易日标 11-27；与 DINIW/XAU 同款回滚。
        mock_get.return_value = _text_response(CL_PAYLOAD_SINA.replace("2026-11-25", "2026-11-28"))
        quote = fetch_sina_global_quote("CL=F", "CMDTY")
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "2026-11-27")


class TencentGlobalQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_shares_hf_layout_and_ignores_vendor_change_pct_field(self, mock_get: MagicMock) -> None:
        # 腾讯 field 1=涨跌幅%（0.43=0.36/83.68 自洽）——未文档化字段不作锚，
        # change 仍按昨结自算；布局与新浪逐字段同位，同一份解析。
        mock_get.return_value = _text_response(CL_PAYLOAD_TENCENT)

        quote = fetch_tencent_global_quote("CL=F", "CMDTY")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 84.04)  # 腾讯 2 位小数（新浪 3 位）
        self.assertEqual(quote["previousClose"], 83.68)
        self.assertEqual(quote["change"], 0.36)
        self.assertAlmostEqual(quote["changesPercentage"], 0.36 / 83.68 * 100, places=6)
        self.assertEqual(quote["source"], "tencent")
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://qt.gtimg.cn"),
            "tencent global endpoint must stay HTTPS",
        )
        self.assertIn("hf_CL", str(mock_get.call_args.args[0]))

    @patch("fetch_market_data.requests.get")
    def test_stays_https_with_referer_and_gates_non_mapped(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(CL_PAYLOAD_TENCENT)
        fetch_tencent_global_quote("CL=F", "CMDTY")
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["Referer"], "http://finance.qq.com"
        )
        # 腾讯不代理 hf_NQ / DINIW（2026-11-26 批量实测丢行）：NQ00Y、美元指数无腾讯备份
        self.assertIsNone(fetch_tencent_global_quote("NQ00Y", "INDEX"))
        self.assertIsNone(fetch_tencent_global_quote("DX-Y.NYB", "FX"))
        self.assertEqual(mock_get.call_count, 1)

    @patch("fetch_market_data.requests.get")
    def test_truncated_or_zero_price_payload_returns_none(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response('v_hf_CL="84.04,0.43";')
        self.assertIsNone(fetch_tencent_global_quote("CL=F", "CMDTY"))
        mock_get.return_value = _text_response(CL_PAYLOAD_TENCENT.replace("84.04,0.43", "0,0"))
        self.assertIsNone(fetch_tencent_global_quote("CL=F", "CMDTY"))
        self.assertEqual(mock_get.call_count, 2)


class CnbcQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_parses_us10y_session_fields(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _json_response(_cnbc_payload())

        quote = fetch_cnbc_quote("^TNX", "INDEX")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 4.864)
        self.assertEqual(quote["change"], -0.038)
        self.assertEqual(quote["changesPercentage"], -0.775)
        self.assertEqual(quote["previousClose"], 4.902)
        self.assertEqual(quote["open"], 4.900)
        self.assertEqual(quote["dayHigh"], 4.912)
        self.assertEqual(quote["dayLow"], 4.850)
        self.assertIsNone(quote["volume"])
        # last_time 的 ET 日期段 -> tradeDate（美盘收盘对收盘口径）。
        self.assertEqual(quote["tradeDate"], "2026-11-25")
        self.assertEqual(quote["source"], "cnbc")
        self.assertEqual(mock_get.call_args.kwargs["params"]["symbols"], "US10Y")
        # 裸 curl 无 UA 时 http=000：浏览器 UA 必须始终携带。
        self.assertTrue(mock_get.call_args.kwargs["headers"].get("User-Agent"))
        self.assertTrue(
            str(mock_get.call_args.args[0]).startswith("https://"),
            "cnbc endpoint must stay HTTPS",
        )

    @patch("fetch_market_data.requests.get")
    def test_rejects_non_percent_yield_scales(self, mock_get: MagicMock) -> None:
        # ×10 指数（48.64）与债券净价（98.5）都越出 % 原值防呆区间：拒收不落快照。
        for bad_last in ("48.64", "98.5"):
            mock_get.return_value = _json_response(_cnbc_payload(bad_last))
            self.assertIsNone(fetch_cnbc_quote("^TNX", "INDEX"))
        self.assertEqual(mock_get.call_count, 2)

    @patch("fetch_market_data.requests.get")
    def test_malformed_shapes_return_none(self, mock_get: MagicMock) -> None:
        for payload in ({}, {"QuickQuoteResult": {}}, {"QuickQuoteResult": {"QuickQuote": []}}):
            mock_get.return_value = _json_response(payload)
            self.assertIsNone(fetch_cnbc_quote("^TNX", "INDEX"))
        self.assertEqual(mock_get.call_count, 3)

    @patch("fetch_market_data.requests.get")
    def test_only_mapped_tickers_reach_cnbc(self, mock_get: MagicMock) -> None:
        self.assertIsNone(fetch_cnbc_quote("NQ00Y", "INDEX"))
        self.assertIsNone(fetch_cnbc_quote("CL=F", "CMDTY"))
        mock_get.assert_not_called()


class SinaBondQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_returns_level_only_beijing_day_cut_trap(self, mock_get: MagicMock) -> None:
        # 北京日切陷阱：该族昨收/涨跌=北京日尾对北京日尾（11-25 样本 +4.2bp vs
        # 美盘真变动 -3.8bp，符号相反），且 gcny10 样本高低字段自相矛盾——
        # 只透传水平，delta/OHLC 一律 None（报告侧显示「—」）。
        mock_get.return_value = _text_response(GLOBALBD_PAYLOAD)

        quote = fetch_sina_bond_quote("^TNX", "INDEX")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 4.886)
        self.assertEqual(quote["tradeDate"], "2026-11-26")  # unix ts 的 UTC 日
        self.assertEqual(quote["source"], "sina-bond")
        for key in ("change", "changesPercentage", "previousClose",
                    "open", "dayHigh", "dayLow", "volume"):
            self.assertIsNone(quote[key], key)
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["Referer"], "https://finance.sina.com.cn"
        )

    @patch("fetch_market_data.requests.get")
    def test_unparseable_timestamp_falls_back_to_date_field(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(GLOBALBD_PAYLOAD.replace("1795656000", "0"))
        quote = fetch_sina_bond_quote("^TNX", "INDEX")
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "2026-11-26")

    @patch("fetch_market_data.requests.get")
    def test_rejects_non_percent_and_gates_unmapped(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(GLOBALBD_PAYLOAD.replace(",4.886,", ",48.86,"))
        self.assertIsNone(fetch_sina_bond_quote("^TNX", "INDEX"))
        self.assertIsNone(fetch_sina_bond_quote("CL=F", "CMDTY"))
        self.assertEqual(mock_get.call_count, 1)


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

    @patch("fetch_market_data.requests.get")
    def test_tnx_eastmoney_down_cnbc_takes_over(self, mock_get: MagicMock) -> None:
        # 2026-11-26 盘前断连回归：东财 push2 挂 -> CNBC（Tradeweb 实时，
        # 美盘收盘对收盘口径）接管；FRED T+1 只当最后兜底。
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url:
                raise RuntimeError("RemoteDisconnected")
            if "quote.cnbc.com" in url:
                return _json_response(_cnbc_payload())
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "^TNX", "market": "INDEX"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "cnbc")
        self.assertEqual(quote["price"], 4.864)
        self.assertEqual(quote["change"], -0.038)
        # 新浪/腾讯对 ^TNX 无映射（零请求），链路就地停在 cnbc：不落 sina-bond/fred。
        urls = " ".join(str(c.args[0]) for c in mock_get.call_args_list)
        self.assertNotIn("hq.sinajs.cn", urls)
        self.assertNotIn("qt.gtimg.cn", urls)
        self.assertNotIn("fred.stlouisfed.org", urls)

    @patch("fetch_market_data.requests.get")
    def test_tnx_all_realtime_down_sina_bond_serves_level_only(self, mock_get: MagicMock) -> None:
        # 东财+CNBC 双挂 -> 新浪 globalbd 兜底：只给水平（change None），不到 FRED。
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url or "quote.cnbc.com" in url:
                raise RuntimeError("down")
            if "hq.sinajs.cn" in url:
                assert "globalbd_usg10y" in url
                return _text_response(GLOBALBD_PAYLOAD)
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "^TNX", "market": "INDEX"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "sina-bond")
        self.assertEqual(quote["price"], 4.886)
        self.assertIsNone(quote["change"])  # 北京日切口径不报告
        self.assertNotIn("fred.stlouisfed.org",
                         " ".join(str(c.args[0]) for c in mock_get.call_args_list))

    @patch("fetch_market_data.requests.get")
    def test_wti_eastmoney_down_sina_takes_over_then_tencent(self, mock_get: MagicMock) -> None:
        # CL=F：东财挂 -> 新浪 hf_CL 接管（今晨缺口回归）；新浪也挂 -> 腾讯
        # 同布局 hf_CL 兜底（两家 keyless vendor 同挂才双双失守）。
        def sina_up_dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url:
                raise RuntimeError("RemoteDisconnected")
            if "hq.sinajs.cn" in url:
                assert "hf_CL" in url
                return _text_response(CL_PAYLOAD_SINA)
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = sina_up_dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "CL=F", "market": "CMDTY"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "sina")
        self.assertEqual(quote["price"], 84.039)
        urls = " ".join(str(c.args[0]) for c in mock_get.call_args_list)
        self.assertNotIn("qt.gtimg.cn", urls)
        self.assertNotIn("fred.stlouisfed.org", urls)

        def all_down_dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url or "hq.sinajs.cn" in url:
                raise RuntimeError("down")
            assert "qt.gtimg.cn" in url, url
            return _text_response(CL_PAYLOAD_TENCENT)

        mock_get.side_effect = all_down_dispatch

        quote = fetch_fallback_quote({"ticker": "CL=F", "market": "CMDTY"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "tencent")
        self.assertEqual(quote["price"], 84.04)

    @patch("fetch_market_data.requests.get")
    def test_nq00y_eastmoney_down_sina_hf_takes_over(self, mock_get: MagicMock) -> None:
        # NQ00Y 原为东财单源断连即 miss（今晨缺口之一）；新浪 hf_NQ 接线后接管。
        # 腾讯无此映射，链路必须停在新浪、不落 fred。
        def dispatch(url: str, **_kwargs: object) -> MagicMock:
            if "push2.eastmoney.com" in url:
                raise RuntimeError("RemoteDisconnected")
            if "hq.sinajs.cn" in url:
                assert "hf_NQ" in url
                return _text_response(NQ_PAYLOAD_SINA)
            raise AssertionError(f"unexpected request to {url}")

        mock_get.side_effect = dispatch
        env = {"FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": ""}

        quote = fetch_fallback_quote({"ticker": "NQ00Y", "market": "INDEX"}, env)

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "sina")
        self.assertEqual(quote["price"], 26286.77)
        self.assertEqual(quote["previousClose"], 26100.25)
        urls = " ".join(str(c.args[0]) for c in mock_get.call_args_list)
        self.assertNotIn("qt.gtimg.cn", urls)


if __name__ == "__main__":
    unittest.main()
