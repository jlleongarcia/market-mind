"""
Research API Views
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.core.cache import cache
from django.db.models import Q
from django.views.generic import TemplateView
from datetime import datetime, timedelta
import logging

from .models import Stock, HistoricalPrice, Dividend, StockSplit
from .serializers import (
    StockSerializer, StockDetailSerializer, 
    HistoricalPriceSerializer, DividendSerializer, StockSplitSerializer
)
from .services import StockDataFetcher

logger = logging.getLogger(__name__)


class StockListView(generics.ListAPIView):
    """
    List all stocks in database with optional search/filter
    """
    permission_classes = [AllowAny]
    serializer_class = StockSerializer
    
    def get_queryset(self):
        queryset = Stock.objects.filter(is_active=True)
        
        # Search by symbol or name
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(symbol__icontains=search) | 
                Q(name__icontains=search)
            )
        
        # Filter by sector
        sector = self.request.query_params.get('sector', None)
        if sector:
            queryset = queryset.filter(sector__iexact=sector)
        
        # Filter by industry
        industry = self.request.query_params.get('industry', None)
        if industry:
            queryset = queryset.filter(industry__iexact=industry)
        
        return queryset.order_by('symbol')


class StockDetailView(APIView):
    """
    Get detailed information about a specific stock
    Fetches from database, or triggers data fetch if not found
    """
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        symbol = symbol.upper()
        
        # Try to get from cache first
        cache_key = f'stock_detail_{symbol}'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol}")
            return Response(cached_data)
        
        # Try to get from database
        try:
            stock = Stock.objects.get(symbol=symbol)
            serializer = StockDetailSerializer(stock)
            data = serializer.data
            
            # Cache for 5 minutes
            cache.set(cache_key, data, 300)
            
            return Response(data)
        
        except Stock.DoesNotExist:
            # Stock not in database, fetch from yfinance
            logger.info(f"Stock {symbol} not found, fetching from yfinance")
            
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='1y')
            
            if not result['success']:
                return Response(
                    {'error': f'Could not fetch data for {symbol}', 'details': result['errors']},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Return newly fetched data
            stock = Stock.objects.get(symbol=symbol)
            serializer = StockDetailSerializer(stock)
            data = serializer.data
            
            # Cache for 5 minutes
            cache.set(cache_key, data, 300)
            
            return Response(data, status=status.HTTP_201_CREATED)


class StockPriceHistoryView(APIView):
    """
    Get historical price data for a stock
    """
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        symbol = symbol.upper()
        
        # Get query parameters
        start_date = request.query_params.get('start')
        end_date = request.query_params.get('end')
        days = request.query_params.get('days', '365')
        
        # Parse dates
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid start date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Default to last N days
            try:
                days_int = int(days)
                start_date = (datetime.now() - timedelta(days=days_int)).date()
            except ValueError:
                return Response(
                    {'error': 'Invalid days parameter'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid end date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            end_date = datetime.now().date()
        
        # Try cache first
        cache_key = f'stock_prices_{symbol}_{start_date}_{end_date}'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol} prices")
            return Response(cached_data)
        
        # Get from database
        try:
            stock = Stock.objects.get(symbol=symbol)
            prices = HistoricalPrice.objects.filter(
                stock=stock,
                date__gte=start_date,
                date__lte=end_date
            ).order_by('date')
            
            if not prices.exists():
                # No data in database, fetch from yfinance
                logger.info(f"No price data for {symbol}, fetching from yfinance")
                fetcher = StockDataFetcher()
                fetcher.save_historical_prices(symbol, start_date=start_date, end_date=end_date)
                
                # Retry query
                prices = HistoricalPrice.objects.filter(
                    stock=stock,
                    date__gte=start_date,
                    date__lte=end_date
                ).order_by('date')
            
            serializer = HistoricalPriceSerializer(prices, many=True)
            data = {
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date,
                'count': len(serializer.data),
                'prices': serializer.data
            }
            
            # Cache for 24 hours if historical, 5 minutes if recent
            days_old = (datetime.now().date() - end_date).days
            cache_timeout = 86400 if days_old > 7 else 300
            cache.set(cache_key, data, cache_timeout)
            
            return Response(data)
        
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock {symbol} not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class StockDividendsView(APIView):
    """
    Get dividend history for a stock
    """
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        symbol = symbol.upper()
        
        # Try cache
        cache_key = f'stock_dividends_{symbol}'
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)
        
        try:
            stock = Stock.objects.get(symbol=symbol)
            dividends = Dividend.objects.filter(stock=stock).order_by('-date')
            
            if not dividends.exists():
                # Try to fetch from yfinance
                fetcher = StockDataFetcher()
                count = fetcher.save_dividends(symbol)
                
                if count > 0:
                    dividends = Dividend.objects.filter(stock=stock).order_by('-date')
            
            serializer = DividendSerializer(dividends, many=True)
            data = {
                'symbol': symbol,
                'count': len(serializer.data),
                'dividends': serializer.data
            }
            
            # Cache for 24 hours
            cache.set(cache_key, data, 86400)
            
            return Response(data)
        
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock {symbol} not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class StockSplitsView(APIView):
    """
    Get stock split history
    """
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        symbol = symbol.upper()
        
        # Try cache
        cache_key = f'stock_splits_{symbol}'
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)
        
        try:
            stock = Stock.objects.get(symbol=symbol)
            splits = StockSplit.objects.filter(stock=stock).order_by('-date')
            
            if not splits.exists():
                # Try to fetch from yfinance
                fetcher = StockDataFetcher()
                count = fetcher.save_splits(symbol)
                
                if count > 0:
                    splits = StockSplit.objects.filter(stock=stock).order_by('-date')
            
            serializer = StockSplitSerializer(splits, many=True)
            data = {
                'symbol': symbol,
                'count': len(serializer.data),
                'splits': serializer.data
            }
            
            # Cache for 1 week
            cache.set(cache_key, data, 604800)
            
            return Response(data)
        
        except Stock.DoesNotExist:
            return Response(
                {'error': f'Stock {symbol} not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class FetchStockDataView(APIView):
    """
    Admin endpoint to manually trigger data fetch for a stock
    """
    permission_classes = [AllowAny]  # Changed to AllowAny for frontend modal
    
    def post(self, request):
        symbol = request.data.get('symbol')
        period = request.data.get('period', '1y')
        
        if not symbol:
            return Response(
                {'error': 'Symbol is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        fetcher = StockDataFetcher()
        result = fetcher.fetch_and_save_all(symbol.upper(), period=period)
        
        if result['success']:
            return Response(result, status=status.HTTP_201_CREATED)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)


# ============================================
# Template-Based Views for Frontend
# ============================================

class StockListPageView(TemplateView):
    """
    Render the stock list/search page
    """
    template_name = 'research/stock_list.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get search query
        search_query = self.request.GET.get('search', '')
        sector_filter = self.request.GET.get('sector', '')
        
        # Get stocks
        stocks = Stock.objects.filter(is_active=True)
        
        if search_query:
            stocks = stocks.filter(
                Q(symbol__icontains=search_query) | 
                Q(name__icontains=search_query)
            )
        
        if sector_filter:
            stocks = stocks.filter(sector__iexact=sector_filter)
        
        stocks = stocks.order_by('symbol')
        
        # Get unique sectors for filter
        sectors = Stock.objects.filter(
            is_active=True, 
            sector__isnull=False
        ).values_list('sector', flat=True).distinct().order_by('sector')
        
        context['stocks'] = stocks
        context['search_query'] = search_query
        context['sector_filter'] = sector_filter
        context['sectors'] = list(sectors)
        
        return context


class StockDetailPageView(TemplateView):
    """
    Render the stock detail page with charts
    """
    template_name = 'research/stock_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        symbol = kwargs.get('symbol', '').upper()
        
        try:
            stock = Stock.objects.get(symbol=symbol)
            
            # Check if we have data
            has_prices = HistoricalPrice.objects.filter(stock=stock).exists()
            has_dividends = Dividend.objects.filter(stock=stock).exists()
            has_splits = StockSplit.objects.filter(stock=stock).exists()
            
            context['stock'] = stock
            context['has_prices'] = has_prices
            context['has_dividends'] = has_dividends
            context['has_splits'] = has_splits
            
        except Stock.DoesNotExist:
            # Stock not found, try to fetch it
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='1y')
            
            if result['success']:
                stock = Stock.objects.get(symbol=symbol)
                context['stock'] = stock
                context['has_prices'] = True
                context['has_dividends'] = result['dividends_saved'] > 0
                context['has_splits'] = result['splits_saved'] > 0
                context['just_fetched'] = True
            else:
                # Handle stock not found
                from django.http import Http404
                raise Http404(f"Stock {symbol} not found and could not be fetched")
        
        return context


class StockHistoryView(APIView):
    """Get historical stock data (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        period = request.query_params.get('period', '1mo')  # 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max
        
        try:
            stock = yf.Ticker(symbol.upper())
            hist = stock.history(period=period)
            
            data = []
            for date, row in hist.iterrows():
                data.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'open': round(row['Open'], 2),
                    'high': round(row['High'], 2),
                    'low': round(row['Low'], 2),
                    'close': round(row['Close'], 2),
                    'volume': int(row['Volume'])
                })
            
            return Response({
                'symbol': symbol.upper(),
                'period': period,
                'data': data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StockMetricsView(APIView):
    """Get financial metrics for a stock (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        try:
            stock = yf.Ticker(symbol.upper())
            info = stock.info
            
            return Response({
                'symbol': symbol.upper(),
                'metrics': {
                    'market_cap': info.get('marketCap'),
                    'pe_ratio': info.get('trailingPE'),
                    'forward_pe': info.get('forwardPE'),
                    'peg_ratio': info.get('pegRatio'),
                    'price_to_book': info.get('priceToBook'),
                    'dividend_yield': info.get('dividendYield'),
                    'profit_margin': info.get('profitMargins'),
                    'operating_margin': info.get('operatingMargins'),
                    'return_on_assets': info.get('returnOnAssets'),
                    'return_on_equity': info.get('returnOnEquity'),
                    'revenue': info.get('totalRevenue'),
                    'revenue_per_share': info.get('revenuePerShare'),
                    'earnings_growth': info.get('earningsGrowth'),
                    'revenue_growth': info.get('revenueGrowth'),
                    'beta': info.get('beta'),
                }
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
