from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from research.models import Stock, Dividend as ResearchDividend

from .models import Portfolio, Transaction, Dividend as PortfolioDividend
from .services import PortfolioCalculationService


class AutoRecordDividendsTests(TestCase):
    """
    Covers the resync scenario: a user backfills a buy/sell transaction dated
    before an ex-dividend date *after* the dividend was already auto-recorded.
    The stored quantity/amount must be corrected on the next sync rather than
    frozen at whatever was true when the row was first created.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.portfolio = Portfolio.objects.create(user=self.user, name='Main')
        self.stock = Stock.objects.create(symbol='ACME', name='Acme Corp', currency='USD')
        self.ex_date = timezone.now().date() - timezone.timedelta(days=30)
        self.research_div = ResearchDividend.objects.create(
            stock=self.stock,
            date=self.ex_date,
            payment_date=self.ex_date + timezone.timedelta(days=5),
            amount=Decimal('1.00'),
        )

        # yfinance refresh is irrelevant to this logic and would hit the network.
        patcher = patch.object(PortfolioCalculationService, '_shares_held_on_date',
                                wraps=PortfolioCalculationService._shares_held_on_date)
        self.addCleanup(patcher.stop)
        patcher.start()

        fetch_patcher = patch('research.services.StockDataFetcher.save_dividends')
        fetch_patcher.start()
        self.addCleanup(fetch_patcher.stop)
        metrics_patcher = patch('research.services.StockDataFetcher.save_financial_metrics')
        metrics_patcher.start()
        self.addCleanup(metrics_patcher.stop)

    def _buy(self, quantity, days_before_ex):
        Transaction.objects.create(
            portfolio=self.portfolio,
            symbol='ACME',
            transaction_type='BUY',
            quantity=Decimal(quantity),
            price=Decimal('10'),
            transaction_date=timezone.make_aware(
                timezone.datetime.combine(
                    self.ex_date - timezone.timedelta(days=days_before_ex),
                    timezone.datetime.min.time(),
                )
            ),
        )

    def test_backfilled_earlier_buy_updates_existing_dividend(self):
        self._buy(10, days_before_ex=10)
        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(result['created'], 1)

        div = PortfolioDividend.objects.get(portfolio=self.portfolio, symbol='ACME')
        self.assertEqual(div.quantity, Decimal('10'))
        self.assertEqual(div.amount, Decimal('10.00'))

        # User forgot this buy and backfills it now, dated before the ex-date.
        self._buy(5, days_before_ex=20)

        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)

        div.refresh_from_db()
        self.assertEqual(div.quantity, Decimal('15'))
        self.assertEqual(div.amount, Decimal('15.00'))
        self.assertEqual(PortfolioDividend.objects.filter(portfolio=self.portfolio, symbol='ACME').count(), 1)

    def test_backfilled_sell_to_zero_deletes_dividend(self):
        self._buy(10, days_before_ex=10)
        PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(PortfolioDividend.objects.filter(portfolio=self.portfolio).count(), 1)

        Transaction.objects.create(
            portfolio=self.portfolio,
            symbol='ACME',
            transaction_type='SELL',
            quantity=Decimal('10'),
            price=Decimal('12'),
            transaction_date=timezone.make_aware(
                timezone.datetime.combine(
                    self.ex_date - timezone.timedelta(days=9),
                    timezone.datetime.min.time(),
                )
            ),
        )

        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(PortfolioDividend.objects.filter(portfolio=self.portfolio).count(), 0)

    def test_manually_edited_dividend_is_never_touched(self):
        self._buy(10, days_before_ex=10)
        PortfolioCalculationService.auto_record_dividends(self.portfolio)

        div = PortfolioDividend.objects.get(portfolio=self.portfolio, symbol='ACME')
        div.is_manual = True
        div.amount = Decimal('999.00')
        div.save(update_fields=['is_manual', 'amount'])

        self._buy(5, days_before_ex=20)
        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['created'], 0)

        div.refresh_from_db()
        self.assertEqual(div.amount, Decimal('999.00'))

    def test_unchanged_run_is_idempotent(self):
        self._buy(10, days_before_ex=10)
        PortfolioCalculationService.auto_record_dividends(self.portfolio)
        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['skipped'], 1)

    def test_oversized_amount_is_skipped_without_crashing_the_sync(self):
        """
        quantity x per-share amount can exceed Dividend.amount's max_digits=10
        for a large enough position (a big institutional-size share count).
        That row should be skipped and reported, not take the whole sync down.
        """
        huge_stock = Stock.objects.create(symbol='HUGE', name='Huge Corp', currency='USD')
        ResearchDividend.objects.create(
            stock=huge_stock,
            date=self.ex_date,
            payment_date=self.ex_date + timezone.timedelta(days=5),
            amount=Decimal('1.00'),
        )
        Transaction.objects.create(
            portfolio=self.portfolio,
            symbol='HUGE',
            transaction_type='BUY',
            quantity=Decimal('100000000'),
            price=Decimal('1'),
            transaction_date=timezone.make_aware(
                timezone.datetime.combine(
                    self.ex_date - timezone.timedelta(days=10),
                    timezone.datetime.min.time(),
                )
            ),
        )
        self._buy(10, days_before_ex=10)  # unrelated ACME dividend should still process fine

        result = PortfolioCalculationService.auto_record_dividends(self.portfolio)

        self.assertEqual(result['created'], 1)
        self.assertIn('HUGE', result.get('errors', []))
        self.assertEqual(PortfolioDividend.objects.filter(portfolio=self.portfolio, symbol='ACME').count(), 1)
        self.assertEqual(PortfolioDividend.objects.filter(portfolio=self.portfolio, symbol='HUGE').count(), 0)


class SpinOffCostBasisTests(TestCase):
    """
    A spin-off is a virtual buy: the shares received need a real cost basis
    (the fair-market-value price entered on the SPOF transaction), not a $0
    one, otherwise selling them later overstates profit.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.portfolio = Portfolio.objects.create(user=self.user, name='Main')
        Stock.objects.create(symbol='PARENT', name='Parent Co', currency='USD')
        Stock.objects.create(symbol='SPINCO', name='Spin Co', currency='USD')

    def _tx(self, **kwargs):
        defaults = dict(
            portfolio=self.portfolio, quantity=Decimal('1'), price=Decimal('0'),
            commission=Decimal('0'), transaction_date=timezone.now(),
        )
        defaults.update(kwargs)
        tx = Transaction.objects.create(**defaults)
        if tx.transaction_type in ('BUY', 'SELL', 'SPOF'):
            PortfolioCalculationService.update_position_from_transaction(tx)
        return tx

    def test_spof_establishes_cost_basis_like_a_buy(self):
        self._tx(symbol='SPINCO', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('5.00'))
        position = self.portfolio.positions.get(symbol='SPINCO')
        self.assertEqual(position.quantity, Decimal('10'))
        self.assertEqual(position.average_cost, Decimal('5.00'))

    def test_spof_blends_with_existing_buy_lot(self):
        self._tx(symbol='PARENT', transaction_type='BUY', quantity=Decimal('10'), price=Decimal('20.00'))
        # Spin-off of the same symbol (e.g. a return-of-capital adjustment) blends in
        self._tx(symbol='PARENT', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('10.00'))
        position = self.portfolio.positions.get(symbol='PARENT')
        self.assertEqual(position.quantity, Decimal('20'))
        self.assertEqual(position.average_cost, Decimal('15.00'))  # (10*20 + 10*10) / 20

    def test_selling_spof_shares_uses_spof_price_not_zero(self):
        self._tx(symbol='SPINCO', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('5.00'))
        self._tx(symbol='SPINCO', transaction_type='SELL', quantity=Decimal('4'), price=Decimal('8.00'))
        position = self.portfolio.positions.get(symbol='SPINCO')
        self.assertEqual(position.quantity, Decimal('6'))
        # average_cost must stay at the SPOF-established basis, not reset to 0
        self.assertEqual(position.average_cost, Decimal('5.00'))
        self.assertEqual(position.total_cost, Decimal('30.00'))  # 6 remaining shares * $5 basis

    def test_rebuild_position_replays_spof_correctly(self):
        self._tx(symbol='SPINCO', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('5.00'))
        PortfolioCalculationService.rebuild_position(self.portfolio, 'SPINCO')
        position = self.portfolio.positions.get(symbol='SPINCO')
        self.assertEqual(position.quantity, Decimal('10'))
        self.assertEqual(position.average_cost, Decimal('5.00'))

    def test_total_amount_treats_spof_like_a_buy(self):
        tx = self._tx(symbol='SPINCO', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('5.00'))
        self.assertEqual(tx.total_amount, Decimal('50.00'))

    def test_broker_summary_does_not_count_spof_as_a_sale(self):
        self._tx(symbol='PARENT', transaction_type='BUY', quantity=Decimal('10'), price=Decimal('20.00'),
                  broker='Degiro')
        self._tx(symbol='SPINCO', transaction_type='SPOF', quantity=Decimal('10'), price=Decimal('5.00'),
                  broker='Degiro')
        summary = {b['broker']: b for b in PortfolioCalculationService.calculate_broker_summary(self.portfolio)}
        # SPOF must not be subtracted from total_invested like a cash sale would be
        self.assertEqual(summary['Degiro']['total_invested'], 200.0)


class DividendCrudViewTests(TestCase):
    """
    Covers the manual edit/delete UI: editing a Dividend must mark it
    is_manual=True so auto_record_dividends leaves it alone afterward.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        self.portfolio = Portfolio.objects.create(user=self.user, name='Main')
        self.stock = Stock.objects.create(symbol='ACME', name='Acme Corp', currency='USD')

    def test_edit_view_marks_previously_auto_recorded_dividend_manual(self):
        div = PortfolioDividend.objects.create(
            portfolio=self.portfolio, symbol='ACME', amount=Decimal('10.00'),
            quantity=Decimal('10'), payment_date=timezone.now().date(),
            ex_dividend_date=timezone.now().date(), notes='Auto-recorded', is_manual=False,
        )
        response = self.client.post(
            reverse('portfolio:dividend_edit_view', args=[self.portfolio.id, div.id]),
            {
                'symbol': 'ACME',
                'amount': '11.00',
                'quantity': '10',
                'tax': '0',
                'payment_date': div.payment_date.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        div.refresh_from_db()
        self.assertTrue(div.is_manual)
        self.assertEqual(div.amount, Decimal('11.00'))

    def test_delete_view_removes_dividend(self):
        div = PortfolioDividend.objects.create(
            portfolio=self.portfolio, symbol='ACME', amount=Decimal('10.00'), is_manual=True,
        )
        response = self.client.post(reverse('portfolio:dividend_delete_view', args=[self.portfolio.id, div.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PortfolioDividend.objects.filter(pk=div.id).exists())

    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_edit_form_renders(self):
        div = PortfolioDividend.objects.create(
            portfolio=self.portfolio, symbol='ACME', amount=Decimal('10.00'), is_manual=True,
        )
        response = self.client.get(reverse('portfolio:dividend_edit_view', args=[self.portfolio.id, div.id]))
        self.assertEqual(response.status_code, 200)

    def test_other_users_dividend_is_not_editable(self):
        other = User.objects.create_user(username='other', password='pw')
        other_portfolio = Portfolio.objects.create(user=other, name='Other')
        div = PortfolioDividend.objects.create(
            portfolio=other_portfolio, symbol='ACME', amount=Decimal('10.00'), is_manual=True,
        )
        response = self.client.post(
            reverse('portfolio:dividend_edit_view', args=[other_portfolio.id, div.id]),
            {'symbol': 'ACME', 'amount': '999', 'payment_date': ''},
        )
        self.assertEqual(response.status_code, 404)
