"""
Management command to backfill declaration_date and payment_date on existing
Dividend records from FMP (US-listed stocks) or Alpha Vantage (everything
else — FMP's free tier blocks non-US symbols outright, and additionally
premium-gates a subset of well-known US tickers too, e.g. CAT/HON/MO/WDS —
see the FMP-failure fallback below). Intended to run daily via cron (see
Makefile setup-cron target). Alpha Vantage's free tier caps out at 25
requests/day, which is why routing US symbols to FMP (250 requests/day)
matters: with only ~2 LSE symbols needing Alpha Vantage as their primary
source, its thin quota is no longer shared across the whole stock list. Each
run only targets stocks that still have a row (since ~2020, Alpha Vantage's
declaration_date coverage start — see below) that hasn't been checked yet,
so it costs nothing once a row is either filled in or confirmed absent, and
safely catches up newly-added stocks whose data initially came from the
yfinance fallback.

payment_date is filled in as a side effect of the same request — both
providers already return it alongside declaration_date, so there's no extra
API cost to using it. Unlike declaration_date, there's no "confirmed
absent, stop asking" bookkeeping for payment_date: whether a stock keeps
getting re-attempted is governed entirely by declaration_date_checked, so a
row missing only payment_date (declaration_date already known) simply won't
be revisited by this command again — see save_dividends for the fuller sync
path that would eventually pick that up instead.

When an FMP-routed stock's request fails for any reason — including FMP's
per-symbol premium gate, not just a genuine rate limit — this command falls
back to trying Alpha Vantage before giving up. That's deliberately confined
to this command and not shared with save_dividends' ordinary sync path
(research/services.py): this cron runs sequentially and throttled by
--delay, so it's safe to spend Alpha Vantage's near-entirely-unused spare
quota here, whereas save_dividends can run from parallel, uncoordinated
contexts (e.g. auto_record_dividends' ThreadPoolExecutor) where the same
fallback could reintroduce the quota contention the FMP/AV split was built
to fix. Stocks are processed Alpha-Vantage-primary-first specifically so
that fallback spending never starves the handful of genuinely AV-only
(non-US) symbols of their own quota.

A row is "checked" (declaration_date_checked=True) once the routed source has
genuinely responded for its exact ex-date — whether or not it had a
declaration_date to give. Rows that source will never be able to fill (its
own data gaps, distinct from rate-limit misses) stop being re-queried,
freeing quota for stocks that can actually still be fixed — see
save_dividends in research/services.py for where checked is set on ordinary
syncs too.

Update-only: never creates new Dividend rows and never touches amount on
existing ones — it only fills in declaration_date and payment_date (only
when currently null; never overwrites an existing value) for rows that
already exist in the database.
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
    help = 'Backfill declaration_date and payment_date on existing Dividend records from FMP/Alpha Vantage (update-only, no new rows)'

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

        fetcher = StockDataFetcher()

        # Alpha Vantage-primary (non-US) stocks first: their 25/day quota is
        # dedicated to a small handful of symbols and should never be starved
        # by the FMP-fallback attempts below for FMP-primary (US) stocks.
        stocks = sorted(stocks, key=lambda s: fetcher.dividend_source_name(s) == 'FMP')
        stock_count = len(stocks)
        self.stdout.write(f"Backfilling declaration_date/payment_date for {stock_count} stock(s)\n")

        total_updated = 0
        total_pay_updated = 0
        total_failed = 0

        for i, stock in enumerate(stocks, 1):
            primary_source = fetcher.dividend_source_name(stock)
            self.stdout.write(f"[{i}/{stock_count}] {stock.symbol} (via {primary_source})...")

            source = primary_source
            if primary_source == 'FMP':
                data = fetcher._fetch_dividends_fmp(stock.symbol)
                if data is None:
                    # FMP failed — including the "Special Endpoint" premium gate FMP
                    # applies to a subset of well-known US tickers regardless of the
                    # US/non-US split (confirmed live for CAT/HON/MO/WDS: HTTP 402,
                    # not a rate limit). Fall back to Alpha Vantage: its 25/day quota
                    # sits almost entirely unused once the genuinely AV-only (non-US)
                    # stocks above are already checked, so there's usually room to
                    # spare rather than let these retry FMP forever for nothing.
                    if i < stock_count:
                        time.sleep(delay)
                    self.stdout.write(f"    ...FMP failed, trying Alpha Vantage instead...")
                    data = fetcher._fetch_dividends_alphavantage(stock.symbol)
                    source = 'Alpha Vantage (FMP fallback)'
            else:
                data = fetcher._fetch_dividends_alphavantage(stock.symbol)

            if data is None:
                # Transient failure (rate limit, request error, missing key) — worth
                # retrying tomorrow, so don't touch declaration_date_checked.
                total_failed += 1
                self.stdout.write(self.style.WARNING(f"  ⚠ {stock.symbol}: no data from {source}"))
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
            pay_updated_here = 0
            for entry in data:
                ex_date_str   = entry.get('ex_dividend_date', '')
                decl_date_str = entry.get('declaration_date', '')
                pay_date_str  = entry.get('payment_date', '')
                if not ex_date_str:
                    continue

                ex_date   = date.fromisoformat(ex_date_str)
                decl_date = date.fromisoformat(decl_date_str) if decl_date_str and decl_date_str != 'None' else None
                pay_date  = date.fromisoformat(pay_date_str) if pay_date_str and pay_date_str != 'None' else None

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

                # payment_date fills independently of declaration_date — a row can be
                # missing one, the other, or both, and the source can answer either
                # independently of the other. Same fill-only-if-null safety as above:
                # never overwrites an existing value, just a plain filter+update, no
                # "checked" bookkeeping needed since there's no separate payment_date
                # retry loop to stop (declaration_date_checked already governs whether
                # this stock gets re-attempted at all).
                if pay_date is not None:
                    pay_updated_here += Dividend.objects.filter(
                        stock=stock, date=ex_date, payment_date__isnull=True,
                    ).update(payment_date=pay_date)

            total_updated += updated_here
            total_pay_updated += pay_updated_here
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {stock.symbol}: {updated_here} declaration_date, {pay_updated_here} payment_date row(s) updated"
            ))

            if i < stock_count:
                time.sleep(delay)

        self.stdout.write(
            f"\n{'='*50}\n"
            f"Summary: {total_updated} declaration_date rows updated, "
            f"{total_pay_updated} payment_date rows updated, {total_failed} stock(s) failed\n"
            f"{'='*50}\n"
        )
