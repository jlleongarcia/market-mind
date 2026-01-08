"""
Data fetching services for stock market data using yfinance
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
from django.utils import timezone
from django.db import transaction
import logging

from .models import Stock, HistoricalPrice, Dividend, StockSplit

logger = logging.getLogger(__name__)


class StockDataFetcher:
    """Service class for fetching stock data from yfinance and storing in database"""
    
    def __init__(self):
        self.session = None
    
    def fetch_stock_info(self, symbol: str) -> Optional[Dict]:
        """
        Fetch basic stock information from yfinance
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            
        Returns:
            Dictionary with stock info or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            
            # Try to get info first
            try:
                info = ticker.info
                if info and 'symbol' in info:
                    return {
                        'symbol': symbol.upper(),
                        'name': info.get('longName', info.get('shortName', symbol)),
                        'sector': info.get('sector'),
                        'industry': info.get('industry'),
                        'exchange': info.get('exchange'),
                        'currency': info.get('currency', 'USD'),
                        'country': info.get('country'),
                    }
            except Exception as info_error:
                logger.warning(f"Could not fetch info for {symbol}, trying historical data: {info_error}")
            
            # Fallback: try to get historical data to verify symbol exists
            hist = ticker.history(period="5d")
            if not hist.empty:
                logger.info(f"Symbol {symbol} verified via historical data")
                # Create minimal stock info
                return {
                    'symbol': symbol.upper(),
                    'name': f"{symbol.upper()} (Historical Data Only)",
                    'sector': None,
                    'industry': None,
                    'exchange': None,
                    'currency': 'USD',
                    'country': None,
                }
            
            logger.warning(f"No data found for symbol: {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching info for {symbol}: {str(e)}")
            return None
    
    def fetch_historical_prices(
        self, 
        symbol: str, 
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        period: str = "1y"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical price data from yfinance
        
        Args:
            symbol: Stock ticker symbol
            start_date: Start date for historical data
            end_date: End date for historical data
            period: Period string if dates not provided (e.g., '1y', '5y', 'max')
            
        Returns:
            DataFrame with historical prices or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            
            if start_date and end_date:
                hist = ticker.history(start=start_date, end=end_date)
            else:
                hist = ticker.history(period=period)
            
            if hist.empty:
                logger.warning(f"No historical data found for {symbol}")
                return None
            
            # Reset index to make date a column
            hist.reset_index(inplace=True)
            
            return hist
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {str(e)}")
            return None
    
    def fetch_dividends(self, symbol: str) -> Optional[pd.Series]:
        """
        Fetch dividend history from yfinance
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Series with dividend data or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            dividends = ticker.dividends
            
            if dividends.empty:
                logger.info(f"No dividend data found for {symbol}")
                return None
            
            return dividends
        except Exception as e:
            logger.error(f"Error fetching dividends for {symbol}: {str(e)}")
            return None
    
    def fetch_splits(self, symbol: str) -> Optional[pd.Series]:
        """
        Fetch stock split history from yfinance
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Series with split data or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            splits = ticker.splits
            
            if splits.empty:
                logger.info(f"No split data found for {symbol}")
                return None
            
            return splits
        except Exception as e:
            logger.error(f"Error fetching splits for {symbol}: {str(e)}")
            return None
    
    @transaction.atomic
    def save_stock_info(self, symbol: str) -> Optional[Stock]:
        """
        Fetch and save stock information to database
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Stock instance or None if failed
        """
        info = self.fetch_stock_info(symbol)
        if not info:
            return None
        
        stock, created = Stock.objects.update_or_create(
            symbol=info['symbol'],
            defaults=info
        )
        
        action = "Created" if created else "Updated"
        logger.info(f"{action} stock: {stock.symbol} - {stock.name}")
        
        return stock
    
    @transaction.atomic
    def save_historical_prices(
        self, 
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        period: str = "1y"
    ) -> Tuple[int, int]:
        """
        Fetch and save historical prices to database
        
        Args:
            symbol: Stock ticker symbol
            start_date: Start date for historical data
            end_date: End date for historical data
            period: Period string if dates not provided
            
        Returns:
            Tuple of (created_count, updated_count)
        """
        # Ensure stock exists
        stock = Stock.objects.filter(symbol=symbol.upper()).first()
        if not stock:
            stock = self.save_stock_info(symbol)
            if not stock:
                logger.error(f"Failed to create stock record for {symbol}")
                return (0, 0)
        
        # Fetch historical data
        hist_df = self.fetch_historical_prices(symbol, start_date, end_date, period)
        if hist_df is None or hist_df.empty:
            return (0, 0)
        
        created_count = 0
        updated_count = 0
        
        # Save each price record
        for _, row in hist_df.iterrows():
            try:
                # Extract date (handle both DatetimeIndex and Date column)
                if 'Date' in row:
                    date = row['Date'].date() if hasattr(row['Date'], 'date') else row['Date']
                else:
                    date = row.name.date() if hasattr(row.name, 'date') else row.name
                
                price_data = {
                    'open': Decimal(str(row['Open'])),
                    'high': Decimal(str(row['High'])),
                    'low': Decimal(str(row['Low'])),
                    'close': Decimal(str(row['Close'])),
                    'volume': int(row['Volume']),
                    'adjusted_close': Decimal(str(row.get('Adj Close', row['Close']))),
                }
                
                _, created = HistoricalPrice.objects.update_or_create(
                    stock=stock,
                    date=date,
                    defaults=price_data
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
            except Exception as e:
                logger.error(f"Error saving price record for {symbol} on {date}: {str(e)}")
                continue
        
        logger.info(f"Saved {created_count} new and updated {updated_count} price records for {symbol}")
        return (created_count, updated_count)
    
    @transaction.atomic
    def save_dividends(self, symbol: str) -> int:
        """
        Fetch and save dividend history to database
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Number of dividend records created
        """
        # Ensure stock exists
        stock = Stock.objects.filter(symbol=symbol.upper()).first()
        if not stock:
            stock = self.save_stock_info(symbol)
            if not stock:
                return 0
        
        # Fetch dividends
        dividends = self.fetch_dividends(symbol)
        if dividends is None:
            return 0
        
        created_count = 0
        
        for date, amount in dividends.items():
            try:
                date_obj = date.date() if hasattr(date, 'date') else date
                
                _, created = Dividend.objects.get_or_create(
                    stock=stock,
                    date=date_obj,
                    defaults={'amount': Decimal(str(amount))}
                )
                
                if created:
                    created_count += 1
                    
            except Exception as e:
                logger.error(f"Error saving dividend for {symbol} on {date}: {str(e)}")
                continue
        
        logger.info(f"Saved {created_count} dividend records for {symbol}")
        return created_count
    
    @transaction.atomic
    def save_splits(self, symbol: str) -> int:
        """
        Fetch and save stock split history to database
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Number of split records created
        """
        # Ensure stock exists
        stock = Stock.objects.filter(symbol=symbol.upper()).first()
        if not stock:
            stock = self.save_stock_info(symbol)
            if not stock:
                return 0
        
        # Fetch splits
        splits = self.fetch_splits(symbol)
        if splits is None:
            return 0
        
        created_count = 0
        
        for date, ratio_value in splits.items():
            try:
                date_obj = date.date() if hasattr(date, 'date') else date
                
                # Parse split ratio (e.g., 2.0 means 2:1 split)
                split_from = int(ratio_value) if ratio_value >= 1 else 1
                split_to = 1 if ratio_value >= 1 else int(1 / ratio_value)
                ratio_str = f"{split_from}:{split_to}"
                
                _, created = StockSplit.objects.get_or_create(
                    stock=stock,
                    date=date_obj,
                    defaults={
                        'ratio': ratio_str,
                        'split_from': split_from,
                        'split_to': split_to
                    }
                )
                
                if created:
                    created_count += 1
                    
            except Exception as e:
                logger.error(f"Error saving split for {symbol} on {date}: {str(e)}")
                continue
        
        logger.info(f"Saved {created_count} split records for {symbol}")
        return created_count
    
    def fetch_and_save_all(self, symbol: str, period: str = "1y") -> Dict:
        """
        Fetch and save all data for a stock symbol
        
        Args:
            symbol: Stock ticker symbol
            period: Period for historical data (e.g., '1y', '5y', 'max')
            
        Returns:
            Dictionary with counts of saved records
        """
        results = {
            'symbol': symbol.upper(),
            'success': False,
            'stock_saved': False,
            'prices_created': 0,
            'prices_updated': 0,
            'dividends_saved': 0,
            'splits_saved': 0,
            'errors': []
        }
        
        try:
            # Save stock info
            stock = self.save_stock_info(symbol)
            if stock:
                results['stock_saved'] = True
            else:
                results['errors'].append('Failed to fetch stock info')
                return results
            
            # Save historical prices
            created, updated = self.save_historical_prices(symbol, period=period)
            results['prices_created'] = created
            results['prices_updated'] = updated
            
            # Save dividends
            results['dividends_saved'] = self.save_dividends(symbol)
            
            # Save splits
            results['splits_saved'] = self.save_splits(symbol)
            
            results['success'] = True
            
        except Exception as e:
            logger.error(f"Error in fetch_and_save_all for {symbol}: {str(e)}")
            results['errors'].append(str(e))
        
        return results
