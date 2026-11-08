"""场外开放式基金（.OF 约定）数据源：tushare fund_nav 主源 + 腾讯 jj 备份。

载荷镜像 2026-11-08 对 021179（易方达产业机遇混合A）的真实抓取：腾讯 jj
布局与股票 35+ 字段完全不同（9 字段），fund_nav 降序全史——夹具保持真实
字段位，索引漂移会让测试先红而不是日报出错。

背景（friction-log 2026-11-08）：TDX 对场外码静默返回错票（021179 实测
映射成四川长虹 600839 全 0 行不报错），_CN_CODE_RE 已收紧为段位白名单；
.OF ticker 在 fetch_fallback_quote 走专用短链，永不进证券行情长链。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from _test_paths import REPO_ROOT  # noqa: F401 (also sets up sys.path)

from fetch_market_data import (  # noqa: E402
    _of_base_code,
    build_quote_record,
    fetch_fallback_quote,
    fetch_tencent_openfund_quote,
    fetch_tushare_openfund_nav,
    is_open_fund_ticker,
)
from mootdx_source import is_mootdx_ticker  # noqa: E402

# 2026-11-08 真实响应（qt.gtimg.cn/q=jj021179，GBK）：
# 0=代码 1=名称 5=单位净值 6=累计净值 7=日涨跌% 8=净值日期。
TENCENT_JJ_PAYLOAD = (
    'v_jj021179="021179~易方达产业机遇混合A~0.0000~0.0000~~2.8052~2.8052~-2.0017~2026-11-06~";'
)
# <9 字段：gate 回归（9 -> 8）会让截断载荷被解析而不是拒绝。
TENCENT_JJ_TRUNCATED_PAYLOAD = 'v_jj021179="021179~名称~0~0~~2.8052";'
# 净值 0（未更新/新基金）：必须拒绝而不是产出 price=0 的记录。
TENCENT_JJ_ZERO_NAV_PAYLOAD = (
    'v_jj021179="021179~名称~0~0~~0.0000~0.0000~0~2026-11-06~";'
)
# 合成夹具（非真实抓取）：单位净值 ≠ 累计净值（已分红基金形状）。真实
# 021179 两值恰好相等（无分红），fields[5]↔fields[6] 索引漂移时上方真实
# 载荷零区分度——本载荷专职锁字段位：price 必须读单位净值位 fields[5]。
TENCENT_JJ_DISTINCT_NAV_PAYLOAD = (
    'v_jj021179="021179~易方达产业机遇混合A~0.0000~0.0000~~2.8052~3.4100~-2.0017~2026-11-06~";'
)

# fund_nav 真实列布局（2026-11-08 实测：降序返回，最新在首行）。
FUND_NAV_FRAME = pd.DataFrame(
    {
        "ts_code": ["021179.OF", "021179.OF", "021179.OF"],
        "ann_date": ["20261106", "20261105", "20261104"],
        "nav_date": ["20261106", "20261105", "20261104"],
        "unit_nav": [2.8052, 2.8625, 2.8094],
        "accum_nav": [2.8052, 2.8625, 2.8094],
    }
)


def _text_response(payload: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = payload
    return response


class OpenFundSymbolTests(unittest.TestCase):
    def test_of_suffix_detection(self) -> None:
        self.assertTrue(is_open_fund_ticker("021179.OF"))
        self.assertTrue(is_open_fund_ticker("021179.of"))  # 大小写不敏感
        self.assertFalse(is_open_fund_ticker("021179"))  # 裸码不识别（防误路由）
        self.assertFalse(is_open_fund_ticker("021179.SZ"))
        self.assertFalse(is_open_fund_ticker("600276.SH"))

    def test_base_code_extraction(self) -> None:
        self.assertEqual(_of_base_code("021179.OF"), "021179")
        self.assertIsNone(_of_base_code("021179"))  # 无后缀
        self.assertIsNone(_of_base_code("21.OF"))  # 不足 6 位
        self.assertIsNone(_of_base_code("021179.SZ"))


class TushareOpenFundNavTests(unittest.TestCase):
    def test_parses_latest_nav_and_computes_change(self) -> None:
        client = MagicMock()
        client.fund_nav.return_value = FUND_NAV_FRAME

        quote = fetch_tushare_openfund_nav(client, "021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        client.fund_nav.assert_called_once_with(ts_code="021179.OF")
        self.assertEqual(quote["source"], "tushare-fund")
        self.assertEqual(quote["price"], 2.8052)
        self.assertEqual(quote["previousClose"], 2.8625)
        # 期望值按夹具自身数值用代码公式自算：2.8052/2.8625-1 = -2.0017%，
        # 与腾讯实测快照 -2.0017% 完全一致——两源独立且对拍干净。
        self.assertAlmostEqual(quote["changesPercentage"], -2.0017, places=3)
        self.assertEqual(quote["tradeDate"], "20261106")
        self.assertIsNone(quote["volume"])  # 场外基金无成交量

    def test_unsorted_input_is_normalized_by_nav_date(self) -> None:
        # API 契约是降序，但按 nav_date 排序防御乱序响应。
        client = MagicMock()
        client.fund_nav.return_value = FUND_NAV_FRAME.iloc[::-1]

        quote = fetch_tushare_openfund_nav(client, "021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "20261106")
        self.assertEqual(quote["price"], 2.8052)

    def test_single_row_still_returns_without_change(self) -> None:
        client = MagicMock()
        client.fund_nav.return_value = FUND_NAV_FRAME.head(1)

        quote = fetch_tushare_openfund_nav(client, "021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertIsNone(quote["previousClose"])
        self.assertIsNone(quote["changesPercentage"])
        self.assertIsNone(quote["previousTradeDate"])

    def test_stale_prev_nav_exposes_previous_trade_date(self) -> None:
        # 净值停发（封闭期/暂停申赎/QDII 延迟披露）：最新两行隔月时
        # changesPercentage 实为期间涨跌而非日涨跌——previousTradeDate
        # 把前值披露日带回，下游可检测 gap 而不是被口径误导。
        client = MagicMock()
        client.fund_nav.return_value = pd.DataFrame(
            {
                "ts_code": ["021179.OF", "021179.OF"],
                "ann_date": ["20261106", "20261009"],
                "nav_date": ["20261106", "20261009"],
                "unit_nav": [2.8052, 2.7434],
            }
        )

        quote = fetch_tushare_openfund_nav(client, "021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "20261106")
        self.assertEqual(quote["previousTradeDate"], "20261009")

    def test_nan_prev_nav_date_yields_none_not_nan_string(self) -> None:
        # 复查 R-2：前值行 nav_date 缺失（None/NaN）时 previousTradeDate
        # 必须是 None——"nan"/"None" 字符串不允许流进快照。
        client = MagicMock()
        client.fund_nav.return_value = pd.DataFrame(
            {
                "ts_code": ["021179.OF", "021179.OF"],
                "ann_date": ["20261106", None],
                "nav_date": ["20261106", None],
                "unit_nav": [2.8052, 2.8625],
            }
        )

        quote = fetch_tushare_openfund_nav(client, "021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["tradeDate"], "20261106")
        self.assertIsNone(quote["previousTradeDate"])

    def test_empty_or_broken_frame_returns_none(self) -> None:
        client = MagicMock()
        client.fund_nav.return_value = pd.DataFrame()
        self.assertIsNone(fetch_tushare_openfund_nav(client, "021179.OF"))

        client.fund_nav.return_value = pd.DataFrame({"foo": [1]})
        self.assertIsNone(fetch_tushare_openfund_nav(client, "021179.OF"))

    def test_api_exception_returns_none_without_raising(self) -> None:
        client = MagicMock()
        client.fund_nav.side_effect = RuntimeError("积分不足")
        self.assertIsNone(fetch_tushare_openfund_nav(client, "021179.OF"))

    def test_non_of_ticker_never_queries(self) -> None:
        client = MagicMock()
        self.assertIsNone(fetch_tushare_openfund_nav(client, "021179"))
        self.assertIsNone(fetch_tushare_openfund_nav(client, "600276.SH"))
        client.fund_nav.assert_not_called()


class TencentOpenFundQuoteTests(unittest.TestCase):
    @patch("fetch_market_data.requests.get")
    def test_parses_jj_payload(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_JJ_PAYLOAD)

        quote = fetch_tencent_openfund_quote("021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        url = mock_get.call_args.args[0]
        self.assertIn("jj021179", url)  # jj 前缀，非 sh/sz
        self.assertEqual(quote["source"], "tencent-fund")
        self.assertEqual(quote["price"], 2.8052)
        self.assertEqual(quote["changesPercentage"], -2.0017)
        self.assertEqual(quote["tradeDate"], "2026-11-06")

    @patch("fetch_market_data.requests.get")
    def test_unit_and_accum_nav_positions_are_distinct_fields(self, mock_get: MagicMock) -> None:
        # 字段位锁：单位净值（fields[5]）≠ 累计净值（fields[6]）时 price 取
        # 前者——解析索引漂到累计位（有分红/拆分的基金会读错净值）时必红。
        mock_get.return_value = _text_response(TENCENT_JJ_DISTINCT_NAV_PAYLOAD)

        quote = fetch_tencent_openfund_quote("021179.OF")

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["price"], 2.8052)
        self.assertNotEqual(quote["price"], 3.4100)

    @patch("fetch_market_data.requests.get")
    def test_truncated_payload_is_rejected(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_JJ_TRUNCATED_PAYLOAD)
        self.assertIsNone(fetch_tencent_openfund_quote("021179.OF"))

    @patch("fetch_market_data.requests.get")
    def test_zero_nav_is_rejected(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _text_response(TENCENT_JJ_ZERO_NAV_PAYLOAD)
        self.assertIsNone(fetch_tencent_openfund_quote("021179.OF"))

    @patch("fetch_market_data.requests.get")
    def test_non_of_ticker_never_requests(self, mock_get: MagicMock) -> None:
        self.assertIsNone(fetch_tencent_openfund_quote("021179"))
        self.assertIsNone(fetch_tencent_openfund_quote("600276.SH"))
        mock_get.assert_not_called()


class OpenFundFallbackChainTests(unittest.TestCase):
    """fetch_fallback_quote 对 .OF ticker 的专用短链与降级记录。"""

    ENV_WITH_TOKEN = {
        "FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": "",
        "TUSHARE_TOKEN": "fake-token",
    }
    ENV_NO_TOKEN = {
        "FINNHUB_API_KEY": "", "EOD_API_KEY": "", "ENABLE_YFINANCE": "",
        "TUSHARE_TOKEN": "",
    }

    def test_tushare_fund_is_primary_and_stops_the_chain(self) -> None:
        # tushare-fund 命中时腾讯环不该被碰：短链就地停住。
        degradations: list[dict] = []
        with patch(
            "fetch_market_data.fetch_tushare_openfund_nav",
            return_value={"symbol": "021179.OF", "price": 2.8052, "source": "tushare-fund"},
        ) as mock_nav, patch(
            "fetch_market_data.fetch_tencent_openfund_quote"
        ) as mock_jj:
            quote = fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_WITH_TOKEN, degradations
            )

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "tushare-fund")
        mock_nav.assert_called_once()
        mock_jj.assert_not_called()
        self.assertEqual(degradations, [])  # 一次命中，无降级记录

    def test_tushare_fund_miss_falls_to_tencent_jj(self) -> None:
        degradations: list[dict] = []
        with patch(
            "fetch_market_data.fetch_tushare_openfund_nav", return_value=None
        ), patch(
            "fetch_market_data.fetch_tencent_openfund_quote",
            return_value={"symbol": "021179.OF", "price": 2.8052, "source": "tencent-fund"},
        ):
            quote = fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_WITH_TOKEN, degradations
            )

        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["source"], "tencent-fund")
        # 降级记录只含短链内的真实环（长链 9 环不产生条目）
        self.assertEqual(len(degradations), 1)
        self.assertEqual(degradations[0]["source_tried"], "tushare-fund")
        self.assertEqual(degradations[0]["fallback"], "tencent-fund")

    def test_no_token_goes_straight_to_tencent_jj(self) -> None:
        with patch(
            "fetch_market_data.fetch_tencent_openfund_quote",
            return_value={"symbol": "021179.OF", "price": 2.8052, "source": "tencent-fund"},
        ) as mock_jj, patch(
            "fetch_market_data.fetch_tushare_openfund_nav"
        ) as mock_nav:
            quote = fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_NO_TOKEN
            )

        self.assertIsNotNone(quote)
        mock_jj.assert_called_once()
        mock_nav.assert_not_called()  # 无 token 时 tushare-fund 环连构建都不进

    @patch("fetch_market_data.requests.get")
    def test_short_chain_never_touches_long_chain_endpoints(self, mock_get: MagicMock) -> None:
        # 变异防护：短链覆盖失败时绝不能漏进长链（东财 push2/新浪等）。
        degradations: list[dict] = []
        with patch(
            "fetch_market_data.fetch_tushare_openfund_nav", return_value=None
        ), patch("fetch_market_data.fetch_tencent_openfund_quote", return_value=None):
            quote = fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_WITH_TOKEN, degradations
            )

        self.assertIsNone(quote)
        mock_get.assert_not_called()  # 长链任何 HTTP 端点都未被碰
        # 路由锁（评审 M-1）：全 miss 时降级记录恰好是 fund 短链两环——
        # 若 .OF 路由被移除漏进长链，这里会出现长链环名而红。
        self.assertEqual(
            [d["source_tried"] for d in degradations],
            ["tushare-fund", "tencent-fund"],
        )
        self.assertEqual(
            [d["fallback"] for d in degradations], ["tencent-fund", "none"]
        )

    @patch("fetch_market_data.requests.get")
    def test_clean_reject_and_exception_reject_have_distinct_reasons(
        self, mock_get: MagicMock
    ) -> None:
        # 语义区分器（评审 M-4）：截断载荷=干净拒绝 reason="returned no
        # data"；HTTP 异常=reason 记真实异常文本。两路径互换时本断言红
        # （quote 侧 assertIsNone 锁不住这个差别）。
        with patch("fetch_market_data.fetch_tushare_openfund_nav", return_value=None):
            mock_get.return_value = _text_response(TENCENT_JJ_TRUNCATED_PAYLOAD)
            clean: list[dict] = []
            fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_WITH_TOKEN, clean
            )
            self.assertEqual(clean[-1]["source_tried"], "tencent-fund")
            self.assertEqual(clean[-1]["reason"], "returned no data")

            mock_get.side_effect = RuntimeError("connection reset")
            crashed: list[dict] = []
            fetch_fallback_quote(
                {"ticker": "021179.OF", "market": "CN"}, self.ENV_WITH_TOKEN, crashed
            )
            self.assertEqual(crashed[-1]["source_tried"], "tencent-fund")
            self.assertEqual(crashed[-1]["reason"], "connection reset")

    @patch("fetch_market_data.requests.get")
    def test_bare_fund_code_stays_on_the_long_chain(self, mock_get: MagicMock) -> None:
        # 裸 021179（无 .OF 后缀）不识别为场外基金：走长链并在各环被
        # gate 拒绝（不产生网络请求意义上的命中）——这是 .OF 约定的反面锁。
        with patch("fetch_market_data.fetch_mootdx_quote", return_value=None):
            quote = fetch_fallback_quote({"ticker": "021179", "market": "CN"}, self.ENV_NO_TOKEN)

        self.assertIsNone(quote)
        # 长链会空跑东财/腾讯/新浪（sh/sz 前缀拼不出 -> 无请求或即刻拒绝）；
        # 关键断言：没有任何 jj 前缀请求被发出。
        for call in mock_get.call_args_list:
            self.assertNotIn("jj021179", str(call.args))


class MootdxGateRegressionTests(unittest.TestCase):
    """_CN_CODE_RE 段位白名单回归（friction-log 2026-11-08 修根）。"""

    def test_watchlist_segments_still_pass(self) -> None:
        # 全池现有段位：A 股 60/68/00/30 + 场内基金 51/56/58/15。
        for ticker in (
            "600276.SH", "601899.SH", "603345.SH", "605016.SH",  # 沪主板
            "688825.SH",  # 科创
            "002415.SZ", "000630.SZ",  # 深主板/原中小板
            "300750.SZ", "301358.SZ",  # 创业板
            "513120.SH", "518880.SH", "517520.SH", "562800.SH",  # 沪 ETF
            "159399.SZ", "159201.SZ",  # 深 ETF
        ):
            self.assertTrue(is_mootdx_ticker(ticker), ticker)

    def test_open_fund_codes_are_rejected_in_every_spelling(self) -> None:
        # 场外码三种写法全部拒绝——尤其 021179.SZ：白名单前它会放行，
        # mootdx 会静默返回四川长虹的错票数据（本次修根的靶心）。
        for ticker in ("021179", "021179.OF", "021179.SZ"):
            self.assertFalse(is_mootdx_ticker(ticker), ticker)

    def test_zero_prefixed_fund_code_is_a_shape_defense_boundary(self) -> None:
        # 形状防御的边界（记录，不修）：002910 供给改革以 00 开头，与深主板
        # 真码形状完全重叠，正则无法区分——它的防线不是白名单而是 .OF
        # 约定本身（watchlist 永远写 002910.OF 而非 .SZ）。锁现状防误改。
        self.assertTrue(is_mootdx_ticker("002910.SZ"))  # 形状上确是深市码段

    def test_tdx_index_suffix_still_passes(self) -> None:
        self.assertTrue(is_mootdx_ticker("881075.TDX"))
        self.assertFalse(is_mootdx_ticker("881075.SH"))  # 板块指数配交易所后缀=配置错位


class OpenFundQuoteRecordTests(unittest.TestCase):
    def test_nav_date_compacts_to_iso_and_nones_survive(self) -> None:
        entry = {
            "ticker": "021179.OF", "name": "易方达产业机遇混合A",
            "market": "CN", "market_cap": "场外基金", "category": "主动权益-偏股",
        }
        raw = {
            "price": 2.8052, "changesPercentage": -1.993, "previousClose": 2.8625,
            "tradeDate": "20261106", "previousTradeDate": "20261105", "source": "tushare-fund",
        }
        record = build_quote_record(raw, entry)
        self.assertEqual(record["tradeDate"], "2026-11-06")
        self.assertEqual(record["previousTradeDate"], "2026-11-05")  # 期间涨跌可检测的钥匙
        self.assertIsNone(record["open"])  # 场外基金无 OHLC
        self.assertIsNone(record["volume"])
        self.assertEqual(record["source"], "tushare-fund")


if __name__ == "__main__":
    unittest.main()
