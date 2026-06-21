"""
Portfolio calculation services
Handles complex portfolio analytics and calculations
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from django.core.cache import cache
from django.db.models import Max, Min, Sum, Q
from research.models import FinancialMetrics, HistoricalPrice, Stock
from research.services import PriceCacheService

logger = logging.getLogger(__name__)


class PortfolioCalculationService:
    """Service for calculating portfolio metrics and analytics"""
    
    @staticmethod
    def calculate_portfolio_summary(portfolio):
        """
        Calculate comprehensive portfolio summary with all metrics
        
        Returns:
            dict: Portfolio summary with positions and metrics
        """
        positions = portfolio.positions.select_related().all()
        
        # Initialize summary — totals are recomputed after positions are built
        # to ensure they use fresh HistoricalPrice data, not the stale current_price field
        summary = {
            'portfolio_id': portfolio.id,
            'portfolio_name': portfolio.name,
            'summary': {
                'total_invested': 0,
                'current_value': 0,
                'total_gain_loss': 0,
                'total_gain_loss_percentage': 0,
                'dividend_income_ytd': float(portfolio.total_dividend_income),
                'annual_dividend_income': 0,
                'average_yield_on_cost': 0,
            },
            'positions': [],
            'metrics': {
                'positions_count': positions.count(),
                'dividend_stocks_count': 0,
            }
        }
        
        symbols = [p.symbol for p in positions]
        today  = date.today().isoformat()

        # 52W high/low — keyed by portfolio + date; refreshed once per day
        range_cache_key = f"price_range_{portfolio.id}_{today}"
        price_range_map = cache.get(range_cache_key)
        if price_range_map is None:
            one_year_ago = date.today() - timedelta(days=365)
            price_ranges = HistoricalPrice.objects.filter(
                stock__symbol__in=symbols,
                date__gte=one_year_ago,
            ).values('stock__symbol').annotate(high_52w=Max('high'), low_52w=Min('low'))
            price_range_map = {r['stock__symbol']: r for r in price_ranges}
            cache.set(range_cache_key, price_range_map, timeout=8 * 3600)

        # Live prices — per-symbol cache shared across all views (15 min during market hours)
        price_data_map = PriceCacheService.get_prices(symbols) if symbols else {}

        # Build positions with fresh prices
        weighted_yoc_sum = 0
        weighted_yoc_cost = 0

        for position in positions:
            position_data = PortfolioCalculationService.get_position_detail(position, price_range_map, price_data_map)
            summary['positions'].append(position_data)

        # Recompute all summary totals from fresh position data (no stale current_price)
        total_invested = sum(p['total_invested'] for p in summary['positions'])
        current_value  = sum(p['current_value']  for p in summary['positions'])
        gain_loss      = current_value - total_invested
        gain_loss_pct  = (gain_loss / total_invested * 100) if total_invested > 0 else 0
        annual_div     = sum(p['annual_dividend_income'] or 0 for p in summary['positions'])
        div_count      = sum(1 for p in summary['positions'] if p.get('pays_dividend'))

        for p in summary['positions']:
            if p.get('yield_on_cost') and p['total_invested'] > 0:
                weighted_yoc_cost += p['total_invested']
                weighted_yoc_sum  += p['total_invested'] * p['yield_on_cost']

        summary['summary']['total_invested']           = round(total_invested, 2)
        summary['summary']['current_value']            = round(current_value, 2)
        summary['summary']['total_gain_loss']          = round(gain_loss, 2)
        summary['summary']['total_gain_loss_percentage'] = round(gain_loss_pct, 2)
        summary['summary']['annual_dividend_income']   = round(annual_div, 2)
        summary['summary']['average_yield_on_cost']    = round(weighted_yoc_sum / weighted_yoc_cost, 2) if weighted_yoc_cost > 0 else 0
        summary['metrics']['dividend_stocks_count']    = div_count

        # Price footnote — shown below positions table when market is closed
        stale_dates = [
            p['price_date'] for p in summary['positions']
            if not p.get('price_is_live') and p.get('price_date')
        ]
        summary['price_as_of'] = min(stale_dates) if stale_dates else None

        return summary
    
    @staticmethod
    def get_position_detail(position, price_range_map=None, price_data_map=None):
        """
        Get detailed information for a single position.

        Args:
            position: Position instance
            price_range_map: optional {symbol: {high_52w, low_52w}} pre-computed by caller
            price_data_map: optional {symbol: {'price', 'is_live', 'price_date'}} from PriceCacheService
        """
        metrics = position.get_current_metrics()

        try:
            stock = Stock.objects.get(symbol=position.symbol)
            company_name = stock.name
        except Stock.DoesNotExist:
            company_name = position.symbol

        pr = (price_range_map or {}).get(position.symbol, {})

        # Resolve current price — fetch from live cache when not pre-supplied
        price_entry = (price_data_map or {}).get(position.symbol)
        if price_entry is None:
            fetched = PriceCacheService.get_prices([position.symbol])
            price_entry = fetched.get(position.symbol)

        if price_entry:
            display_price = price_entry['price']
            price_is_live = price_entry['is_live']
            price_date    = price_entry['price_date']
        else:
            # Last-resort fallback: stale DB fields
            display_price = float(position.current_price) if position.current_price else float(position.average_cost)
            price_is_live = False
            price_date    = None

        qty = float(position.quantity)
        total_cost = float(position.total_cost)
        current_value = display_price * qty
        gain_loss = current_value - total_cost
        gain_loss_pct = (gain_loss / total_cost * 100) if total_cost > 0 else 0

        position_data = {
            'symbol': position.symbol,
            'company_name': company_name,
            'quantity': qty,
            'average_cost': float(position.average_cost),
            'current_price': display_price,
            'price_is_live': price_is_live,
            'price_date': price_date,
            'total_invested': total_cost,
            'current_value': current_value,
            'gain_loss': gain_loss,
            'gain_loss_percentage': gain_loss_pct,
            'buy_yield': position.average_buy_yield,
            'current_yield': None,
            'yield_on_cost': position.yield_on_cost,
            'annual_dividend_income': position.annual_dividend_income,
            'pays_dividend': False,
            # Fundamentals
            'trailing_pe': None,
            'forward_pe': None,
            'payout_ratio': None,
            'fcf_payout_ratio': None,
            'dividend_growth_1y': None,
            'dividend_growth_5y': None,
            'chowder_number': None,
            'beta': None,
            'high_52w': float(pr['high_52w']) if pr.get('high_52w') else None,
            'low_52w': float(pr['low_52w']) if pr.get('low_52w') else None,
        }

        if metrics:
            position_data['pays_dividend'] = metrics.pays_dividend
            position_data['current_yield'] = float(metrics.dividend_yield) if metrics.dividend_yield else None
            position_data['trailing_pe'] = float(metrics.trailing_pe) if metrics.trailing_pe else None
            position_data['forward_pe'] = float(metrics.forward_pe) if metrics.forward_pe else None
            position_data['payout_ratio'] = float(metrics.payout_ratio) if metrics.payout_ratio else None
            position_data['fcf_payout_ratio'] = float(metrics.fcf_payout_ratio) if metrics.fcf_payout_ratio else None
            position_data['dividend_growth_1y'] = float(metrics.dividend_growth_1y) if metrics.dividend_growth_1y else None
            position_data['dividend_growth_5y'] = float(metrics.dividend_growth_5y) if metrics.dividend_growth_5y else None
            position_data['chowder_number'] = float(metrics.chowder_number) if metrics.chowder_number else None
            position_data['beta'] = float(metrics.beta) if metrics.beta else None

        return position_data
    
    @staticmethod
    def calculate_broker_summary(portfolio):
        """
        Calculate portfolio breakdown by broker
        
        Returns:
            list: Summary of holdings by broker
        """
        from django.db.models import Sum, F, Q
        from decimal import Decimal
        
        # Get all transactions with broker information
        transactions = portfolio.transactions.filter(
            broker__isnull=False
        ).exclude(broker='')
        
        brokers = {}
        
        for transaction in transactions:
            broker = transaction.broker
            if broker not in brokers:
                brokers[broker] = {
                    'broker': broker,
                    'total_invested': 0,
                    'transactions_count': 0,
                }
            
            if transaction.transaction_type == 'BUY':
                brokers[broker]['total_invested'] += float(transaction.total_amount)
            else:
                brokers[broker]['total_invested'] -= float(transaction.total_amount)
            
            brokers[broker]['transactions_count'] += 1
        
        return list(brokers.values())
    
    @staticmethod
    def update_position_from_transaction(transaction):
        """
        Update or create position based on a transaction
        
        Args:
            transaction: Transaction instance
        """
        from portfolio.models import Position
        
        # Get or create position
        position, created = Position.objects.get_or_create(
            portfolio=transaction.portfolio,
            symbol=transaction.symbol,
            defaults={
                'quantity': Decimal('0'),
                'average_cost': Decimal('0'),
            }
        )
        
        if transaction.transaction_type == 'BUY':
            # Calculate new average cost
            old_total_cost = position.quantity * position.average_cost
            transaction_cost = transaction.quantity * transaction.price
            new_quantity = position.quantity + transaction.quantity
            
            if new_quantity > 0:
                new_average_cost = (old_total_cost + transaction_cost) / new_quantity
                position.average_cost = new_average_cost
            
            position.quantity = new_quantity
            
        elif transaction.transaction_type == 'SELL':
            # Reduce quantity (average cost stays the same)
            position.quantity -= transaction.quantity
            
            # If position is fully closed, you might want to delete it
            if position.quantity <= 0:
                position.delete()
                return None
        
        position.save()
        return position
    
    @staticmethod
    def fetch_and_store_buy_yield(transaction):
        """
        Fetch current dividend yield and store as buy_yield for a BUY transaction
        
        Args:
            transaction: Transaction instance
            
        Returns:
            bool: True if yield was stored, False otherwise
        """
        if transaction.transaction_type != 'BUY':
            return False
        
        try:
            metrics = FinancialMetrics.objects.get(stock__symbol=transaction.symbol)
            if metrics.pays_dividend and metrics.dividend_yield:
                transaction.buy_yield = metrics.dividend_yield
                transaction.save(update_fields=['buy_yield'])
                return True
        except FinancialMetrics.DoesNotExist:
            pass
        
        return False
    
    @staticmethod
    def calculate_dividend_income_history(portfolio, year=None):
        """
        Calculate dividend income history for a portfolio.

        Uses payment_date when available, falls back to ex_dividend_date for
        auto-recorded entries where payment_date is null.
        """
        from datetime import datetime
        from django.db.models import Sum
        from django.db.models.functions import Coalesce, TruncMonth

        # Annotate effective date: payment_date if known, else ex_dividend_date
        dividends = portfolio.dividends.annotate(
            effective_date=Coalesce('payment_date', 'ex_dividend_date')
        )

        if year:
            dividends = dividends.filter(effective_date__year=year)

        monthly_data = (
            dividends
            .annotate(month=TruncMonth('effective_date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        return {
            'year': year or datetime.now().year,
            'monthly_income': [
                {
                    'month': item['month'].strftime('%Y-%m'),
                    'total': float(item['total'])
                }
                for item in monthly_data
            ],
            'total': float(sum(item['total'] for item in monthly_data)),
        }
    
    @staticmethod
    def ensure_stock_exists(symbol: str) -> tuple[bool, str, object]:
        """
        Ensure stock exists in database, auto-fetch if not found
        Handles symbol redirects (e.g., FB → META) and exchange disambiguation
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            tuple: (success: bool, message: str, stock: Stock or None)
        """
        from research.models import Stock
        from research.services import StockDataFetcher
        import logging

        logger = logging.getLogger(__name__)
        original_symbol = symbol.upper()
        symbol = original_symbol

        # Check if stock already exists
        try:
            stock = Stock.objects.get(symbol=symbol)
            return (True, f"Stock {symbol} found in database", stock)
        except Stock.DoesNotExist:
            pass

        # Stock doesn't exist, try to fetch it
        logger.info(f"Stock {symbol} not found in database, attempting auto-fetch with full data...")
        
        try:
            fetcher = StockDataFetcher()
            # Fetch all data: stock info, historical prices, dividends, splits, financial metrics
            result = fetcher.fetch_and_save_all(symbol, period='1y')
            
            if result['success'] and result['stock_saved']:
                stock = Stock.objects.get(symbol=symbol)
                logger.info(
                    f"Successfully auto-fetched stock: {symbol} "
                    f"({result['prices_created']} prices, "
                    f"{result['dividends_saved']} dividends, "
                    f"metrics: {'✓' if result['financial_metrics_saved'] else '✗'})"
                )
                
                return (True, f"Stock {symbol} added to database", stock)
            else:
                error_msg = f"Stock symbol '{original_symbol}' not found."

                if result.get('errors'):
                    error_msg += f" Errors: {', '.join(result['errors'])}"
                else:
                    error_msg += " Please verify the symbol is correct."
                    
                logger.warning(f"Failed to fetch stock {symbol} - symbol not found")
                return (False, error_msg, None)
                
        except Exception as e:
            error_msg = f"Error fetching stock '{symbol}': {str(e)}"
            logger.error(f"Error auto-fetching stock {symbol}: {str(e)}")
            return (False, error_msg, None)

    @staticmethod
    def _shares_held_on_date(portfolio, symbol, as_of_date):
        """
        Reconstruct shares held for a symbol at close of a given date
        by replaying BUY/SELL/SPOF transactions up to and including that date.
        """
        from .models import Transaction
        txs = Transaction.objects.filter(
            portfolio=portfolio,
            symbol=symbol,
            transaction_type__in=['BUY', 'SELL', 'SPOF'],
            transaction_date__date__lte=as_of_date,
        ).order_by('transaction_date')

        shares = Decimal('0')
        for tx in txs:
            if tx.transaction_type in ('BUY', 'SPOF'):
                shares += tx.quantity
            else:
                shares -= tx.quantity
        return max(shares, Decimal('0'))

    @staticmethod
    def auto_record_dividends(portfolio):
        """
        Refresh research.Dividend data from yfinance for every position, then
        create portfolio.Dividend records for dividends the user qualified for
        (held shares at close of the day before the ex-dividend date).

        Returns a dict with counts of new records created and skipped duplicates.
        Idempotent — safe to call multiple times.
        """
        from research.models import Dividend as ResearchDividend
        from research.services import StockDataFetcher
        from .models import Dividend as PortfolioDividend

        symbols = list(portfolio.positions.values_list('symbol', flat=True))
        if not symbols:
            return {'created': 0, 'skipped': 0}

        # Step 1 — pull fresh dividend history from yfinance so we never miss
        # a recent ex-dividend that wasn't present when the stock was first added.
        # Cache flag prevents redundant yfinance calls within the same calendar day.
        # Symbols that need fetching are dispatched in parallel (max 5 workers).
        from concurrent.futures import ThreadPoolExecutor, as_completed

        fetcher = StockDataFetcher()
        today_str = date.today().isoformat()

        stale = [s for s in symbols if not cache.get(f"dividend_refreshed_{s}_{today_str}")]
        fresh = [s for s in symbols if s not in stale]
        if fresh:
            logger.debug(f"Skipping yfinance refresh for {fresh} (already refreshed today)")

        refresh_errors = []

        def _refresh(symbol):
            fetcher.save_dividends(symbol)
            return symbol

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_refresh, s): s for s in stale}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    future.result()
                    cache.set(f"dividend_refreshed_{symbol}_{today_str}", True, timeout=20 * 3600)
                except Exception as e:
                    logger.warning(f"Could not refresh dividends for {symbol}: {e}")
                    refresh_errors.append(symbol)

        # Step 2 — re-query research dividends (now up to date)
        research_divs = (
            ResearchDividend.objects
            .filter(stock__symbol__in=symbols)
            .select_related('stock')
            .order_by('stock__symbol', 'date')
        )

        # Existing portfolio dividend records keyed by (symbol, ex_date) for dedup
        existing = set(
            PortfolioDividend.objects.filter(portfolio=portfolio)
            .exclude(ex_dividend_date=None)
            .values_list('symbol', 'ex_dividend_date')
        )

        created = 0
        skipped = 0

        for div in research_divs:
            symbol     = div.stock.symbol
            ex_date    = div.date          # research.Dividend.date is the ex-date
            check_date = ex_date - timedelta(days=1)

            if (symbol, ex_date) in existing:
                skipped += 1
                continue

            shares = PortfolioCalculationService._shares_held_on_date(
                portfolio, symbol, check_date
            )
            if shares <= 0:
                continue

            # Use the research-side payment_date when available so the portfolio
            # entry sorts and displays correctly.
            payment_date = getattr(div, 'payment_date', None)

            total_amount = (div.amount * shares).quantize(Decimal('0.01'))

            PortfolioDividend.objects.create(
                portfolio=portfolio,
                symbol=symbol,
                amount=total_amount,
                quantity=shares,
                payment_date=payment_date,
                ex_dividend_date=ex_date,
                notes='Auto-recorded',
            )
            existing.add((symbol, ex_date))
            created += 1

        result = {'created': created, 'skipped': skipped}
        if refresh_errors:
            result['refresh_errors'] = refresh_errors
        return result
