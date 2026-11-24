"""
Metric registry and per-symbol snapshots that alert conditions are evaluated against.

Everything is read from the DB (research.FinancialMetrics, refreshed by the
daily 9:00 cron) — nothing here calls out to yfinance, so evaluating rules is
cheap and safe to do on page load ("Test now").
"""
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

# (key, label, unit) — unit is only used for display
METRICS = [
    ('yield_vs_5y_avg', 'Yield vs its 5y average', '%'),
    ('week52_percentile', '52-week range percentile', ''),
    ('yield', 'Dividend yield', '%'),
    ('price', 'Price', ''),
    ('price_vs_avg_cost', 'Price vs my average cost', '%'),
    ('pe', 'P/E (trailing)', ''),
    ('payout_ratio', 'Payout ratio', '%'),
    ('fcf_payout_ratio', 'FCF payout ratio', '%'),
    ('chowder', 'Chowder number', ''),
    ('dividend_growth_5y', '5y dividend growth (CAGR)', '%'),
]
METRIC_LABELS = {key: label for key, label, _ in METRICS}
METRIC_UNITS = {key: unit for key, _, unit in METRICS}

# Daily data older than this is treated as missing rather than silently
# evaluated — covers weekends plus a market holiday.
STALE_AFTER_DAYS = 5


def _f(value):
    return float(value) if value is not None else None


def owned_symbols(user):
    from portfolio.models import Position
    return set(
        Position.objects.filter(portfolio__user=user, portfolio__is_active=True, quantity__gt=0)
        .values_list('symbol', flat=True)
    )


def wishlist_symbols(user):
    return set(user.wishlist_items.values_list('symbol', flat=True))


def build_snapshots(user, symbols):
    """
    {symbol: snapshot} where a snapshot holds every METRICS key (None when
    unknown or stale) plus display context: name, currency, owned,
    best_buy_yield, avg_yield_5y, current_yield, note, missing_reason.
    """
    from portfolio.models import Position, Transaction
    from research.models import FinancialMetrics

    symbols = sorted(set(symbols))
    if not symbols:
        return {}

    metrics = {
        fm.stock_id: fm
        for fm in FinancialMetrics.objects.select_related('stock').filter(stock__symbol__in=symbols)
    }

    # Quantity-weighted average cost across all of the user's portfolios
    cost = {}
    for pos in Position.objects.filter(
        portfolio__user=user, portfolio__is_active=True, quantity__gt=0, symbol__in=symbols
    ):
        qty, total = cost.get(pos.symbol, (0.0, 0.0))
        cost[pos.symbol] = (qty + float(pos.quantity), total + float(pos.quantity) * float(pos.average_cost))

    best_buy_yield = dict(
        Transaction.objects.filter(
            portfolio__user=user, transaction_type='BUY', buy_yield__isnull=False, symbol__in=symbols
        ).values('symbol').annotate(best=Max('buy_yield')).values_list('symbol', 'best')
    )
    notes = dict(user.wishlist_items.filter(symbol__in=symbols).values_list('symbol', 'note'))

    today = timezone.now().date()
    snapshots = {}
    for symbol in symbols:
        fm = metrics.get(symbol)
        snap = {key: None for key, _, _ in METRICS}
        snap.update({
            'symbol': symbol,
            'name': fm.stock.name if fm else symbol,
            'currency': fm.stock.currency if fm else '',
            'owned': symbol in cost,
            'best_buy_yield': _f(best_buy_yield.get(symbol)),
            'current_yield': None,
            'avg_yield_5y': None,
            'note': notes.get(symbol, ''),
            'missing_reason': '',
        })
        snapshots[symbol] = snap

        if fm is None:
            snap['missing_reason'] = 'no metrics yet'
            continue
        if fm.last_updated.date() < today - timedelta(days=STALE_AFTER_DAYS):
            snap['missing_reason'] = f'metrics stale (last updated {fm.last_updated.date()})'
            continue

        snap.update({
            'yield': _f(fm.current_yield),
            'current_yield': _f(fm.current_yield),
            'avg_yield_5y': _f(fm.avg_yield_5y),
            'yield_vs_5y_avg': fm.yield_vs_5y_avg,
            'pe': _f(fm.trailing_pe),
            'payout_ratio': _f(fm.payout_ratio),
            'fcf_payout_ratio': _f(fm.fcf_payout_ratio),
            'chowder': _f(fm.chowder_number),
            'dividend_growth_5y': _f(fm.dividend_growth_5y),
        })

        price_fresh = fm.price_date and fm.price_date >= today - timedelta(days=STALE_AFTER_DAYS)
        if price_fresh:
            snap['price'] = _f(fm.current_price)
            snap['week52_percentile'] = fm.week52_percentile
            if symbol in cost and cost[symbol][1] > 0 and fm.current_price:
                avg_cost = cost[symbol][1] / cost[symbol][0]
                snap['price_vs_avg_cost'] = round((float(fm.current_price) / avg_cost - 1) * 100, 1)
        else:
            snap['missing_reason'] = 'price stale' if fm.price_date else 'no price history yet'

    return snapshots


def format_value(metric, value):
    if value is None:
        return '—'
    unit = METRIC_UNITS.get(metric, '')
    if metric in ('yield_vs_5y_avg', 'price_vs_avg_cost'):
        return f"{value:+.1f}%"
    return f"{value:.2f}{unit}"
