"""
Management command to fetch stock data from yfinance
"""
from django.core.management.base import BaseCommand
from research.services import StockDataFetcher
import time


class Command(BaseCommand):
    help = 'Fetch stock data from yfinance and store in database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'symbols',
            nargs='+',
            type=str,
            help='Stock symbols to fetch (e.g., AAPL MSFT GOOGL)'
        )
        parser.add_argument(
            '--period',
            type=str,
            default='1y',
            help='Period for historical data (e.g., 1mo, 3mo, 1y, 5y, max)'
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=2,
            help='Delay in seconds between fetches to avoid rate limits'
        )
    
    def handle(self, *args, **options):
        symbols = options['symbols']
        period = options['period']
        delay = options['delay']
        
        self.stdout.write(self.style.SUCCESS(
            f"\nFetching data for {len(symbols)} symbols with period={period}\n"
        ))
        
        fetcher = StockDataFetcher()
        total_success = 0
        total_failed = 0
        
        for i, symbol in enumerate(symbols, 1):
            self.stdout.write(f"\n[{i}/{len(symbols)}] Fetching {symbol}...")
            
            try:
                result = fetcher.fetch_and_save_all(symbol, period=period)
                
                if result['success']:
                    total_success += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ {symbol}: "
                        f"{result['prices_created']} prices, "
                        f"{result['dividends_saved']} dividends, "
                        f"{result['splits_saved']} splits"
                    ))
                else:
                    total_failed += 1
                    self.stdout.write(self.style.ERROR(
                        f"✗ {symbol}: {', '.join(result['errors'])}"
                    ))
                
                # Delay to avoid rate limits (except for last symbol)
                if i < len(symbols):
                    time.sleep(delay)
                    
            except Exception as e:
                total_failed += 1
                self.stdout.write(self.style.ERROR(
                    f"✗ {symbol}: Unexpected error - {str(e)}"
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*50}"
            f"\nSummary: {total_success} successful, {total_failed} failed"
            f"\n{'='*50}\n"
        ))
