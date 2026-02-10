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
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, update_session_auth_hash
from django.contrib import messages
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import datetime, timedelta
import logging

from .models import Stock, HistoricalPrice, Dividend, StockSplit, UserRegistrationRequest, FinancialMetrics
from .serializers import (
    StockSerializer, StockDetailSerializer, 
    HistoricalPriceSerializer, DividendSerializer, StockSplitSerializer, FinancialMetricsSerializer
)
from .services import StockDataFetcher
from .forms import UserRegistrationForm, AccountSettingsForm, PasswordChangeForm

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
        
        # Try to get from cache first (shorter cache for fresher data)
        cache_key = f'stock_detail_{symbol}'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol}")
            return Response(cached_data)
        
        # Try to get from database
        try:
            stock = Stock.objects.get(symbol=symbol)
            
            # Check data freshness - update if data is more than 1 day old
            latest_price = HistoricalPrice.objects.filter(stock=stock).order_by('-date').first()
            needs_update = False
            
            if not latest_price:
                needs_update = True
                logger.info(f"No price data for {symbol}, fetching...")
            else:
                days_old = (datetime.now().date() - latest_price.date).days
                if days_old > 1:
                    needs_update = True
                    logger.info(f"Data for {symbol} is {days_old} days old, updating...")
            
            # Update data if needed
            if needs_update:
                fetcher = StockDataFetcher()
                # Fetch comprehensive historical data (all available) plus recent updates
                result = fetcher.fetch_and_save_all(symbol, period='max')
                if not result['success']:
                    logger.warning(f"Failed to update data for {symbol}: {result['errors']}")
                    # Continue with existing data if update fails
            
            serializer = StockDetailSerializer(stock)
            data = serializer.data
            
            # Cache for 2 minutes (shorter for fresher data)
            cache.set(cache_key, data, 120)
            
            return Response(data)
        
        except Stock.DoesNotExist:
            # Stock not in database, fetch from yfinance
            logger.info(f"Stock {symbol} not found, fetching all available historical data...")
            
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='max')
            
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
        all_data = request.query_params.get('all', 'false').lower() == 'true'
        
        # Handle "all data" request (Max button)
        if all_data:
            start_date = None
            end_date = datetime.now().date()
        else:
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
        
        if end_date and not all_data:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid end date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif not all_data:
            end_date = datetime.now().date()
        
        # Try cache first
        cache_key = f'stock_prices_{symbol}_{start_date or "all"}_{end_date}'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol} prices")
            return Response(cached_data)
        
        # Get from database
        try:
            stock = Stock.objects.get(symbol=symbol)
            
            # Build query based on parameters
            if all_data or start_date is None:
                prices = HistoricalPrice.objects.filter(
                    stock=stock,
                    date__lte=end_date
                ).order_by('date')
            else:
                prices = HistoricalPrice.objects.filter(
                    stock=stock,
                    date__gte=start_date,
                    date__lte=end_date
                ).order_by('date')
            
            if not prices.exists():
                # No data in database, fetch ALL historical data automatically
                logger.info(f"No price data for {symbol} in requested range, fetching all available historical data...")
                fetcher = StockDataFetcher()
                result = fetcher.fetch_and_save_all(symbol, period='max')
                
                if not result['success']:
                    logger.error(f"Failed to fetch data for {symbol}: {result['errors']}")
                    return Response(
                        {'error': f'Could not fetch historical data for {symbol}'},
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                # Retry query after fetching all data
                if all_data or start_date is None:
                    prices = HistoricalPrice.objects.filter(
                        stock=stock,
                        date__lte=end_date
                    ).order_by('date')
                else:
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
            # Stock not found, automatically fetch all historical data
            logger.info(f"Stock {symbol} not found in StockPriceHistoryView, fetching complete historical dataset...")
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='max')
            
            if not result['success']:
                return Response(
                    {'error': f'Stock {symbol} not found and could not be fetched', 'details': result['errors']},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Now get the data for the requested time range
            stock = Stock.objects.get(symbol=symbol)
            
            if all_data or start_date is None:
                prices = HistoricalPrice.objects.filter(
                    stock=stock,
                    date__lte=end_date
                ).order_by('date')
            else:
                prices = HistoricalPrice.objects.filter(
                    stock=stock,
                    date__gte=start_date,
                    date__lte=end_date
                ).order_by('date')
            
            serializer = HistoricalPriceSerializer(prices, many=True)
            data = {
                'symbol': symbol,
                'start_date': start_date or 'all',
                'end_date': end_date,
                'count': len(serializer.data),
                'prices': serializer.data,
                'just_fetched': True
            }
            
            # Cache for 2 minutes for newly fetched data
            cache.set(cache_key, data, 120)
            
            return Response(data, status=status.HTTP_201_CREATED)


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
            # Stock not found, automatically fetch all historical data including dividends
            logger.info(f"Stock {symbol} not found in StockDividendsView, fetching complete dataset...")
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='max')
            
            if not result['success']:
                return Response(
                    {'error': f'Stock {symbol} not found and could not be fetched', 'details': result['errors']},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Now get the dividends
            stock = Stock.objects.get(symbol=symbol)
            dividends = Dividend.objects.filter(stock=stock).order_by('-date')
            
            serializer = DividendSerializer(dividends, many=True)
            data = {
                'symbol': symbol,
                'count': len(serializer.data),
                'dividends': serializer.data,
                'just_fetched': True
            }
            
            # Cache for 2 minutes for newly fetched data
            cache.set(cache_key, data, 120)
            
            return Response(data, status=status.HTTP_201_CREATED)


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
            # Stock not found, automatically fetch all historical data including splits
            logger.info(f"Stock {symbol} not found in StockSplitsView, fetching complete dataset...")
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='max')
            
            if not result['success']:
                return Response(
                    {'error': f'Stock {symbol} not found and could not be fetched', 'details': result['errors']},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Now get the splits
            stock = Stock.objects.get(symbol=symbol)
            splits = StockSplit.objects.filter(stock=stock).order_by('-date')
            
            serializer = StockSplitSerializer(splits, many=True)
            data = {
                'symbol': symbol,
                'count': len(serializer.data),
                'splits': serializer.data,
                'just_fetched': True
            }
            
            # Cache for 2 minutes for newly fetched data
            cache.set(cache_key, data, 120)
            
            return Response(data, status=status.HTTP_201_CREATED)


class StockFinancialMetricsView(APIView):
    """
    Get financial metrics for a specific stock
    Includes P/E ratios, dividend metrics, growth rates, and Chowder Number
    """
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        symbol = symbol.upper()
        
        # Try cache first
        cache_key = f'stock_metrics_{symbol}'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol} financial metrics")
            return Response(cached_data)
        
        try:
            # Get financial metrics
            metrics = FinancialMetrics.objects.select_related('stock').get(stock__symbol=symbol)
            
            serializer = FinancialMetricsSerializer(metrics)
            data = serializer.data
            
            # Add additional context
            data['stock_name'] = metrics.stock.name
            data['sector'] = metrics.stock.sector
            data['industry'] = metrics.stock.industry
            
            # Cache for 1 hour (metrics don't change as frequently)
            cache.set(cache_key, data, 3600)
            
            return Response(data)
        
        except FinancialMetrics.DoesNotExist:
            # Try to fetch the stock data if it doesn't exist
            try:
                stock = Stock.objects.get(symbol=symbol)
                
                # Fetch financial metrics
                fetcher = StockDataFetcher()
                success = fetcher.save_financial_metrics(symbol)
                
                if success:
                    metrics = FinancialMetrics.objects.select_related('stock').get(stock__symbol=symbol)
                    serializer = FinancialMetricsSerializer(metrics)
                    data = serializer.data
                    data['stock_name'] = metrics.stock.name
                    data['sector'] = metrics.stock.sector
                    data['industry'] = metrics.stock.industry
                    
                    # Cache for 1 hour
                    cache.set(cache_key, data, 3600)
                    
                    return Response(data, status=status.HTTP_201_CREATED)
                else:
                    return Response(
                        {'error': f'Could not fetch financial metrics for {symbol}'},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            except Stock.DoesNotExist:
                # Stock not in database at all
                return Response(
                    {
                        'error': f'Stock {symbol} not found',
                        'message': 'Use the fetch endpoint to add this stock first'
                    },
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

class StockListPageView(LoginRequiredMixin, TemplateView):
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


class StockDetailPageView(LoginRequiredMixin, TemplateView):
    """
    Render the stock detail page with charts
    """
    template_name = 'research/stock_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        symbol = kwargs.get('symbol', '').upper()
        
        try:
            stock = Stock.objects.get(symbol=symbol)
            
            # Check data freshness - similar to API view
            latest_price = HistoricalPrice.objects.filter(stock=stock).order_by('-date').first()
            needs_update = False
            
            if not latest_price:
                needs_update = True
                logger.info(f"No price data for {symbol} (template view), fetching...")
            else:
                days_old = (datetime.now().date() - latest_price.date).days
                if days_old > 1:
                    needs_update = True
                    logger.info(f"Data for {symbol} is {days_old} days old (template view), updating...")
            
            # Update data if needed
            if needs_update:
                fetcher = StockDataFetcher()
                result = fetcher.fetch_and_save_all(symbol, period='max')
                if not result['success']:
                    logger.warning(f"Failed to update data for {symbol} (template view): {result['errors']}")
                    # Continue with existing data if update fails
                else:
                    context['just_updated'] = True
            
            # Check if we have data
            has_prices = HistoricalPrice.objects.filter(stock=stock).exists()
            has_dividends = Dividend.objects.filter(stock=stock).exists()
            has_splits = StockSplit.objects.filter(stock=stock).exists()
            
            # Get financial metrics
            try:
                financial_metrics = FinancialMetrics.objects.get(stock=stock)
                context['financial_metrics'] = financial_metrics
            except FinancialMetrics.DoesNotExist:
                context['financial_metrics'] = None
            
            context['stock'] = stock
            context['has_prices'] = has_prices
            context['has_dividends'] = has_dividends
            context['has_splits'] = has_splits
            
        except Stock.DoesNotExist:
            # Stock not found, try to fetch it with all available historical data
            logger.info(f"Stock {symbol} not found (template view), fetching all historical data...")
            fetcher = StockDataFetcher()
            result = fetcher.fetch_and_save_all(symbol, period='max')
            
            if result['success']:
                stock = Stock.objects.get(symbol=symbol)
                context['stock'] = stock
                context['has_prices'] = True
                context['has_dividends'] = result['dividends_saved'] > 0
                context['has_splits'] = result['splits_saved'] > 0
                context['just_fetched'] = True
                
                # Try to get financial metrics
                try:
                    financial_metrics = FinancialMetrics.objects.get(stock=stock)
                    context['financial_metrics'] = financial_metrics
                except FinancialMetrics.DoesNotExist:
                    context['financial_metrics'] = None
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


# Authentication Views

def user_registration(request):
    """View for user registration (requires approval)"""
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            # Save registration request
            solicitud = form.save()
            
            # Send notification email to administrator
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                import logging
                
                logger = logging.getLogger(__name__)
                
                # Get admin email
                try:
                    admin_user = User.objects.filter(is_superuser=True).first()
                    admin_email = admin_user.email if admin_user and admin_user.email else settings.ADMIN_EMAIL
                except:
                    admin_email = settings.ADMIN_EMAIL
                
                subject = f'[Py-Stocks] New registration request - {solicitud.username}'
                message = f"""
Hello Administrator,

A new registration request has been received for Py-Stocks.

Applicant details:
- Username: {solicitud.username}
- Full name: {solicitud.first_name} {solicitud.last_name}
- Email: {solicitud.email}
- Request date: {solicitud.request_date.strftime('%m/%d/%Y %H:%M')}

To review and approve/reject this request, access the admin panel:
{request.build_absolute_uri('/admin/research/userregistrationrequest/')}

Best regards,
Py-Stocks
                """
                
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin_email],
                    fail_silently=False,
                )
                logger.info(f"Notification email sent to admin {admin_email} for request {solicitud.username}")
                
            except Exception as e:
                # If email sending fails, log error but continue
                logger.error(f"Error sending notification email to admin: {e}")
                print(f"Error sending notification email to admin: {e}")
            
            messages.success(
                request, 
                f'Registration request sent successfully! Your request is pending administrator approval. '
                f'We will contact you at {solicitud.email} when it is processed.'
            )
            return redirect('research:registration_success')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'registration/registro.html', {'form': form})


def registration_success(request):
    """View to show success message after registration"""
    return render(request, 'registration/registro_exitoso.html')


@login_required
def account_panel(request):
    """User account panel for managing account settings"""
    return render(request, 'registration/account_panel.html', {
        'user': request.user
    })


@login_required
def account_settings(request):
    """View for users to manage their account settings"""
    if request.method == 'POST':
        form = AccountSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your account settings have been updated successfully.')
            return redirect('research:account_panel')
    else:
        form = AccountSettingsForm(instance=request.user)
    
    return render(request, 'registration/account_settings.html', {'form': form})


@login_required
def change_password(request):
    """View for users to change their password"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Keep user logged in after password change
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password has been changed successfully.')
            return redirect('research:account_panel')
    else:
        form = PasswordChangeForm(request.user)
    
    return render(request, 'registration/change_password.html', {'form': form})
