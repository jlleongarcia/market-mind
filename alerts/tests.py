from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from portfolio.models import Portfolio, Position, Transaction
from research.models import Dividend, FinancialMetrics, Stock, StockSplit
from research.services import StockDataFetcher

from .metrics import build_snapshots
from .models import AlertCondition, AlertEvent, AlertRule, AlertState, NotificationSettings, WishlistItem
from .notifications import _chunks, send_digest
from .services import (
    AlertEngine, detect_cut, detect_freeze, evaluate_rule, regular_dividend_series,
)


def make_metrics(symbol, **overrides):
    stock = Stock.objects.create(symbol=symbol, name=f'{symbol} Inc', currency='USD')
    values = dict(
        stock=stock, pays_dividend=True,
        current_price=Decimal('50'), price_date=timezone.now().date(),
        week52_low=Decimal('40'), week52_high=Decimal('70'),   # 50 → 33.3 percentile
        current_yield=Decimal('3.30'), avg_yield_5y=Decimal('3.00'),  # +10% vs average
        trailing_pe=Decimal('18'), payout_ratio=Decimal('60'), fcf_payout_ratio=Decimal('70'),
    )
    values.update(overrides)
    return FinancialMetrics.objects.create(**values)


class EvaluateRuleTests(TestCase):
    def test_all_and_any_with_missing_data(self):
        snap = {'yield': 4.0, 'pe': None}
        yes, no, unknown = ('yield', 'gt', 3), ('yield', 'lt', 3), ('pe', 'lt', 20)

        self.assertTrue(evaluate_rule('ALL', [yes], snap))
        self.assertFalse(evaluate_rule('ALL', [yes, no], snap))
        self.assertIsNone(evaluate_rule('ALL', [yes, unknown], snap))
        self.assertFalse(evaluate_rule('ALL', [no, unknown], snap))   # a known False decides ALL

        self.assertTrue(evaluate_rule('ANY', [no, yes], snap))
        self.assertTrue(evaluate_rule('ANY', [unknown, yes], snap))   # a known True decides ANY
        self.assertIsNone(evaluate_rule('ANY', [no, unknown], snap))
        self.assertFalse(evaluate_rule('ANY', [], snap))


class SnapshotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw')

    def test_derived_metrics(self):
        make_metrics('KO')
        snap = build_snapshots(self.user, ['KO'])['KO']
        self.assertEqual(snap['week52_percentile'], 33.3)
        self.assertEqual(snap['yield_vs_5y_avg'], 10.0)
        self.assertFalse(snap['owned'])

    def test_stale_price_is_missing_not_evaluated(self):
        make_metrics('KO', price_date=timezone.now().date() - timedelta(days=10))
        snap = build_snapshots(self.user, ['KO'])['KO']
        self.assertIsNone(snap['price'])
        self.assertIsNone(snap['week52_percentile'])
        self.assertEqual(snap['missing_reason'], 'price stale')
        self.assertEqual(snap['yield'], 3.3)   # non-price metrics still usable

    def test_owned_context_spans_portfolios(self):
        make_metrics('KO')
        for i, (qty, cost) in enumerate([(10, 40), (30, 60)]):
            p = Portfolio.objects.create(user=self.user, name=f'P{i}')
            Position.objects.create(portfolio=p, symbol='KO', quantity=qty, average_cost=cost)
            Transaction.objects.create(
                portfolio=p, symbol='KO', transaction_type='BUY', quantity=qty, price=cost,
                transaction_date=timezone.now(), buy_yield=Decimal('3.5') + i,
            )
        snap = build_snapshots(self.user, ['KO'])['KO']
        self.assertTrue(snap['owned'])
        self.assertEqual(snap['best_buy_yield'], 4.5)
        self.assertEqual(snap['price_vs_avg_cost'], -9.1)   # 50 vs weighted 55


class DividendSignalTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(symbol='DIV', name='Div Co', currency='USD')

    def _pay(self, amounts, start=None, gap=91):
        start = start or date.today() - timedelta(days=gap * (len(amounts) - 1))
        for i, amount in enumerate(amounts):
            Dividend.objects.create(stock=self.stock, date=start + timedelta(days=gap * i), amount=Decimal(str(amount)))

    def test_freeze_needs_frequency_plus_one_equal_payments(self):
        series = [(date(2025, 1, 1) + timedelta(days=91 * i), a) for i, a in enumerate([0.9, 1, 1, 1, 1])]
        self.assertIsNone(detect_freeze(series, 4))          # 4 equal: a normal year between raises
        series.append((date(2026, 4, 1), 1.0))
        start, length, amount = detect_freeze(series, 4)     # 5th equal payment
        self.assertEqual((start, length), (series[1][0], 5))
        self.assertEqual(detect_freeze(series[-3:], 2)[1], 3)  # semi-annual: 3 in a row

    def test_cut_only_when_recent(self):
        today = date.today()
        series = [(today - timedelta(days=100), 1.0), (today - timedelta(days=10), 0.5)]
        self.assertEqual(detect_cut(series, today)[1:], (1.0, 0.5))
        old = [(today - timedelta(days=400), 1.0), (today - timedelta(days=300), 0.5)]
        self.assertIsNone(detect_cut(old, today))

    def test_special_dividend_ignored(self):
        self._pay([1, 1, 1, 3, 1, 1, 1, 1])
        amounts = [a for _, a in regular_dividend_series(self.stock, 4)]
        self.assertNotIn(3.0, amounts)
        self.assertIsNotNone(detect_freeze(regular_dividend_series(self.stock, 4), 4))

    def test_raw_split_is_not_a_cut(self):
        # Raw (unadjusted) history across a 2-for-1 split: 1.00 → 0.52 is a raise, not a cut.
        start = date.today() - timedelta(days=91 * 5)
        self._pay([1, 1, 1, 1, 0.52, 0.52], start=start)
        StockSplit.objects.create(stock=self.stock, date=start + timedelta(days=91 * 3 + 30),
                                  ratio='2:1', split_from=2, split_to=1)
        series = regular_dividend_series(self.stock, 4)
        self.assertIsNone(detect_cut(series))


class EngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw', email='u@example.com')
        make_metrics('KO')
        WishlistItem.objects.create(user=self.user, symbol='KO', note='buy the dip')
        self.rule = AlertRule.objects.create(user=self.user, name='Cheap', scope='WISHLIST', cooldown_days=7)
        AlertCondition.objects.create(rule=self.rule, metric='week52_percentile', operator='lte', value=Decimal('33.5'))

    def _run(self, now=None):
        return AlertEngine(now=now).evaluate_user(self.user)[0]

    def test_fires_once_on_transition(self):
        events = self._run()
        self.assertEqual(len(events), 1)
        self.assertIn('buy the dip', events[0].message)
        self.assertEqual(self._run(), [])   # still true next day → silent

    def test_cooldown_blocks_flapping_then_allows(self):
        t0 = timezone.now()
        self._run(t0)
        fm = FinancialMetrics.objects.get(stock_id='KO')
        fm.current_price = Decimal('65'); fm.save()
        self.assertEqual(self._run(t0 + timedelta(days=1)), [])      # turns false → re-armed
        fm.current_price = Decimal('45'); fm.save()
        self.assertEqual(self._run(t0 + timedelta(days=2)), [])      # true again, but within cooldown
        fm.current_price = Decimal('65'); fm.save()
        self._run(t0 + timedelta(days=9))
        fm.current_price = Decimal('45'); fm.save()
        self.assertEqual(len(self._run(t0 + timedelta(days=10))), 1)  # after cooldown → fires

    def test_missing_data_leaves_state_untouched(self):
        self._run()
        FinancialMetrics.objects.filter(stock_id='KO').update(price_date=timezone.now().date() - timedelta(days=30))
        events, unevaluated = AlertEngine().evaluate_user(self.user)
        self.assertEqual(events, [])
        self.assertIn('KO', unevaluated)
        self.assertTrue(AlertState.objects.get(key=f'rule:{self.rule.id}').is_matching)

    def test_dry_run_writes_nothing(self):
        events, _ = AlertEngine(dry_run=True).evaluate_user(self.user)
        self.assertEqual(len(events), 1)
        self.assertFalse(AlertState.objects.exists())
        self.assertFalse(AlertEvent.objects.exists())

    def test_payout_warning_only_for_owned(self):
        make_metrics('T', payout_ratio=Decimal('120'))
        WishlistItem.objects.create(user=self.user, symbol='T')
        self.assertFalse([e for e in self._run() if e.kind == 'PAYOUT_HIGH'])
        p = Portfolio.objects.create(user=self.user, name='Main')
        Position.objects.create(portfolio=p, symbol='T', quantity=1, average_cost=20)
        self.assertEqual([e.kind for e in self._run() if e.symbol == 'T'], ['PAYOUT_HIGH'])
        self.assertEqual([e for e in self._run() if e.symbol == 'T'], [])

    def test_freeze_reported_once(self):
        stock = Stock.objects.get(symbol='KO')
        start = date.today() - timedelta(days=91 * 5)
        for i in range(6):
            Dividend.objects.create(stock=stock, date=start + timedelta(days=91 * i), amount=Decimal('0.51'))
        p = Portfolio.objects.create(user=self.user, name='Main')
        Position.objects.create(portfolio=p, symbol='KO', quantity=1, average_cost=20)
        self.assertEqual([e.kind for e in self._run() if e.kind == 'DIVIDEND_FREEZE'], ['DIVIDEND_FREEZE'])
        self.assertEqual([e for e in self._run() if e.kind == 'DIVIDEND_FREEZE'], [])


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_BOT_USERNAME='')
class DigestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw', email='u@example.com')

    def test_one_email_per_user_and_no_resend(self):
        for sym in ('KO', 'PEP'):
            AlertEvent.objects.create(user=self.user, kind='RULE', symbol=sym, message=f'{sym} matched')
        send_digest(self.user, {'XYZ': 'no metrics yet'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('KO matched', mail.outbox[0].body)
        self.assertIn('XYZ: no metrics yet', mail.outbox[0].body)
        self.assertEqual(send_digest(self.user, {}), 'nothing to send')
        self.assertEqual(len(mail.outbox), 1)

    def test_email_disabled(self):
        NotificationSettings.objects.create(user=self.user, email_enabled=False)
        AlertEvent.objects.create(user=self.user, kind='RULE', symbol='KO', message='x')
        send_digest(self.user, {})
        self.assertEqual(len(mail.outbox), 0)

    def test_telegram_chunks_never_exceed_limit(self):
        text = '\n\n'.join('x' * 1000 for _ in range(10))
        chunks = _chunks(text)
        self.assertTrue(all(len(c) <= 4096 for c in chunks))
        self.assertEqual(''.join(chunks).count('x'), 10000)


class PriceHistorySummaryTests(TestCase):
    def _hist(self, days, close, dividends):
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
        df = pd.DataFrame({'Close': close(np.arange(days)), 'Dividends': 0.0}, index=idx)
        df['High'] = df['Close'] * 1.01
        df['Low'] = df['Close'] * 0.99
        for pos, amount in dividends:
            df.iloc[pos, df.columns.get_loc('Dividends')] = amount
        return df

    def test_constant_yield(self):
        # Price 100 and a $1 quarterly dividend every ~63 trading days → 4% throughout
        days = 252 * 6
        hist = self._hist(days, lambda i: np.full(len(i), 100.0), [(p, 1.0) for p in range(0, days, 63)])
        out = StockDataFetcher.summarize_price_history(hist, 4, False)
        self.assertAlmostEqual(out['avg_yield_5y'], 4.0, places=4)
        self.assertAlmostEqual(out['week52_low'], 99.0)
        self.assertAlmostEqual(out['week52_high'], 101.0)

    def test_special_excluded_and_short_history_has_no_average(self):
        days = 252 * 6
        divs = [(p, 1.0) for p in range(0, days, 63)]
        divs[10] = (divs[10][0], 5.0)   # one special
        out = StockDataFetcher.summarize_price_history(
            self._hist(days, lambda i: np.full(len(i), 100.0), divs), 4, False)
        self.assertAlmostEqual(out['avg_yield_5y'], 4.0, places=4)

        short = self._hist(400, lambda i: np.full(len(i), 100.0), [(p, 1.0) for p in range(0, 400, 63)])
        self.assertNotIn('avg_yield_5y', StockDataFetcher.summarize_price_history(short, 4, False))


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw')
        self.client.login(username='u', password='pw')
        make_metrics('KO')
        WishlistItem.objects.create(user=self.user, symbol='KO')

    def test_pages_render(self):
        for name in ('wishlist_view', 'rules_view', 'rule_create_view', 'history_view', 'notification_settings_view'):
            self.assertEqual(self.client.get(reverse(f'alerts:{name}')).status_code, 200, name)

    def test_create_rule_and_preview(self):
        data = {
            'name': 'Mine', 'scope': 'BOTH', 'match': 'ALL', 'cooldown_days': '7', 'is_active': 'on',
            'metric': ['yield_vs_5y_avg', 'week52_percentile'], 'operator': ['gt', 'lte'], 'value': ['0', '33.5'],
        }
        resp = self.client.post(reverse('alerts:rule_preview_api'), data)
        self.assertEqual(resp.json()['rows'][0]['result'], True)
        self.client.post(reverse('alerts:rule_create_view'), data)
        rule = AlertRule.objects.get(user=self.user)
        self.assertEqual(rule.conditions.count(), 2)
        self.assertEqual(self.client.get(reverse('alerts:rule_edit_view', args=[rule.pk])).status_code, 200)

    def test_preset_and_isolation(self):
        self.client.post(reverse('alerts:rules_view'), {'action': 'preset', 'preset': 'yield_and_low_third'})
        rule = AlertRule.objects.get(user=self.user)
        other = User.objects.create_user(username='other', password='pw')
        self.client.logout()
        self.client.login(username='other', password='pw')
        self.assertEqual(self.client.get(reverse('alerts:rule_edit_view', args=[rule.pk])).status_code, 404)
        self.client.post(reverse('alerts:rules_view'), {'action': 'delete', 'rule_id': rule.pk})
        self.assertTrue(AlertRule.objects.filter(pk=rule.pk).exists())
        self.assertFalse(other.alert_rules.exists())
