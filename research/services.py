"""
Data fetching services for stock market data using yfinance
"""
import math
import threading
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
from django.utils import timezone
from django.db import transaction
import logging

from .models import Stock, HistoricalPrice, Dividend, StockSplit, FinancialMetrics

logger = logging.getLogger(__name__)


class StockDataFetcher:
    """Service class for fetching stock data from yfinance and storing in database"""
    
    def __init__(self):
        self.session = None
    
    def fetch_stock_info(self, symbol: str, prefer_us_exchanges: bool = True) -> Optional[Dict]:
        """
        Fetch basic stock information from yfinance
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            prefer_us_exchanges: If True, prioritize US exchanges (NYSE, NASDAQ)
            
        Returns:
            Dictionary with stock info or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            
            # Try to get info first
            try:
                info = ticker.info
                if info and 'symbol' in info:
                    exchange = info.get('exchange', '')
                    
                    # If preferring US exchanges, check if this is a non-US exchange
                    # and if symbol without suffix might be US
                    if prefer_us_exchanges and exchange and '.' in symbol:
                        # Symbol has exchange suffix (e.g., 'INTC.L')
                        # Try the base symbol without suffix for US exchanges
                        base_symbol = symbol.split('.')[0]
                        logger.info(f"Symbol {symbol} has exchange suffix, trying US version: {base_symbol}")
                        us_info = self.fetch_stock_info(base_symbol, prefer_us_exchanges=False)
                        if us_info and us_info.get('exchange') in ['NMS', 'NYQ', 'NYSE', 'NASDAQ']:
                            logger.info(f"Found US listing for {base_symbol}, using instead of {symbol}")
                            return us_info
                    
                    return {
                        'symbol': symbol.upper(),
                        'name': info.get('longName', info.get('shortName', symbol)),
                        'sector': info.get('sector'),
                        'industry': info.get('industry'),
                        'exchange': exchange,
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
    def _fetch_dividends_alphavantage(self, symbol: str) -> Optional[List[Dict]]:
        """
        Fetch full dividend history from Alpha Vantage, including payment_date.

        Returns a list of dicts with keys: ex_dividend_date, payment_date,
        declaration_date, record_date, amount.  Returns None if the API key is
        missing, the rate limit is hit, or any other error occurs — callers
        should fall back to yfinance in that case.
        """
        from django.conf import settings
        import requests as _requests

        api_key = getattr(settings, 'ALPHA_VANTAGE_API_KEY', '')
        if not api_key:
            return None

        try:
            resp = _requests.get(
                'https://www.alphavantage.co/query',
                params={'function': 'DIVIDENDS', 'symbol': symbol.upper(), 'apikey': api_key},
                timeout=10,
            )
            data = resp.json()

            if 'data' not in data:
                # Rate-limit or error message from AV
                logger.warning(f"Alpha Vantage DIVIDENDS no data for {symbol}: {data}")
                return None

            return data['data']

        except Exception as e:
            logger.warning(f"Alpha Vantage DIVIDENDS fetch failed for {symbol}: {e}")
            return None

    def _fetch_payment_date_map_yfinance(self, symbol: str) -> dict:
        """
        Fallback: build a {ex_date: pay_date} map from yfinance calendar / info.
        Only covers the single next upcoming dividend; used when Alpha Vantage
        is unavailable.
        """
        from datetime import datetime as dt
        payment_map = {}
        try:
            ticker = yf.Ticker(symbol.upper())

            cal = ticker.calendar
            if isinstance(cal, dict):
                ex_d  = cal.get('Ex-Dividend Date')
                pay_d = cal.get('Dividend Date')
                if ex_d is not None and pay_d is not None:
                    ex_obj  = ex_d.date()  if hasattr(ex_d,  'date') else ex_d
                    pay_obj = pay_d.date() if hasattr(pay_d, 'date') else pay_d
                    payment_map[ex_obj] = pay_obj

            info = ticker.info
            ex_ts  = info.get('exDividendDate')
            pay_ts = info.get('dividendDate')
            if ex_ts and pay_ts:
                ex_obj  = dt.utcfromtimestamp(ex_ts).date()
                pay_obj = dt.utcfromtimestamp(pay_ts).date()
                payment_map.setdefault(ex_obj, pay_obj)

        except Exception as e:
            logger.warning(f"yfinance payment date map failed for {symbol}: {e}")
        return payment_map

    def save_dividends(self, symbol: str) -> int:
        """
        Fetch and save dividend history to database.

        Primary source: Alpha Vantage DIVIDENDS endpoint (has full payment_date
        history).  Falls back to yfinance when AV is unavailable or rate-limited.
        """
        stock = Stock.objects.filter(symbol=symbol.upper()).first()
        if not stock:
            stock = self.save_stock_info(symbol)
            if not stock:
                return 0

        # --- Alpha Vantage path (preferred) ---
        av_data = self._fetch_dividends_alphavantage(symbol)
        if av_data:
            created_count = 0
            for entry in av_data:
                try:
                    ex_date_str   = entry.get('ex_dividend_date', '')
                    pay_date_str  = entry.get('payment_date', '')
                    decl_date_str = entry.get('declaration_date', '')
                    amount_str    = entry.get('amount', '')
                    if not ex_date_str or not amount_str:
                        continue

                    ex_date  = date.fromisoformat(ex_date_str)
                    # AV sends the string 'None' for records without a known payment/declaration date
                    pay_date  = date.fromisoformat(pay_date_str) if pay_date_str and pay_date_str != 'None' else None
                    decl_date = date.fromisoformat(decl_date_str) if decl_date_str and decl_date_str != 'None' else None
                    # AV has genuinely answered for this ex-date: either it gave us a
                    # declaration_date, or the dividend has already gone ex so a missing
                    # declaration_date means AV will never have one — not "not announced yet".
                    decl_checked = decl_date is not None or ex_date < date.today()

                    defaults = {'amount': Decimal(str(amount_str))}
                    if pay_date is not None:
                        defaults['payment_date'] = pay_date
                    if decl_date is not None:
                        defaults['declaration_date'] = decl_date

                    obj, created = Dividend.objects.get_or_create(
                        stock=stock,
                        date=ex_date,
                        defaults={
                            **defaults, 'payment_date': pay_date, 'declaration_date': decl_date,
                            'declaration_date_checked': decl_checked,
                        },
                    )
                    if not created:
                        obj.amount = Decimal(str(amount_str))
                        if pay_date is not None:
                            obj.payment_date = pay_date
                        if decl_date is not None:
                            obj.declaration_date = decl_date
                        if decl_checked:
                            obj.declaration_date_checked = True
                        obj.save()

                    if created:
                        created_count += 1

                except Exception as e:
                    logger.error(f"Error saving AV dividend for {symbol} on {entry}: {e}")
                    continue

            logger.info(f"Alpha Vantage: saved/updated {len(av_data)} dividend records for {symbol} ({created_count} new)")
            return created_count

        # --- yfinance fallback ---
        logger.info(f"Alpha Vantage unavailable for {symbol}, falling back to yfinance")
        dividends = self.fetch_dividends(symbol)
        if dividends is None:
            return 0

        payment_map = self._fetch_payment_date_map_yfinance(symbol)
        created_count = 0

        for div_date, amount in dividends.items():
            try:
                date_obj = div_date.date() if hasattr(div_date, 'date') else div_date
                pay_date = payment_map.get(date_obj)

                defaults = {'amount': Decimal(str(amount))}
                if pay_date is not None:
                    defaults['payment_date'] = pay_date

                obj, created = Dividend.objects.get_or_create(
                    stock=stock,
                    date=date_obj,
                    defaults={**defaults, 'payment_date': pay_date},
                )
                if not created:
                    obj.amount = Decimal(str(amount))
                    if pay_date is not None:
                        obj.payment_date = pay_date
                    obj.save()

                if created:
                    created_count += 1

            except Exception as e:
                logger.error(f"Error saving yfinance dividend for {symbol} on {div_date}: {e}")
                continue

        logger.info(f"yfinance fallback: saved {created_count} new dividend records for {symbol}")
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
    
    def calculate_dividend_growth(self, symbol: str) -> Dict[str, Optional[Decimal]]:
        """
        Calculate 1-year and 5-year dividend growth rates
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Dictionary with growth_1y and growth_5y (as percentages)
        """
        result = {
            'growth_1y': None,
            'growth_5y': None
        }
        
        try:
            # Get stock instance
            stock = Stock.objects.filter(symbol=symbol.upper()).first()
            if not stock:
                return result
            
            # Get all dividends ordered by date
            dividends = Dividend.objects.filter(stock=stock).order_by('date')
            
            if dividends.count() < 2:
                logger.info(f"Insufficient dividend data for {symbol}")
                return result
            
            # Convert to DataFrame for easier calculation
            df = pd.DataFrame(list(dividends.values('date', 'amount')))
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()

            now = datetime.now()
            # Exclude future-dated dividends (Alpha Vantage includes declared but unpaid ones)
            df = df[df.index <= pd.Timestamp(now.date())]

            if len(df) < 2:
                logger.info(f"Insufficient past dividend data for {symbol}")
                return result
            
            # 1Y growth: last 4 dividends / penultimate 4 dividends − 1
            # Using positional slicing avoids time-window edge cases where an
            # off-by-one quarter produces 5 recent vs 3 prior and inflates the result.
            try:
                if len(df) >= 8:
                    recent_4   = float(df['amount'].iloc[-4:].sum())
                    previous_4 = float(df['amount'].iloc[-8:-4].sum())
                    if previous_4 > 0 and recent_4 > 0:
                        growth_1y = (recent_4 / previous_4 - 1) * 100
                        result['growth_1y'] = Decimal(str(round(growth_1y, 2)))
                        logger.info(f"1Y dividend growth for {symbol}: {result['growth_1y']}%")
                else:
                    logger.info(f"Not enough dividends for 1Y growth ({len(df)} records) for {symbol}")
            except Exception as e:
                logger.warning(f"Could not calculate 1Y growth for {symbol}: {str(e)}")

            # 5Y growth CAGR: last 4 dividends vs the 4 most recent dividends
            # paid on or before 5 years ago, raised to the 1/5 power.
            try:
                five_years_ago = pd.Timestamp((now - timedelta(days=365 * 5)).date())
                df_old = df[df.index <= five_years_ago]
                if len(df_old) >= 4:
                    recent_4  = float(df['amount'].iloc[-4:].sum())
                    base_4    = float(df_old['amount'].iloc[-4:].sum())
                    if base_4 > 0 and recent_4 > 0:
                        cagr = ((recent_4 / base_4) ** (1 / 5) - 1) * 100
                        result['growth_5y'] = Decimal(str(round(cagr, 2)))
                        logger.info(f"5Y dividend growth for {symbol}: {result['growth_5y']}%")
                else:
                    logger.info(f"Not enough historical dividends for 5Y growth for {symbol}")
            except Exception as e:
                logger.warning(f"Could not calculate 5Y growth for {symbol}: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error calculating dividend growth for {symbol}: {str(e)}")
        
        return result
    
    def fetch_financial_metrics(self, symbol: str) -> Optional[Dict]:
        """
        Fetch financial metrics from yfinance
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Dictionary with financial metrics or None if failed
        """
        try:
            ticker = yf.Ticker(symbol.upper())
            info = ticker.info
            
            if not info:
                logger.warning(f"No info available for {symbol}")
                return None
            
            # Extract metrics with smart conversion to percentages
            metrics = {}
            
            # P/E ratios and beta - already in correct format
            metrics['trailing_pe'] = info.get('trailingPE')
            metrics['forward_pe'] = info.get('forwardPE')
            metrics['beta'] = info.get('beta')
            
            # Payout ratio - yfinance returns as decimal (0.6672 = 66.72%)
            payout = info.get('payoutRatio')
            if payout is not None:
                # If value is between 0 and 1, it's a decimal that needs conversion
                metrics['payout_ratio'] = payout * 100 if 0 < payout <= 1 else payout
            else:
                metrics['payout_ratio'] = None
            
            # FCF Payout Ratio - calculate from FCF and dividend data
            fcf = info.get('freeCashflow')
            metrics['fcf_payout_ratio'] = None
            
            if fcf and fcf > 0:
                try:
                    # Get dividend per share and shares outstanding to calculate total dividends
                    dividend_rate = info.get('dividendRate')  # Annual dividend per share
                    shares_outstanding = info.get('sharesOutstanding')
                    
                    if dividend_rate and shares_outstanding:
                        total_dividends = dividend_rate * shares_outstanding
                        fcf_payout = (total_dividends / fcf) * 100
                        metrics['fcf_payout_ratio'] = min(fcf_payout, 999.99)  # Cap at 999.99%
                        logger.info(f"FCF Payout Ratio for {symbol}: {metrics['fcf_payout_ratio']:.2f}%")
                except Exception as e:
                    logger.warning(f"Could not calculate FCF payout ratio for {symbol}: {str(e)}")
            
            # Annual dividend per share — direct dollar amount, no unit ambiguity
            div_rate = info.get('dividendRate')
            metrics['dividend_rate'] = div_rate if div_rate else None

            # Correct yield derived from dividend_rate / price (avoids yfinance % format ambiguity)
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if div_rate and current_price and current_price > 0:
                metrics['_yield_pct'] = (div_rate / current_price) * 100
            else:
                metrics['_yield_pct'] = None

            # dividend_yield kept for display/backward compatibility only
            div_yield = info.get('dividendYield')
            if div_yield is not None:
                metrics['dividend_yield'] = div_yield * 100 if 0 < div_yield <= 1 else div_yield
            else:
                metrics['dividend_yield'] = None

            # Convert to Decimal for database storage — skip transient _ keys
            for key, value in list(metrics.items()):
                if key.startswith('_'):
                    continue
                if value is not None:
                    try:
                        metrics[key] = Decimal(str(round(value, 2)))
                    except:
                        metrics[key] = None
            
            # Check if stock pays dividends
            pays_dividend = bool(info.get('dividendYield') or info.get('dividendRate'))
            metrics['pays_dividend'] = pays_dividend
            
            logger.info(f"Fetched financial metrics for {symbol} - Pays dividend: {pays_dividend}")
            return metrics
            
        except Exception as e:
            logger.error(f"Error fetching financial metrics for {symbol}: {str(e)}")
            return None
    
    @transaction.atomic
    def save_financial_metrics(self, symbol: str) -> bool:
        """
        Fetch and save financial metrics to database
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure stock exists
            stock = Stock.objects.filter(symbol=symbol.upper()).first()
            if not stock:
                stock = self.save_stock_info(symbol)
                if not stock:
                    logger.error(f"Failed to create stock record for {symbol}")
                    return False
            
            # Fetch metrics from yfinance
            metrics = self.fetch_financial_metrics(symbol)
            if not metrics:
                logger.warning(f"No financial metrics available for {symbol}")
                return False
            
            pays_dividend = metrics.pop('pays_dividend', False)
            yield_pct     = metrics.pop('_yield_pct', None)   # transient — not a DB column

            # Calculate dividend growth if stock pays dividends
            if pays_dividend:
                growth_data = self.calculate_dividend_growth(symbol)
                metrics['dividend_growth_1y'] = growth_data['growth_1y']
                metrics['dividend_growth_5y'] = growth_data['growth_5y']

                # Chowder = correct_yield + 5Y dividend growth rate
                if yield_pct and metrics.get('dividend_growth_5y'):
                    chowder = yield_pct + float(metrics['dividend_growth_5y'])
                    metrics['chowder_number'] = Decimal(str(round(chowder, 2)))
                else:
                    metrics['chowder_number'] = None
            else:
                # Non-dividend stock - set all dividend metrics to None
                metrics['dividend_growth_1y'] = None
                metrics['dividend_growth_5y'] = None
                metrics['chowder_number'] = None
            
            metrics['pays_dividend'] = pays_dividend
            
            # Save to database
            financial_metrics, created = FinancialMetrics.objects.update_or_create(
                stock=stock,
                defaults=metrics
            )
            
            action = "Created" if created else "Updated"
            logger.info(f"{action} financial metrics for {symbol}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving financial metrics for {symbol}: {str(e)}")
            return False
    
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
            'financial_metrics_saved': False,
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
            
            # Save financial metrics
            if self.save_financial_metrics(symbol):
                results['financial_metrics_saved'] = True
            else:
                results['errors'].append('Failed to fetch financial metrics')
            
            results['success'] = True
            
        except Exception as e:
            logger.error(f"Error in fetch_and_save_all for {symbol}: {str(e)}")
            results['errors'].append(str(e))

        return results


class PriceCacheService:
    """
    Real-time price layer with market-aware TTL.

    During NYSE hours (Mon–Fri 09:30–16:00 ET) prices are refreshed every 15 min
    from yfinance (15-min delayed, same as Yahoo Finance).  Outside market hours
    a 2-hour TTL keeps the last known close in cache.

    All pages share the same per-symbol cache key so discrepancies between views
    are impossible.  After market close the day's OHLC is lazily persisted to
    HistoricalPrice in a background thread.
    """

    LIVE_TTL = 15 * 60      # seconds — during market hours
    CLOSED_TTL = 2 * 3600   # seconds — outside market hours

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_market_open() -> bool:
        """True when NYSE regular session is active (no holiday check)."""
        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo('America/New_York'))
        if now.weekday() >= 5:          # Saturday or Sunday
            return False
        open_time  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
        close_time = now.replace(hour=16, minute=0,  second=0, microsecond=0)
        return open_time <= now <= close_time

    @classmethod
    def get_prices(cls, symbols: list) -> dict:
        """
        Return {symbol: {'price': float, 'is_live': bool, 'price_date': str}}.

        is_live=True  → fresh yfinance price (intraday, 15-min delayed)
        is_live=False → last close from HistoricalPrice DB
        price_date    → ISO date string ('YYYY-MM-DD')
        """
        from django.core.cache import cache

        result = {}
        to_fetch = []

        for symbol in symbols:
            cached = cache.get(f"live_price_{symbol}")
            if cached is not None:
                result[symbol] = cached
            else:
                to_fetch.append(symbol)

        if to_fetch:
            is_open  = cls.is_market_open()
            ttl      = cls.LIVE_TTL if is_open else cls.CLOSED_TTL
            today    = date.today().isoformat()

            yf_prices = cls._fetch_yfinance_prices(to_fetch)

            for symbol in to_fetch:
                if symbol in yf_prices:
                    entry = {
                        'price':      yf_prices[symbol],
                        'is_live':    is_open,
                        'price_date': today,
                    }
                    cache.set(f"live_price_{symbol}", entry, timeout=ttl)
                    result[symbol] = entry

            # After close: persist today's candle to HistoricalPrice in background
            if not is_open and yf_prices:
                threading.Thread(
                    target=cls._lazy_save_historical,
                    args=(list(yf_prices.keys()),),
                    daemon=True,
                ).start()

        # Fall back to HistoricalPrice for any symbol yfinance could not serve
        missing = [s for s in symbols if s not in result]
        if missing:
            cls._fill_from_historical(missing, result)

        return result

    @classmethod
    def invalidate(cls, symbol: str) -> None:
        """Force a yfinance refresh on the next request for this symbol."""
        from django.core.cache import cache
        cache.delete(f"live_price_{symbol}")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fetch_yfinance_prices(symbols: list) -> dict:
        """Fast per-symbol last-price lookup via fast_info."""
        result = {}
        for symbol in symbols:
            try:
                price = yf.Ticker(symbol).fast_info.last_price
                if price is not None and not math.isnan(float(price)):
                    result[symbol] = float(price)
            except Exception as e:
                logger.warning(f"Live price fetch failed for {symbol}: {e}")
        return result

    @staticmethod
    def _fill_from_historical(symbols: list, result: dict) -> None:
        """Populate result with the most-recent HistoricalPrice close for each symbol."""
        from django.db.models import Max, Q
        latest_dates = (
            HistoricalPrice.objects.filter(stock__symbol__in=symbols)
            .values('stock__symbol')
            .annotate(latest_date=Max('date'))
        )
        date_map = {r['stock__symbol']: r['latest_date'] for r in latest_dates}
        if not date_map:
            return
        q = Q()
        for sym, dt in date_map.items():
            q |= Q(stock__symbol=sym, date=dt)
        for row in HistoricalPrice.objects.filter(q).values('stock__symbol', 'close', 'date'):
            result[row['stock__symbol']] = {
                'price':      float(row['close']),
                'is_live':    False,
                'price_date': row['date'].isoformat(),
            }

    @staticmethod
    def _lazy_save_historical(symbols: list) -> None:
        """Background thread: save today's full OHLC candle to HistoricalPrice if missing."""
        today = date.today()
        fetcher = StockDataFetcher()
        for symbol in symbols:
            try:
                if not HistoricalPrice.objects.filter(stock__symbol=symbol, date=today).exists():
                    fetcher.save_historical_prices(symbol, period='5d')
                    logger.info(f"Lazy-saved historical prices for {symbol}")
            except Exception as e:
                logger.warning(f"Lazy historical save failed for {symbol}: {e}")
