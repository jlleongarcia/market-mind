"""
Management command to backfill declaration_date on existing Dividend records
from Alpha Vantage. Intended to run daily via cron (see Makefile setup-cron
target) since Alpha Vantage's free tier caps out at 25 requests/day — each
run only targets stocks that still have a row (since ~2020, Alpha Vantage's
declaration_date coverage start) that hasn't been checked yet, so it costs
nothing once a row is either filled in or confirmed absent, and safely
catches up newly-added stocks whose data initially came from the yfinance
fallback.

A row is "checked" (declaration_date_checked=True) once Alpha Vantage has
genuinely responded for its exact ex-date — whether or not it had a
declaration_date to give. Rows AV will never be able to fill (its own data
gaps, distinct from rate-limit misses) stop being re-queried, freeing quota
for stocks that can actually still be fixed — see save_dividends in
research/services.py for where checked is set on ordinary syncs too.

Update-only: never creates new Dividend rows and never touches amount /
payment_date on existing ones — it only fills in declaration_date for rows
that already exist in the database.
"""
import time
from datetime import date

from django.core.management.base import BaseCommand

from research.models import Dividend, Stock
from research.services import StockDataFetcher

# Alpha Vantage's DIVIDENDS endpoint only carries declaration_date from
# roughly this point onward — older rows will never get backfilled, so
# excluding them keeps daily reruns from wasting quota. This must be a fixed
# calendar date, not a rolling window relative to "today": a rolling window
# would eventually push a genuinely-recoverable row (e.g. a 2023 dividend)
# out of range simply because time passed, silently dropping it from future
# retries even though Alpha Vantage could still supply it.
AV_DECLARATION_DATE_COVERAGE_START = date(2020, 1, 1)


class Command(BaseCommand):
    help = 'Backfill declaration_date on existing Dividend records from Alpha Vantage (update-only, no new rows)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            type=str,
            help='Specific stock symbols to backfill (optional, defaults to all stocks with a recent dividend row not yet checked against Alpha Vantage)',
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=1,
            help='Delay in seconds between Alpha Vantage calls to avoid rate limits',
        )

    def handle(self, *args, **options):
        symbols = options['symbols']
        delay = options['delay']

        if symbols:
            stocks = Stock.objects.filter(symbol__in=[s.upper() for s in symbols])
        else:
            stocks = Stock.objects.filter(
                dividends__declaration_date__isnull=True,
                dividends__declaration_date_checked=False,
                dividends__date__gte=AV_DECLARATION_DATE_COVERAGE_START,
            ).distinct()

        stock_count = stocks.count()
        self.stdout.write(f"Backfilling declaration_date for {stock_count} stock(s)\n")

        fetcher = StockDataFetcher()
        total_updated = 0
        total_failed = 0

        for i, stock in enumerate(stocks, 1):
            self.stdout.write(f"[{i}/{stock_count}] {stock.symbol}...")

            av_data = fetcher._fetch_dividends_alphavantage(stock.symbol)
            if not av_data:
                total_failed += 1
                self.stdout.write(self.style.WARNING(f"  ⚠ {stock.symbol}: no Alpha Vantage data"))
                if i < stock_count:
                    time.sleep(delay)
                continue

            updated_here = 0
            for entry in av_data:
                ex_date_str   = entry.get('ex_dividend_date', '')
                decl_date_str = entry.get('declaration_date', '')
                if not ex_date_str:
                    continue

                ex_date   = date.fromisoformat(ex_date_str)
                decl_date = date.fromisoformat(decl_date_str) if decl_date_str and decl_date_str != 'None' else None

                if decl_date is not None:
                    updated_here += Dividend.objects.filter(
                        stock=stock, date=ex_date, declaration_date__isnull=True,
                    ).update(declaration_date=decl_date, declaration_date_checked=True)
                elif ex_date < date.today():
                    # AV answered but has no declaration_date for this dividend, and it's
                    # already gone ex — a real, permanent gap, not "not announced yet".
                    Dividend.objects.filter(
                        stock=stock, date=ex_date, declaration_date_checked=False,
                    ).update(declaration_date_checked=True)

            total_updated += updated_here
            self.stdout.write(self.style.SUCCESS(f"  ✓ {stock.symbol}: {updated_here} row(s) updated"))

            if i < stock_count:
                time.sleep(delay)

        self.stdout.write(
            f"\n{'='*50}\n"
            f"Summary: {total_updated} rows updated, {total_failed} stock(s) failed\n"
            f"{'='*50}\n"
        )
