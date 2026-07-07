"""
One-off management command to aggressively backfill declaration_date and
payment_date for every tracked stock using the Alpha Vantage PREMIUM key
(ALPHA_VANTAGE_PREMIUM_API_KEY) — a temporary, paid-for-one-month upgrade
(75 requests/minute, no daily cap) that removes both the free-tier 25/day
ceiling and the need to route through FMP at all.

Deliberately kept 100% separate from backfill_dividend_declaration_dates
(the permanent, free-tier-safe daily cron command) and from
StockDataFetcher (research/services.py) — this duplicates the small amount
of fetch/parse logic it needs rather than importing it, so nothing about
the existing hybrid FMP/Alpha-Vantage pipeline, its scripts, or its API
keys is touched by adding this. Meant to be deleted (or just left unused)
once the premium month ends; the daily cron keeps working exactly as
before regardless.

Three differences from the daily cron command, all deliberate:
  - Processes every tracked stock unconditionally (or a --symbols subset),
    not just ones still flagged declaration_date_checked=False. Most
    stocks are already "resolved" under the free-tier logic and would be
    skipped forever by the daily cron, but they can still be missing
    payment_date, which the free-tier command only fills as a side effect
    of stocks it happens to revisit for declaration_date reasons.
  - Calls Alpha Vantage directly for every stock, US and non-US alike —
    skipping FMP (and its per-symbol premium gate) entirely. Pointless to
    route around Alpha Vantage's limits when they're effectively gone for
    a month.
  - No 2020-01-01 coverage-start boundary. That boundary exists on the
    free-tier command purely to avoid wasting scarce quota on symbols with
    no realistic chance of a match; with the premium cap effectively gone,
    there's no reason to skip older rows — if Alpha Vantage genuinely has
    nothing for them the update simply matches zero rows, same as always.

Not registered in cron or the Makefile — run manually as needed during the
paid month via scripts/backfill_dividend_data_premium.sh (or directly).
See DIVIDEND_AUTOMATION.md.
"""
import time
from datetime import date
from typing import Dict, List, Optional

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from research.models import Dividend, Stock


def _fetch_alphavantage_dividends(symbol: str, api_key: str) -> Optional[List[Dict]]:
    """
    Self-contained copy of the fetch/parse logic in
    StockDataFetcher._fetch_dividends_alphavantage (research/services.py),
    duplicated rather than imported so this one-off premium script never
    touches the shared service code the permanent daily cron depends on.

    Same return shape: a list of dicts with ex_dividend_date, payment_date,
    declaration_date, record_date, amount — or None on any error.
    """
    try:
        resp = requests.get(
            'https://www.alphavantage.co/query',
            params={'function': 'DIVIDENDS', 'symbol': symbol.upper(), 'apikey': api_key},
            timeout=10,
        )
        data = resp.json()
        if 'data' not in data:
            return None
        return data['data']
    except Exception:
        return None


class Command(BaseCommand):
    help = (
        'One-off premium-key blitz: backfill declaration_date/payment_date for '
        'every stock via Alpha Vantage premium. Not part of the daily cron.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            type=str,
            help='Specific stock symbols to backfill (optional, defaults to every tracked stock)',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help=(
                'Delay in seconds between API calls (default 1.0s — safely under '
                'the 75/min premium cap and the ~1 req/sec burst floor Alpha '
                'Vantage enforces regardless of tier)'
            ),
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, 'ALPHA_VANTAGE_PREMIUM_API_KEY', '')
        if not api_key:
            raise CommandError(
                'ALPHA_VANTAGE_PREMIUM_API_KEY is not set in .env — this command '
                'only ever uses the premium key, never the free-tier one.'
            )

        symbols = options['symbols']
        delay = options['delay']

        if symbols:
            stocks = Stock.objects.filter(symbol__in=[s.upper() for s in symbols])
        else:
            stocks = Stock.objects.all()

        stocks = list(stocks.order_by('symbol'))
        stock_count = len(stocks)
        self.stdout.write(
            f"Premium blitz: refreshing declaration_date/payment_date for {stock_count} stock(s)\n"
        )

        total_decl_updated = 0
        total_pay_updated = 0
        total_failed = 0

        for i, stock in enumerate(stocks, 1):
            self.stdout.write(f"[{i}/{stock_count}] {stock.symbol}...")

            data = _fetch_alphavantage_dividends(stock.symbol, api_key)

            if data is None:
                total_failed += 1
                self.stdout.write(self.style.WARNING(f"  ⚠ {stock.symbol}: no data (error or rate limit)"))
                if i < stock_count:
                    time.sleep(delay)
                continue

            if not data:
                marked = Dividend.objects.filter(
                    stock=stock, declaration_date__isnull=True, declaration_date_checked=False,
                ).update(declaration_date_checked=True)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {stock.symbol}: no dividend history on Alpha Vantage — marked {marked} row(s) checked"
                ))
                if i < stock_count:
                    time.sleep(delay)
                continue

            decl_updated = 0
            pay_updated = 0
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
                    decl_updated += Dividend.objects.filter(
                        stock=stock, date=ex_date, declaration_date__isnull=True,
                    ).update(declaration_date=decl_date, declaration_date_checked=True)
                elif ex_date < date.today():
                    Dividend.objects.filter(
                        stock=stock, date=ex_date, declaration_date_checked=False,
                    ).update(declaration_date_checked=True)

                if pay_date is not None:
                    pay_updated += Dividend.objects.filter(
                        stock=stock, date=ex_date, payment_date__isnull=True,
                    ).update(payment_date=pay_date)

            total_decl_updated += decl_updated
            total_pay_updated += pay_updated
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {stock.symbol}: {decl_updated} declaration_date, {pay_updated} payment_date row(s) updated"
            ))

            if i < stock_count:
                time.sleep(delay)

        self.stdout.write(
            f"\n{'='*50}\n"
            f"Summary: {total_decl_updated} declaration_date rows, "
            f"{total_pay_updated} payment_date rows updated, {total_failed} stock(s) failed\n"
            f"{'='*50}\n"
        )
