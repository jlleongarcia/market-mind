"""
Alert evaluation: user rules, built-in warnings for owned stocks, and the
daily digest. Driven by the run_alerts management command (daily cron); the
preview helpers are also used by the rule editor's "Test now".
"""
import logging
import operator
from datetime import date, timedelta

import pandas as pd
from django.contrib.auth.models import User
from django.utils import timezone

from .metrics import (
    METRIC_LABELS, build_snapshots, format_value, owned_symbols, wishlist_symbols,
)
from .models import AlertEvent, AlertRule, AlertState, NotificationSettings

logger = logging.getLogger(__name__)

OPERATORS = {
    'lt': (operator.lt, '<'),
    'lte': (operator.le, '≤'),
    'gt': (operator.gt, '>'),
    'gte': (operator.ge, '≥'),
}

# Days a built-in threshold warning (payout > 100%) stays quiet after firing
WARNING_COOLDOWN_DAYS = 30
# A cut is only reported while it's recent — on first run we don't want to
# dig up a cut from years ago on a stock that hasn't paid since.
CUT_RECENCY_DAYS = 120
# Relative tolerance for treating two split-adjusted payments as "equal"
FREEZE_TOLERANCE = 0.005
CUT_TOLERANCE = 0.01


# --------------------------------------------------------------------------- #
# Rule evaluation                                                              #
# --------------------------------------------------------------------------- #

def evaluate_condition(metric, op, threshold, snapshot):
    """True/False, or None when the metric is unknown for this symbol."""
    value = snapshot.get(metric)
    if value is None or op not in OPERATORS:
        return None
    return OPERATORS[op][0](float(value), float(threshold))


def evaluate_rule(match, conditions, snapshot):
    """
    Combine condition results. Missing data never counts as a match: ALL is
    False as soon as one condition is False, None if any is unknown; ANY is
    True as soon as one is True, None if any is unknown.
    """
    if not conditions:
        return False
    results = [evaluate_condition(m, op, v, snapshot) for m, op, v in conditions]
    if match == 'ANY':
        if True in results:
            return True
        return None if None in results else False
    if False in results:
        return False
    return None if None in results else True


def rule_symbols(scope, symbol, wishlist, owned):
    if scope == 'SYMBOL':
        return {symbol.upper()} if symbol else set()
    if scope == 'WISHLIST':
        return set(wishlist)
    if scope == 'PORTFOLIO':
        return set(owned)
    return set(wishlist) | set(owned)


def describe_conditions(conditions, snapshot):
    parts = []
    for metric, op, threshold in conditions:
        label = METRIC_LABELS.get(metric, metric)
        parts.append(
            f"{label} {format_value(metric, snapshot.get(metric))} "
            f"(rule: {OPERATORS.get(op, (None, op))[1]} {float(threshold):g})"
        )
    return '; '.join(parts)


def preview_rule(user, scope, symbol, match, conditions):
    """Rows for "Test now": how every in-scope symbol evaluates today. Read-only."""
    symbols = rule_symbols(scope, symbol, wishlist_symbols(user), owned_symbols(user))
    snapshots = build_snapshots(user, symbols)
    rows = []
    for sym in sorted(symbols):
        snap = snapshots[sym]
        rows.append({
            'symbol': sym,
            'name': snap['name'],
            'owned': snap['owned'],
            'result': evaluate_rule(match, conditions, snap),
            'values': [
                {
                    'metric': metric,
                    'label': METRIC_LABELS.get(metric, metric),
                    'value': format_value(metric, snap.get(metric)),
                    'passes': evaluate_condition(metric, op, threshold, snap),
                }
                for metric, op, threshold in conditions
            ],
            'missing_reason': snap['missing_reason'],
        })
    # Matches first, then unknowns, then non-matches
    order = {True: 0, None: 1, False: 2}
    rows.sort(key=lambda r: (order[r['result']], r['symbol']))
    return rows


def owned_context(snapshot):
    if not snapshot.get('owned'):
        return ''
    current = snapshot.get('current_yield')
    best = snapshot.get('best_buy_yield')
    if current is None:
        return 'You own it.'
    if best is None:
        return f"You own it — current yield {current:.2f}%."
    return f"You own it — current yield {current:.2f}% vs your best buy yield {best:.2f}%."


# --------------------------------------------------------------------------- #
# Dividend cut / freeze detection                                              #
# --------------------------------------------------------------------------- #

def regular_dividend_series(stock, frequency):
    """
    [(ex_date, split-adjusted amount)] for a stock's regular dividends, oldest
    first — includes already-declared future ones, so a declared cut is caught
    before it's paid. Special dividends are dropped with the same 1.8×
    rolling-median rule used for dividend growth.
    """
    from research.models import Dividend, StockSplit
    from research.services import StockDataFetcher

    since = date.today() - timedelta(days=5 * 365)
    rows = list(Dividend.objects.filter(stock=stock, date__gte=since).order_by('date'))
    if len(rows) < 2:
        return []

    fetcher = StockDataFetcher()
    splits = list(StockSplit.objects.filter(stock=stock))
    to_date = max(date.today(), rows[-1].date)
    amounts = pd.Series(
        [
            float(d.amount) / (fetcher._effective_split_adjustment_factor(
                stock, d.date, to_date, splits=splits, dividends=rows
            ) or 1.0)
            for d in rows
        ],
        index=[d.date for d in rows],
    )
    window = min(len(amounts), 2 * frequency + 1)
    median = amounts.rolling(window=window, center=True, min_periods=1).median()
    amounts = amounts[amounts <= 1.8 * median]
    return list(amounts.items())


def detect_cut(series, today=None):
    """(ex_date, previous, latest) if the latest regular payment is a recent cut, else None."""
    today = today or date.today()
    if len(series) < 2:
        return None
    (_, prev), (last_date, last) = series[-2], series[-1]
    if last < prev * (1 - CUT_TOLERANCE) and last_date >= today - timedelta(days=CUT_RECENCY_DAYS):
        return last_date, prev, last
    return None


def detect_freeze(series, frequency):
    """
    (streak_start_date, streak_length, amount) when the last `frequency + 1`
    regular payments are all equal — i.e. the dividend has gone a full year
    plus one payment without a raise (5 in a row for a quarterly payer, 13 for
    monthly, 3 semi-annual, 2 annual). Otherwise None.
    """
    needed = frequency + 1
    if len(series) < needed:
        return None
    last = series[-1][1]
    if last <= 0:
        return None
    streak = 0
    for _, amount in reversed(series):
        if abs(amount - last) / last <= FREEZE_TOLERANCE:
            streak += 1
        else:
            break
    if streak < needed:
        return None
    return series[-streak][0], streak, last


# --------------------------------------------------------------------------- #
# Engine                                                                       #
# --------------------------------------------------------------------------- #

class AlertEngine:
    def __init__(self, dry_run=False, now=None):
        self.dry_run = dry_run
        self.now = now or timezone.now()

    # -- state helpers ------------------------------------------------------ #

    def _transition(self, user, key, symbol, result, cooldown_days, rule=None):
        """Record today's result; True if this is a false → true flip outside the cooldown."""
        state = AlertState.objects.filter(user=user, key=key, symbol=symbol).first()
        if state is None:
            state = AlertState(user=user, key=key, symbol=symbol, rule=rule)

        fire = False
        if result and not state.is_matching:
            cooled = (
                state.last_fired_at is None
                or self.now - state.last_fired_at >= timedelta(days=cooldown_days)
            )
            if cooled:
                fire = True
                state.last_fired_at = self.now
            state.is_matching = True
        elif not result:
            state.is_matching = False

        if not self.dry_run:
            state.save()
        return fire

    def _already_reported(self, user, kind, symbol, event_key):
        return AlertEvent.objects.filter(user=user, kind=kind, symbol=symbol, event_key=event_key).exists()

    def _event(self, user, kind, symbol, message, snapshot, rule=None, event_key=''):
        event = AlertEvent(
            user=user, rule=rule, rule_name=rule.name if rule else '', kind=kind,
            symbol=symbol, event_key=event_key, message=message,
            snapshot={k: v for k, v in snapshot.items() if isinstance(v, (int, float, str, bool, type(None)))},
        )
        if not self.dry_run:
            event.save()
        return event

    def _message(self, symbol, snapshot, headline):
        lines = [f"{symbol} ({snapshot['name']}) — {headline}"]
        context = owned_context(snapshot)
        if context:
            lines.append(context)
        if snapshot.get('note'):
            lines.append(f'Your note: "{snapshot["note"]}"')
        return '\n'.join(lines)

    # -- evaluation --------------------------------------------------------- #

    def evaluate_user(self, user):
        """Returns (new_events, unevaluated) where unevaluated is {symbol: reason}."""
        settings = NotificationSettings.for_user(user)
        wishlist = wishlist_symbols(user)
        owned = owned_symbols(user)
        rules = list(AlertRule.objects.filter(user=user, is_active=True).prefetch_related('conditions'))

        all_symbols = set(wishlist) | set(owned)
        for rule in rules:
            all_symbols |= rule_symbols(rule.scope, rule.symbol, wishlist, owned)
        snapshots = build_snapshots(user, all_symbols)

        events, unevaluated = [], {}

        for rule in rules:
            conditions = [(c.metric, c.operator, c.value) for c in rule.conditions.all()]
            for symbol in sorted(rule_symbols(rule.scope, rule.symbol, wishlist, owned)):
                snap = snapshots[symbol]
                result = evaluate_rule(rule.match, conditions, snap)
                if result is None:
                    # Leave state untouched so a one-day data gap neither
                    # re-arms nor fires the rule.
                    unevaluated[symbol] = snap['missing_reason'] or 'missing data'
                    continue
                if self._transition(user, f"rule:{rule.id}", symbol, result, rule.cooldown_days, rule=rule):
                    headline = f"{rule.name}: {describe_conditions(conditions, snap)}"
                    events.append(self._event(user, 'RULE', symbol, self._message(symbol, snap, headline), snap, rule=rule))

        events.extend(self._warnings(user, settings, owned, snapshots))
        return events, unevaluated

    def _warnings(self, user, settings, owned, snapshots):
        from research.models import Dividend, Stock
        from research.services import infer_dividend_frequency

        events = []
        today = self.now.date()
        stocks = {s.symbol: s for s in Stock.objects.filter(symbol__in=owned)}

        for symbol in sorted(owned):
            snap = snapshots[symbol]
            stock = stocks.get(symbol)

            if settings.warn_payout:
                for kind, metric, label in (
                    ('PAYOUT_HIGH', 'payout_ratio', 'Payout ratio'),
                    ('FCF_PAYOUT_HIGH', 'fcf_payout_ratio', 'FCF payout ratio'),
                ):
                    value = snap.get(metric)
                    if value is None:
                        continue
                    if self._transition(user, f"warn:{metric}", symbol, value > 100, WARNING_COOLDOWN_DAYS):
                        headline = f"⚠ {label} is {value:.1f}% — the dividend isn't covered"
                        events.append(self._event(user, kind, symbol, self._message(symbol, snap, headline), snap))

            if stock is None:
                continue

            # ETF distributions vary payment to payment by design — cut/freeze
            # would be pure noise for them.
            if not stock.is_etf and (settings.warn_dividend_cut or settings.warn_dividend_freeze):
                frequency = infer_dividend_frequency(stock)
                series = regular_dividend_series(stock, frequency)

                cut = detect_cut(series, today) if settings.warn_dividend_cut else None
                if cut:
                    ex_date, prev, last = cut
                    key = f"cut:{ex_date.isoformat()}"
                    if not self._already_reported(user, 'DIVIDEND_CUT', symbol, key):
                        headline = (
                            f"⚠ Dividend cut: {prev:.4f} → {last:.4f} per share "
                            f"({(last / prev - 1) * 100:+.1f}%, ex-date {ex_date})"
                        )
                        events.append(self._event(user, 'DIVIDEND_CUT', symbol,
                                                  self._message(symbol, snap, headline), snap, event_key=key))

                freeze = detect_freeze(series, frequency) if settings.warn_dividend_freeze else None
                if freeze:
                    start, length, amount = freeze
                    key = f"freeze:{start.isoformat()}"
                    if not self._already_reported(user, 'DIVIDEND_FREEZE', symbol, key):
                        headline = (
                            f"⚠ Dividend frozen at {amount:.4f} for {length} payments in a row "
                            f"(since {start}) — no raise in over a year"
                        )
                        events.append(self._event(user, 'DIVIDEND_FREEZE', symbol,
                                                  self._message(symbol, snap, headline), snap, event_key=key))

            if settings.warn_ex_dividend:
                upcoming = Dividend.objects.filter(
                    stock=stock, date__gte=today, date__lte=today + timedelta(days=settings.ex_dividend_days)
                ).order_by('date').first()
                if upcoming:
                    key = f"exdiv:{upcoming.date.isoformat()}"
                    if not self._already_reported(user, 'EX_DIVIDEND', symbol, key):
                        headline = f"Ex-dividend date {upcoming.date} ({upcoming.amount} per share)"
                        events.append(self._event(user, 'EX_DIVIDEND', symbol,
                                                  self._message(symbol, snap, headline), snap, event_key=key))
        return events

    # -- delivery ----------------------------------------------------------- #

    def run(self, users=None, stdout=None):
        from .notifications import send_digest

        users = users if users is not None else User.objects.filter(is_active=True)
        summary = []
        for user in users:
            try:
                events, unevaluated = self.evaluate_user(user)
            except Exception:
                logger.exception(f"Alert evaluation failed for {user.username}")
                summary.append((user.username, 'error', 0))
                continue

            if self.dry_run:
                if stdout:
                    for e in events:
                        stdout.write(f"[{user.username}] {e.get_kind_display()} — {e.message}\n")
                    for sym, reason in sorted(unevaluated.items()):
                        stdout.write(f"[{user.username}] couldn't evaluate {sym}: {reason}\n")
                summary.append((user.username, 'dry-run', len(events)))
                continue

            delivered = send_digest(user, unevaluated)
            summary.append((user.username, delivered, len(events)))
        return summary
