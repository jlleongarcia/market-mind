"""
Management command to backfill declaration_date on existing Dividend records
from FMP (US-listed stocks) or Alpha Vantage (everything else — FMP's free
tier blocks non-US symbols outright). Intended to run daily via cron (see
Makefile setup-cron target). Alpha Vantage's free tier caps out at 25
requests/day, which is why routing US symbols to FMP (250 requests/day)
matters: with only ~2 LSE symbols left needing Alpha Vantage, its thin quota
is no longer shared across the whole stock list. Each run only targets
stocks that still have a row (since ~2020, Alpha Vantage's declaration_date
coverage start — see below) that hasn't been checked yet, so it costs
nothing once a row is either filled in or confirmed absent, and safely
catches up newly-added stocks whose data initially came from the yfinance
fallback.

A row is "checked" (declaration_date_checked=True) once the routed source has
genuinely responded for its exact ex-date — whether or not it had a
declaration_date to give. Rows that source will never be able to fill (its
own data gaps, distinct from rate-limit misses) stop being re-queried,
freeing quota for stocks that can actually still be fixed — see
save_dividends in research/services.py for where checked is set on ordinary
syncs too.

Update-only: never creates new Dividend rows and never touches amount /
payment_date on existing ones — it only fills in declaration_date for rows
that already exist in the database.
"""
import time
from datetime import date

from django.core.management.base import BaseCommand

from research.models import Dividend, Stock
from research.services import StockDataFetcher

# Both Alpha Vantage's DIVIDENDS endpoint and FMP's /stable/dividends only
# carry declaration_date from roughly this point onward (Alpha Vantage's
# observed coverage start; FMP's is actually deeper, but there's no harm
# sharing the same conservative boundary) — older rows will never get
# backfilled, so excluding them keeps daily reruns from wasting quota. This
# must be a fixed calendar date, not a rolling window relative to "today": a
# rolling window would eventually push a genuinely-recoverable row (e.g. a
# 2023 dividend) out of range simply because time passed, silently dropping
# it from future retries even though the source could still supply it.
AV_DECLARATION_DATE_COVERAGE_START = date(2020, 1, 1)


class Command(BaseCommand):
    help = 'Backfill declaration_date on existing Dividend records from FMP/Alpha Vantage (update-only, no new rows)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            type=str,
            help='Specific stock symbols to backfill (optional, defaults to all stocks with a recent dividend row not yet checked)',
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=1,
            help='Delay in seconds between API calls to avoid rate limits',
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
            source = fetcher.dividend_source_name(stock)
            self.stdout.write(f"[{i}/{stock_count}] {stock.symbol} (via {source})...")

            data = fetcher._fetch_dividends_primary(stock)
            if data is None:
                # Transient failure (rate limit, request error, missing key) — worth
                # retrying tomorrow, so don't touch declaration_date_checked.
                total_failed += 1
                self.stdout.write(self.style.WARNING(f"  ⚠ {stock.symbol}: no {source} data"))
                if i < stock_count:
                    time.sleep(delay)
                continue

            if not data:
                # A clean response with zero entries: the source has genuinely never
                # heard of any dividend for this symbol (confirmed live for LSE ETFs
                # IDUS.L/DGRW.L on Alpha Vantage) — mark every eligible row checked so
                # this symbol stops being retried forever, instead of silently burning
                # one request/day indefinitely on a symbol that will never answer.
                marked = Dividend.objects.filter(
                    stock=stock, declaration_date__isnull=True, declaration_date_checked=False,
                    date__gte=AV_DECLARATION_DATE_COVERAGE_START,
                ).update(declaration_date_checked=True)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {stock.symbol}: no dividend history on {source} — marked {marked} row(s) checked"
                ))
                if i < stock_count:
                    time.sleep(delay)
                continue

            updated_here = 0
            for entry in data:
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
                    # The source answered but has no declaration_date for this dividend,
                    # and it's already gone ex — a real, permanent gap, not "not announced yet".
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
