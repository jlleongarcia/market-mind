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
        patcher = patch.object(StockDataFetcher, '_fetch_dividends_primary', return_value=None)
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
