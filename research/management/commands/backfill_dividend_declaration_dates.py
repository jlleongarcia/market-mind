"""
One-off management command to backfill declaration_date on existing Dividend
records from Alpha Vantage.

Update-only: never creates new Dividend rows and never touches amount /
payment_date on existing ones — it only fills in declaration_date for rows
that already exist in the database.
"""
import time
from datetime import date

from django.core.management.base import BaseCommand

from research.models import Dividend, Stock
from research.services import StockDataFetcher


class Command(BaseCommand):
    help = 'Backfill declaration_date on existing Dividend records from Alpha Vantage (update-only, no new rows)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            type=str,
            help='Specific stock symbols to backfill (optional, defaults to all stocks with dividend history)',
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
            stocks = Stock.objects.filter(dividends__isnull=False).distinct()

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
                if not ex_date_str or not decl_date_str or decl_date_str == 'None':
                    continue

                updated_here += Dividend.objects.filter(
                    stock=stock, date=date.fromisoformat(ex_date_str), declaration_date__isnull=True,
                ).update(declaration_date=date.fromisoformat(decl_date_str))

            total_updated += updated_here
            self.stdout.write(self.style.SUCCESS(f"  ✓ {stock.symbol}: {updated_here} row(s) updated"))

            if i < stock_count:
                time.sleep(delay)

        self.stdout.write(
            f"\n{'='*50}\n"
            f"Summary: {total_updated} rows updated, {total_failed} stock(s) failed\n"
            f"{'='*50}\n"
        )
