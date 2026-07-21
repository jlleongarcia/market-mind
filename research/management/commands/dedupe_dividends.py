"""
Management command to find (and optionally remove) duplicate/implausible
dividend records already sitting in research.Dividend — the patterns
save_dividends' guards (see _is_plausible_dividend_amount / _find_nearby_dividend
in research/services.py) now prevent going forward, but can't retroactively
clean up rows saved before those guards existed (or before a deploy carrying
them has actually shipped). Purely a DB-level scan — makes no external API
calls, so it's safe to run any time regardless of Alpha Vantage/FMP quota.

Two patterns detected, mirroring the live-sync guards exactly:
  * Implausible amount — a dividend with no declaration_date/payment_date
    whose amount is wildly outside the stock's own recent range. Same shape
    as CMCSA's real incident: a $19.47 row with no confirming date sitting
    next to a run of genuine ~$3.96 payouts.
  * Near-duplicate — two dividends for the same stock within a few days of
    each other with a near-identical amount: the same real-world payment
    reported twice under slightly different ex-dates. Seen live for DGRW.L,
    3 days apart, $0.1360/share both times, straight from yfinance's own
    (not this app's) data — it can and did recur after a single manual
    cleanup, since the underlying source still reports both dates.

Rows are evaluated in ex-date order per stock; when two are near-duplicates,
the earlier-dated one is always the one kept (arbitrary but stable — matches
how the two known incidents were manually resolved).

Dry-run by default — prints what it would flag. Pass --apply to actually
delete. Deleting a research.Dividend row also deletes any portfolio.Dividend
rows auto-recorded from it (is_manual=False) — otherwise those would be left
as orphans exactly like the ones auto_record_dividends' own cleanup handles
when a source row disappears through the ordinary sync path instead.

The implausible-amount check is split-adjusted (see _split_adjustment_factor
in research/services.py) but still isn't reliable enough to auto-delete on:
a first production run flagged ~90 old rows, and spot-checking them showed
some are genuine one-off events (e.g. spin-off-related special distributions)
that just happen to look like bad data by amount alone, not fetch errors.
Use --duplicates-only with --apply until that check earns more trust —
near-duplicate detection has had zero false positives so far.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from research.models import Dividend, Stock
from research.services import StockDataFetcher


class Command(BaseCommand):
    help = (
        'Find and optionally remove duplicate/implausible dividend records '
        '(dry-run by default; pass --apply to delete)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols', nargs='+', type=str,
            help='Limit the scan to specific stock symbols (default: every stock with dividend history)',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually delete the flagged rows (default: dry-run report only)',
        )
        parser.add_argument(
            '--window-days', type=int, default=5,
            help='Max day gap between two dividends to treat them as the same event (default: 5)',
        )
        parser.add_argument(
            '--tolerance', type=float, default=0.15,
            help='Max relative amount difference to treat two dividends as the same event (default: 0.15 = 15%%)',
        )
        parser.add_argument(
            '--duplicates-only', action='store_true',
            help=(
                'Skip the implausible-amount check entirely, keep only near-duplicate detection. '
                'The amount check has turned out to need per-row human review on old data — rare '
                'genuine special distributions and split-adjacent entries can look identical to bad '
                'data by amount alone, where duplicates so far have been unambiguous. Recommended '
                'when using --apply.'
            ),
        )

    def _nearby_kept(self, div, kept, window_days, tolerance):
        """Look for a match among already-accepted (earlier) rows for this
        stock — never against rows later in the scan, so a duplicate pair
        only ever gets one side flagged, not both."""
        for k in kept:
            if abs((div.date - k.date).days) <= window_days and k.amount:
                if abs(float(k.amount) - float(div.amount)) <= float(k.amount) * tolerance:
                    return k
        return None

    def handle(self, *args, **options):
        apply_changes = options['apply']
        window_days = options['window_days']
        tolerance = options['tolerance']
        duplicates_only = options['duplicates_only']

        if options['symbols']:
            stocks = Stock.objects.filter(symbol__in=[s.upper() for s in options['symbols']])
        else:
            stocks = Stock.objects.filter(dividends__isnull=False).distinct()
        stocks = stocks.order_by('symbol')

        fetcher = StockDataFetcher()
        flagged = []  # list of (Dividend, reason)

        for stock in stocks:
            kept = []
            for div in Dividend.objects.filter(stock=stock).order_by('date'):
                has_confirming_date = div.payment_date is not None or div.declaration_date is not None

                if not duplicates_only and not fetcher._is_plausible_dividend_amount(
                    stock, div.date, div.amount, has_confirming_date
                ):
                    flagged.append((div, "implausible amount — no declaration/payment date, "
                                          "far outside this stock's recent dividend range"))
                    continue

                if not has_confirming_date:
                    nearby = self._nearby_kept(div, kept, window_days, tolerance)
                    if nearby is not None:
                        flagged.append((div, f"duplicate of id={nearby.id} ({nearby.date}, {nearby.amount}) — "
                                              f"{abs((div.date - nearby.date).days)} day(s) apart, similar amount"))
                        continue

                kept.append(div)

        if not flagged:
            self.stdout.write(self.style.SUCCESS("No duplicate/implausible dividends found."))
            return

        self.stdout.write(f"Found {len(flagged)} flagged dividend row(s):\n")
        for div, reason in flagged:
            self.stdout.write(
                f"  [{div.stock.symbol}] id={div.id} date={div.date} amount={div.amount} "
                f"pay={div.payment_date} decl={div.declaration_date} — {reason}"
            )

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "\nDry run — nothing deleted. Re-run with --apply to delete these rows."
            ))
            return

        from portfolio.models import Dividend as PortfolioDividend

        deleted_research = 0
        deleted_portfolio = 0
        with transaction.atomic():
            for div, _ in flagged:
                deleted_portfolio += PortfolioDividend.objects.filter(
                    symbol=div.stock.symbol, ex_dividend_date=div.date, is_manual=False,
                ).delete()[0]
                div.delete()
                deleted_research += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDeleted {deleted_research} research.Dividend row(s) and "
            f"{deleted_portfolio} orphaned portfolio.Dividend row(s)."
        ))
