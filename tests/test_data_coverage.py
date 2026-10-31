from __future__ import annotations

import unittest
from unittest.mock import patch

import _test_paths  # noqa: F401
from fetch_market_data import fetch_earnings_calendar
from generate_daily_report import render_data_coverage, render_earnings_sections


class CoverageTests(unittest.TestCase):
    def test_no_key_is_not_an_empty_success(self):
        status = {}
        with patch('fetch_market_data.request_json') as request:
            self.assertEqual(fetch_earnings_calendar('', {}, status), [])
        request.assert_not_called()
        self.assertEqual(status['state'], 'not_configured')
        text = '\n'.join(render_earnings_sections([], True, status))
        self.assertIn('本轮未检查', text)
        self.assertNotIn('暂无', text)

    def test_failed_request_is_not_empty_success(self):
        status = {}
        with patch('fetch_market_data.request_json', side_effect=RuntimeError('offline')):
            self.assertEqual(fetch_earnings_calendar('test', {}, status), [])
        self.assertEqual(status['state'], 'failed')
        self.assertIn('获取失败', render_earnings_sections([], True, status)[0])

    def test_successful_empty_calendar_remains_empty_success(self):
        status = {}
        with patch('fetch_market_data.request_json', return_value=[]):
            self.assertEqual(fetch_earnings_calendar('test', {}, status), [])
        self.assertEqual(status['state'], 'ok')
        self.assertIn('暂无', render_earnings_sections([], True, status)[0])

    def test_malformed_response_is_a_failure(self):
        status = {}
        with patch('fetch_market_data.request_json', return_value={'error': 'denied'}):
            fetch_earnings_calendar('test', {}, status)
        self.assertEqual(status['state'], 'failed')

    def test_report_keeps_source_date_and_missing_coverage(self):
        market = {'quotes': [{'ticker': 'AAPL', 'source': 'nasdaq', 'tradeDate': 'Sep 29, 2026'}],
                  'meta': {'fetched_at': '2026-09-30T01:00:00+00:00',
                           'quotes': {'missing_tickers': ['OTHER']}}}
        text = render_data_coverage(market, {'meta': {'reason': 'FMP_API_KEY not set'}},
                                    {'earnings': True, 'macro': True})
        for value in ['nasdaq', 'Sep 29, 2026', 'OTHER', '宏观数据源未配置', '2026-09-30T01:00:00']:
            self.assertIn(value, text)

    def test_caliber_note_shows_when_watched_ticker_present(self):
        market = {'quotes': [{'ticker': 'HG=F', 'source': 'sina', 'tradeDate': '2026-10-31'},
                             {'ticker': '000630.SZ', 'source': 'tushare', 'tradeDate': '2026-10-30'}],
                  'meta': {'fetched_at': '2026-10-31T12:00:00+00:00'}}
        text = render_data_coverage(market, {'meta': {}}, {'earnings': False, 'macro': False})
        self.assertIn('口径注记（HG=F）', text)
        self.assertIn('LME 三月铜', text)
        # 未命中注记表的标的不能带出口径行。
        self.assertNotIn('口径注记（000630.SZ）', text)
        self.assertNotIn('口径注记（^TNX）', text)
