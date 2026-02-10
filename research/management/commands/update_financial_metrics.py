"""
Management command to update financial metrics for stocks
"""
from django.core.management.base import BaseCommand
from research.models import Stock
from research.services import StockDataFetcher
import time


class Command(BaseCommand):
    help = 'Update financial metrics for stocks in the database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            type=str,
            help='Specific stock symbols to update (optional)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Update all stocks in database'
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=1,
            help='Delay in seconds between updates to avoid rate limits'
        )
    
    def handle(self, *args, **options):
        symbols = options['symbols']
        update_all = options['all']
        delay = options['delay']
        
        # Determine which stocks to update
        if symbols:
            stocks = Stock.objects.filter(symbol__in=[s.upper() for s in symbols], is_active=True)
        elif update_all:
            stocks = Stock.objects.filter(is_active=True)
        else:
            self.stdout.write(self.style.ERROR(
                'Please specify --symbols or --all'
            ))
            return
        
        stock_count = stocks.count()
        self.stdout.write(self.style.SUCCESS(
            f"\nUpdating financial metrics for {stock_count} stocks\n"
        ))
        
        fetcher = StockDataFetcher()
        total_success = 0
        total_failed = 0
        
        for i, stock in enumerate(stocks, 1):
            self.stdout.write(f"[{i}/{stock_count}] Updating {stock.symbol}...")
            
            try:
                success = fetcher.save_financial_metrics(stock.symbol)
                
                if success:
                    total_success += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ {stock.symbol}: Metrics updated"
                    ))
                else:
                    total_failed += 1
                    self.stdout.write(self.style.WARNING(
                        f"⚠ {stock.symbol}: Failed to update metrics"
                    ))
                
                # Delay to avoid rate limits (except for last stock)
                if i < stock_count:
                    time.sleep(delay)
                    
            except Exception as e:
                total_failed += 1
                self.stdout.write(self.style.ERROR(
                    f"✗ {stock.symbol}: Error - {str(e)}"
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*50}"
            f"\nSummary: {total_success} successful, {total_failed} failed"
            f"\n{'='*50}\n"
        ))
