from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pandas as pd
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Dividend, Stock, StockSplit
from .services import StockDataFetcher


class PreloadedDividendChecksTests(TestCase):
    """
    _is_plausible_dividend_amount / _find_nearby_dividend / _split_adjustment_factor
    can either query the DB themselves or be handed preloaded lists (what
    save_dividends now does, to avoid a query per incoming row). Both paths
    must agree.
    """

    def setUp(self):
        self.fetcher = StockDataFetcher()
        self.stock = Stock.objects.create(symbol='ACME', name='Acme Corp', currency='USD')
        self.base = date(2024, 1, 1)
        for i in range(4):
            Dividend.objects.create(
                stock=self.stock, date=self.base + timedelta(days=90 * i), amount=Decimal('1.00')
            )

    def test_is_plausible_preloaded_matches_db_query(self):
        ex_date = self.base + timedelta(days=360)
        known_dividends = list(Dividend.objects.filter(stock=self.stock))
        known_splits = list(StockSplit.objects.filter(stock=self.stock))

        db_result = self.fetcher._is_plausible_dividend_amount(self.stock, ex_date, '1.05', False)
        preloaded_result = self.fetcher._is_plausible_dividend_amount(
            self.stock, ex_date, '1.05', False, recent_dividends=known_dividends, splits=known_splits
        )
        self.assertTrue(db_result)
        self.assertEqual(db_result, preloaded_result)

        db_result = self.fetcher._is_plausible_dividend_amount(self.stock, ex_date, '50.00', False)
        preloaded_result = self.fetcher._is_plausible_dividend_amount(
            self.stock, ex_date, '50.00', False, recent_dividends=known_dividends, splits=known_splits
        )
        self.assertFalse(db_result)
        self.assertEqual(db_result, preloaded_result)

    def test_split_adjustment_preloaded_matches_db_query(self):
        split_date = self.base + timedelta(days=45)
        StockSplit.objects.create(stock=self.stock, date=split_date, ratio='2:1', split_from=2, split_to=1)
        known_splits = list(StockSplit.objects.filter(stock=self.stock))

        db_factor = self.fetcher._split_adjustment_factor(self.stock, self.base, self.base + timedelta(days=100))
        preloaded_factor = self.fetcher._split_adjustment_factor(
            self.stock, self.base, self.base + timedelta(days=100), splits=known_splits
        )
        self.assertEqual(db_factor, 2.0)
        self.assertEqual(db_factor, preloaded_factor)

    def test_find_nearby_preloaded_matches_db_query(self):
        near_date = self.base + timedelta(days=2)
        known_dividends = list(Dividend.objects.filter(stock=self.stock))

        db_result = self.fetcher._find_nearby_dividend(self.stock, near_date, '1.00')
        preloaded_result = self.fetcher._find_nearby_dividend(self.stock, near_date, '1.00', candidates=known_dividends)
        self.assertIsNotNone(db_result)
        self.assertEqual(db_result.date, preloaded_result.date)

        far_date = self.base + timedelta(days=400)
        db_result = self.fetcher._find_nearby_dividend(self.stock, far_date, '1.00')
        preloaded_result = self.fetcher._find_nearby_dividend(self.stock, far_date, '1.00', candidates=known_dividends)
        self.assertIsNone(db_result)
        self.assertIsNone(preloaded_result)

    def test_stale_old_dividend_is_not_used_as_recent_baseline(self):
        """
        A single dividend far older than _RECENT_DIVIDEND_LOOKBACK_DAYS must
        not be picked up as the "nearest earlier" comparator — otherwise it
        permanently locks out every later entry, since a rejected row is
        never saved and so keeps being the nearest comparator forever (seen
        live: NEE stuck at 2 rows since a $0.0172 1973 entry poisoned every
        later comparison). A stock-sized, unconfirmed amount should pass when
        the only "earlier" row on record is years out of range.
        """
        stock = Stock.objects.create(symbol='OLDCO', name='Old Co', currency='USD')
        Dividend.objects.create(stock=stock, date=date(1973, 2, 21), amount=Decimal('0.0172'))

        ex_date = date(1983, 8, 22)
        self.assertTrue(self.fetcher._is_plausible_dividend_amount(stock, ex_date, '0.05625', False))

        known_dividends = list(Dividend.objects.filter(stock=stock))
        self.assertTrue(
            self.fetcher._is_plausible_dividend_amount(
                stock, ex_date, '0.05625', False, recent_dividends=known_dividends, splits=[]
            )
        )

    def test_dividend_within_lookback_still_enforces_plausibility(self):
        """The recency bound only widens what counts as "no data" — it must not
        weaken the check for a genuinely recent, implausible amount."""
        stock = Stock.objects.create(symbol='NEWCO', name='New Co', currency='USD')
        Dividend.objects.create(stock=stock, date=date(2024, 1, 1), amount=Decimal('0.50'))

        ex_date = date(2024, 4, 1)
        self.assertFalse(self.fetcher._is_plausible_dividend_amount(stock, ex_date, '25.00', False))


class FetchDividendsPrimaryFmpGateTests(TestCase):
    """
    FMP premium-gates a handful of individual US tickers outright (confirmed
    live for NEE: HTTP 402 even though the exchange is covered in general).
    _fetch_dividends_primary must retry Alpha Vantage in that case instead of
    dropping straight to the much lower-confidence yfinance fallback.
    """

    def setUp(self):
        self.fetcher = StockDataFetcher()
        self.stock = Stock.objects.create(symbol='NEE', name='NextEra Energy', currency='USD', exchange='NYQ')

    def test_fmp_failure_retries_alpha_vantage(self):
        av_data = [{'ex_dividend_date': '2026-08-28', 'declaration_date': '2026-07-30', 'amount': '0.6232'}]
        with patch.object(self.fetcher, '_fetch_dividends_fmp', return_value=None) as mock_fmp, \
             patch.object(self.fetcher, '_fetch_dividends_alphavantage', return_value=av_data) as mock_av:
            data, source = self.fetcher._fetch_dividends_primary(self.stock)

        mock_fmp.assert_called_once_with('NEE')
        mock_av.assert_called_once_with('NEE')
        self.assertEqual(data, av_data)
        self.assertEqual(source, 'Alpha Vantage (FMP fallback)')

    def test_fmp_success_does_not_call_alpha_vantage(self):
        fmp_data = [{'ex_dividend_date': '2026-08-28', 'declaration_date': '2026-07-30', 'amount': '0.6232'}]
        with patch.object(self.fetcher, '_fetch_dividends_fmp', return_value=fmp_data), \
             patch.object(self.fetcher, '_fetch_dividends_alphavantage') as mock_av:
            data, source = self.fetcher._fetch_dividends_primary(self.stock)

        mock_av.assert_not_called()
        self.assertEqual(data, fmp_data)
        self.assertEqual(source, 'FMP')


class SaveDividendsYfinanceFallbackTests(TestCase):
    """
    save_dividends' yfinance-fallback branch is where the un-preloaded version
    used to issue several DB queries (recent-history + split-adjustment +
    nearby-duplicate lookups) per incoming row — for a stock with decades of
    history that was the dominant cost of a portfolio-wide dividend sync.
    """

    def setUp(self):
        self.fetcher = StockDataFetcher()
        self.stock = Stock.objects.create(
            symbol='ACME', name='Acme Corp', currency='USD', exchange='LSE'  # non-US -> Alpha Vantage primary
        )
        patcher = patch.object(StockDataFetcher, '_fetch_dividends_primary', return_value=(None, 'Alpha Vantage'))
        self.addCleanup(patcher.stop)
        patcher.start()
        payment_patcher = patch.object(StockDataFetcher, '_fetch_payment_date_map_yfinance', return_value={})
        self.addCleanup(payment_patcher.stop)
        payment_patcher.start()

    def _mock_dividends(self, entries):
        index = pd.to_datetime([d for d, _ in entries])
        return pd.Series([a for _, a in entries], index=index)

    def test_same_batch_near_duplicate_is_still_deduped(self):
        """
        Two entries in the *same* fetch batch, a few days apart with a similar
        amount, must still be treated as one event — this only works if the
        in-memory preloaded list is updated as rows are saved (_remember),
        since there's no DB round trip to catch it otherwise.
        """
        entries = [
            (date(2024, 3, 1), 0.50),
            (date(2024, 3, 4), 0.505),  # same real payment, reported a few days later
        ]
        with patch.object(self.fetcher, 'fetch_dividends', return_value=self._mock_dividends(entries)):
            created = self.fetcher.save_dividends('ACME')

        self.assertEqual(created, 1)
        self.assertEqual(Dividend.objects.filter(stock=self.stock).count(), 1)

    def test_implausible_amount_is_rejected(self):
        entries = [
            (date(2024, 1, 1), 0.50),
            (date(2024, 4, 1), 0.51),
            (date(2024, 7, 1), 0.52),
            (date(2024, 10, 1), 0.53),
            (date(2025, 1, 1), 25.0),  # wildly outside recent range, no confirming date
        ]
        with patch.object(self.fetcher, 'fetch_dividends', return_value=self._mock_dividends(entries)):
            created = self.fetcher.save_dividends('ACME')

        self.assertEqual(created, 4)
        self.assertFalse(Dividend.objects.filter(stock=self.stock, date=date(2025, 1, 1)).exists())

    def test_query_count_does_not_scale_with_history_length(self):
        """
        Locks in the fix: per-row cost should be bounded by Django's own
        get_or_create machinery (existence check + savepoint/insert/release,
        ~4 queries/row) and NOT also carry a recent-history query, up to 4
        split-adjustment queries, and a nearby-duplicate query on top — which
        is what _is_plausible_dividend_amount/_find_nearby_dividend cost
        before they accepted preloaded data, multiplying per-row cost several
        times over for a stock with a lot of dividend history.
        """
        entries = [(date(2000, 1, 1) + timedelta(days=90 * i), 0.50 + i * 0.001) for i in range(60)]
        with patch.object(self.fetcher, 'fetch_dividends', return_value=self._mock_dividends(entries)):
            with CaptureQueriesContext(connection) as ctx:
                created = self.fetcher.save_dividends('ACME')

        self.assertEqual(created, 60)
        # 1 (resolve stock) + 2 (preload known dividends/splits) + up to 4/row
        # from get_or_create's own existence-check + savepoint/insert/release.
        self.assertLessEqual(len(ctx.captured_queries), 3 + created * 4)


class FetchFinancialMetricsDividendRateFallbackTests(TestCase):
    """
    yfinance leaves `dividendRate` blank for some dividend payers (observed
    live for SCHD) even though it reports a `dividendYield` — which otherwise
    silently blanks out everything downstream that needs a per-share rate
    (Position.yield_on_cost, Position.annual_dividend_income). fetch_financial_metrics
    must fall back to our own payment history in that case.
    """

    def setUp(self):
        self.fetcher = StockDataFetcher()
        self.stock = Stock.objects.create(symbol='ETFX', name='Example ETF', currency='USD', is_etf=True)
        quarterly_amounts = [Decimal('0.25'), Decimal('0.26'), Decimal('0.27'), Decimal('0.28')]
        for i, amount in enumerate(quarterly_amounts):
            Dividend.objects.create(stock=self.stock, date=date(2025, 3, 1) + timedelta(days=90 * i), amount=amount)

    def _mock_info(self, **overrides):
        info = {'dividendRate': None, 'dividendYield': 3.0, 'regularMarketPrice': 36.0}
        info.update(overrides)
        return info

    def test_falls_back_to_payment_history_when_dividend_rate_missing(self):
        with patch('research.services.yf.Ticker') as mock_ticker:
            mock_ticker.return_value.info = self._mock_info()
            metrics = self.fetcher.fetch_financial_metrics('ETFX')

        self.assertEqual(metrics['dividend_rate'], Decimal('1.06'))  # 0.25+0.26+0.27+0.28
        self.assertTrue(metrics['pays_dividend'])

    def test_does_not_override_a_dividend_rate_yfinance_already_provides(self):
        with patch('research.services.yf.Ticker') as mock_ticker:
            mock_ticker.return_value.info = self._mock_info(dividendRate=2.5)
            metrics = self.fetcher.fetch_financial_metrics('ETFX')

        self.assertEqual(metrics['dividend_rate'], Decimal('2.5'))

    def test_leaves_dividend_rate_none_when_no_payment_history_exists(self):
        self.stock.dividends.all().delete()
        with patch('research.services.yf.Ticker') as mock_ticker:
            mock_ticker.return_value.info = self._mock_info()
            metrics = self.fetcher.fetch_financial_metrics('ETFX')

        self.assertIsNone(metrics['dividend_rate'])
