"""
Portfolio calculation services
Handles complex portfolio analytics and calculations
"""
from decimal import Decimal
from django.db.models import Sum, Q
from research.models import FinancialMetrics, Stock


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
        
        # Initialize summary data
        summary = {
            'portfolio_id': portfolio.id,
            'portfolio_name': portfolio.name,
            'summary': {
                'total_invested': float(portfolio.total_invested),
                'current_value': float(portfolio.total_value),
                'total_gain_loss': float(portfolio.total_return),
                'total_gain_loss_percentage': float(portfolio.total_return_percentage),
                'dividend_income_ytd': float(portfolio.total_dividend_income),
                'annual_dividend_income': float(portfolio.annual_dividend_income),
                'average_yield_on_cost': 0,
            },
            'positions': [],
            'metrics': {
                'positions_count': positions.count(),
                'dividend_stocks_count': portfolio.dividend_positions_count,
                'non_dividend_stocks_count': positions.count() - portfolio.dividend_positions_count,
                'weighted_dividend_yield': float(portfolio.weighted_dividend_yield),
            }
        }
        
        # Calculate average YoC and build position details
        total_cost = 0
        weighted_yoc_sum = 0
        
        for position in positions:
            position_data = PortfolioCalculationService.get_position_detail(position)
            summary['positions'].append(position_data)
            
            # Calculate weighted YoC
            if position_data.get('yield_on_cost'):
                position_cost = float(position.total_cost)
                total_cost += position_cost
                weighted_yoc_sum += position_cost * position_data['yield_on_cost']
        
        # Calculate average YoC
        if total_cost > 0:
            summary['summary']['average_yield_on_cost'] = round(weighted_yoc_sum / total_cost, 2)
        
        return summary
    
    @staticmethod
    def get_position_detail(position):
        """
        Get detailed information for a single position
        
        Args:
            position: Position instance
            
        Returns:
            dict: Position details with metrics
        """
        metrics = position.get_current_metrics()
        
        # Get stock info
        try:
            stock = Stock.objects.get(symbol=position.symbol)
            company_name = stock.name
        except Stock.DoesNotExist:
            company_name = position.symbol
        
        position_data = {
            'symbol': position.symbol,
            'company_name': company_name,
            'quantity': float(position.quantity),
            'average_cost': float(position.average_cost),
            'current_price': float(position.current_price) if position.current_price else float(position.average_cost),
            'total_invested': float(position.total_cost),
            'current_value': float(position.current_value),
            'gain_loss': float(position.profit_loss),
            'gain_loss_percentage': float(position.profit_loss_percentage),
            'buy_yield': position.average_buy_yield,
            'current_yield': None,
            'yield_on_cost': position.yield_on_cost,
            'annual_dividend_income': position.annual_dividend_income,
            'pays_dividend': False,
        }
        
        # Add financial metrics if available
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
        Calculate dividend income history for a portfolio
        
        Args:
            portfolio: Portfolio instance
            year: Optional year to filter (default: current year)
            
        Returns:
            dict: Dividend income history by month
        """
        from datetime import datetime
        from django.db.models import Sum
        from django.db.models.functions import TruncMonth
        
        dividends = portfolio.dividends.all()
        
        if year:
            dividends = dividends.filter(payment_date__year=year)
        
        # Group by month
        monthly_data = dividends.annotate(
            month=TruncMonth('payment_date')
        ).values('month').annotate(
            total=Sum('amount')
        ).order_by('month')
        
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
        from research.models import Stock, SymbolRedirect
        from research.services import StockDataFetcher
        import logging
        
        logger = logging.getLogger(__name__)
        original_symbol = symbol.upper()
        symbol = original_symbol
        redirect_used = None
        
        # Check if stock already exists
        try:
            stock = Stock.objects.get(symbol=symbol)
            return (True, f"Stock {symbol} found in database", stock)
        except Stock.DoesNotExist:
            pass
        
        # Check for symbol redirects (e.g., FB → META, ticker changes)
        try:
            redirect = SymbolRedirect.objects.get(old_symbol=symbol, is_active=True)
            logger.info(f"Found redirect: {symbol} → {redirect.new_symbol} ({redirect.reason})")
            symbol = redirect.new_symbol
            redirect_used = redirect
            
            # Check if redirected symbol exists
            try:
                stock = Stock.objects.get(symbol=symbol)
                message = f"Symbol {original_symbol} has changed to {symbol}"
                if redirect.reason:
                    message += f" ({redirect.reason})"
                return (True, message, stock)
            except Stock.DoesNotExist:
                pass
                
        except SymbolRedirect.DoesNotExist:
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
                
                # Build message
                if redirect_used:
                    message = f"Stock {original_symbol} redirected to {symbol}"
                    if redirect_used.reason:
                        message += f" ({redirect_used.reason})"
                    message += " and added to database"
                else:
                    message = f"Stock {symbol} added to database"
                    
                return (True, message, stock)
            else:
                # Stock not found - check if it's because symbol is invalid
                error_msg = f"Stock symbol '{original_symbol}' not found."
                
                if redirect_used:
                    error_msg = f"Symbol {original_symbol} redirects to {symbol}, but {symbol} was not found."
                
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
