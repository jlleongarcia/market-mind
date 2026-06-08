"""
Portfolio API Views
Comprehensive views for portfolio management with financial metrics integration
"""
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from datetime import datetime

from .models import Portfolio, Transaction, Position, Dividend
from .serializers import (
    PortfolioSerializer, PortfolioSummarySerializer, TransactionSerializer,
    PositionSerializer, PositionDetailSerializer, DividendSerializer,
    BrokerSummarySerializer, DividendIncomeHistorySerializer
)
from .services import PortfolioCalculationService


class PortfolioListCreateView(APIView):
    """List and create portfolios"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all portfolios for authenticated user"""
        portfolios = Portfolio.objects.filter(user=request.user)
        serializer = PortfolioSerializer(portfolios, many=True)
        return Response({
            'count': portfolios.count(),
            'portfolios': serializer.data
        })
    
    def post(self, request):
        """Create new portfolio"""
        serializer = PortfolioSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PortfolioDetailView(APIView):
    """Get, update, delete portfolio"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get portfolio details"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        serializer = PortfolioSerializer(portfolio)
        return Response(serializer.data)
    
    def put(self, request, pk):
        """Update portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        serializer = PortfolioSerializer(portfolio, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """Delete portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        portfolio.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PortfolioSummaryView(APIView):
    """Get comprehensive portfolio summary with all metrics"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get portfolio summary including positions and calculated metrics"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        summary = PortfolioCalculationService.calculate_portfolio_summary(portfolio)
        serializer = PortfolioSummarySerializer(summary)
        return Response(serializer.data)


class PortfolioPositionsView(APIView):
    """Get portfolio positions"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get all positions for a portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        positions = portfolio.positions.all()
        serializer = PositionSerializer(positions, many=True)
        return Response({
            'count': positions.count(),
            'positions': serializer.data
        })


class PositionDetailView(APIView):
    """Get detailed position information with metrics"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, portfolio_id, symbol):
        """Get position details including financial metrics"""
        portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
        position = get_object_or_404(Position, portfolio=portfolio, symbol=symbol.upper())
        
        # Get detailed position data with metrics
        position_data = PortfolioCalculationService.get_position_detail(position)
        
        # Get transaction history for this position
        transactions = position.get_transactions()
        transaction_serializer = TransactionSerializer(transactions, many=True)
        
        # Combine data
        response_data = {
            'position': position_data,
            'transactions': transaction_serializer.data,
            'transactions_count': transactions.count()
        }
        
        return Response(response_data)


class PortfolioTransactionsView(APIView):
    """Get and create portfolio transactions"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get all transactions for a portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        transactions = portfolio.transactions.all()
        serializer = TransactionSerializer(transactions, many=True)
        return Response({
            'count': transactions.count(),
            'transactions': serializer.data
        })
    
    def post(self, request, pk):
        """Create new transaction for a portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        
        # Validate and ensure stock exists
        symbol = request.data.get('symbol', '').strip().upper()
        if not symbol:
            return Response(
                {'error': 'Stock symbol is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        success, message, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
        if not success:
            return Response(
                {'error': message, 'symbol': symbol},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add portfolio to request data
        data = request.data.copy()
        data['portfolio'] = portfolio.id
        data['symbol'] = symbol  # Use validated uppercase symbol
        
        serializer = TransactionSerializer(data=data)
        if serializer.is_valid():
            transaction = serializer.save()
            
            # Update position based on transaction
            PortfolioCalculationService.update_position_from_transaction(transaction)
            
            # Fetch and store buy yield if applicable
            if transaction.transaction_type == 'BUY':
                PortfolioCalculationService.fetch_and_store_buy_yield(transaction)
            
            # Include redirect URL in response
            response_data = serializer.data
            response_data['redirect_url'] = f'/portfolio/{portfolio.id}/'
            response_data['portfolio_id'] = portfolio.id
            
            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TransactionCreateView(APIView):
    """Create transaction (legacy endpoint)"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Create transaction"""
        # Verify user owns the portfolio
        portfolio_id = request.data.get('portfolio')
        portfolio = None
        if portfolio_id:
            portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
        
        # Validate and ensure stock exists
        symbol = request.data.get('symbol', '').strip().upper()
        if not symbol:
            return Response(
                {'error': 'Stock symbol is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        success, message, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
        if not success:
            return Response(
                {'error': message, 'symbol': symbol},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update request data with validated symbol
        data = request.data.copy()
        data['symbol'] = symbol
        
        serializer = TransactionSerializer(data=data)
        if serializer.is_valid():
            transaction = serializer.save()
            
            # Update position based on transaction
            PortfolioCalculationService.update_position_from_transaction(transaction)
            
            # Fetch and store buy yield if applicable
            if transaction.transaction_type == 'BUY':
                PortfolioCalculationService.fetch_and_store_buy_yield(transaction)
            
            # Include redirect URL in response if portfolio is known
            response_data = serializer.data
            if portfolio:
                response_data['redirect_url'] = f'/portfolio/{portfolio.id}/'
                response_data['portfolio_id'] = portfolio.id
            
            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DividendListView(APIView):
    """List and create dividends"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all dividends for user's portfolios"""
        portfolios = Portfolio.objects.filter(user=request.user)
        dividends = Dividend.objects.filter(portfolio__in=portfolios)
        
        # Filter by portfolio if specified
        portfolio_id = request.query_params.get('portfolio')
        if portfolio_id:
            dividends = dividends.filter(portfolio_id=portfolio_id)
        
        # Filter by year if specified
        year = request.query_params.get('year')
        if year:
            dividends = dividends.filter(payment_date__year=year)
        
        serializer = DividendSerializer(dividends, many=True)
        return Response({
            'count': dividends.count(),
            'dividends': serializer.data
        })
    
    def post(self, request):
        """Create new dividend record"""
        # Verify user owns the portfolio
        portfolio_id = request.data.get('portfolio')
        if portfolio_id:
            get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
        
        serializer = DividendSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DividendIncomeHistoryView(APIView):
    """Get dividend income history for a portfolio"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get dividend income history"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        
        # Get year from query params (default to current year)
        year = request.query_params.get('year', datetime.now().year)
        try:
            year = int(year)
        except ValueError:
            year = datetime.now().year
        
        history = PortfolioCalculationService.calculate_dividend_income_history(portfolio, year)
        serializer = DividendIncomeHistorySerializer(history)
        return Response(serializer.data)


class BrokerSummaryView(APIView):
    """Get portfolio breakdown by broker"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """Get broker summary for a portfolio"""
        portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
        broker_summary = PortfolioCalculationService.calculate_broker_summary(portfolio)
        serializer = BrokerSummarySerializer(broker_summary, many=True)
        return Response({
            'count': len(broker_summary),
            'brokers': serializer.data
        })


# ============================================================================
# Frontend Template Views
# ============================================================================

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages


@login_required
def portfolio_list_view(request):
    """Frontend view: List all portfolios"""
    portfolios = Portfolio.objects.filter(user=request.user).prefetch_related('positions')
    
    # Add computed properties for template
    for portfolio in portfolios:
        portfolio.positions_count = portfolio.positions.count()
    
    return render(request, 'portfolio/portfolio_list.html', {
        'portfolios': portfolios
    })


@login_required
def portfolio_detail_view(request, pk):
    """Frontend view: Portfolio detail with summary"""
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    summary = PortfolioCalculationService.calculate_portfolio_summary(portfolio)

    # Build unified chronological ledger (transactions + dividend receipts)
    position_avg = {p.symbol: float(p.average_cost) for p in portfolio.positions.all()}
    ledger = []

    for tx in portfolio.transactions.order_by('-transaction_date'):
        qty = float(tx.quantity)
        price = float(tx.price)
        commission = float(tx.commission)
        tx_date = tx.transaction_date.date() if hasattr(tx.transaction_date, 'date') else tx.transaction_date

        if tx.transaction_type == 'BUY':
            ledger.append({
                'date': tx_date, 'type': 'buy', 'label': 'Buy',
                'symbol': tx.symbol,
                'price': price, 'quantity': qty,
                'commission': commission,
                'total': price * qty + commission,
                'extra': f"{float(tx.buy_yield):.2f}%" if tx.buy_yield else None,
                'extra_class': 'positive',
            })
        elif tx.transaction_type == 'SELL':
            avg = position_avg.get(tx.symbol)
            pnl = round((price - avg) * qty - commission, 2) if avg else None
            ledger.append({
                'date': tx_date, 'type': 'sell', 'label': 'Sell',
                'symbol': tx.symbol,
                'price': price, 'quantity': qty,
                'commission': commission,
                'total': price * qty - commission,
                'extra': f"${pnl:+,.2f}" if pnl is not None else None,
                'extra_class': 'positive' if (pnl or 0) >= 0 else 'negative',
            })
        elif tx.transaction_type == 'DIV':
            ledger.append({
                'date': tx_date, 'type': 'div', 'label': 'Dividend',
                'symbol': tx.symbol,
                'price': price, 'quantity': qty,
                'commission': commission,
                'total': price * qty - commission,
                'extra': None, 'extra_class': None,
            })
        elif tx.transaction_type == 'SPOF':
            ledger.append({
                'date': tx_date, 'type': 'spof', 'label': 'Spin-Off',
                'symbol': tx.symbol,
                'price': price, 'quantity': qty,
                'commission': 0, 'total': price * qty,
                'extra': None, 'extra_class': None,
            })
        elif tx.transaction_type == 'INT':
            ledger.append({
                'date': tx_date, 'type': 'int', 'label': 'Interest',
                'symbol': tx.symbol or '—',
                'price': None, 'quantity': None,
                'commission': 0, 'total': price,
                'extra': None, 'extra_class': None,
            })

    for div in portfolio.dividends.order_by('-payment_date'):
        ledger.append({
            'date': div.payment_date, 'type': 'div', 'label': 'Dividend',
            'symbol': div.symbol,
            'price': None, 'quantity': None,
            'commission': 0, 'total': float(div.amount),
            'extra': None, 'extra_class': None,
        })

    ledger.sort(key=lambda x: x['date'], reverse=True)

    return render(request, 'portfolio/portfolio_detail.html', {
        'portfolio': portfolio,
        'summary': summary,
        'ledger': ledger,
    })


@login_required
@require_http_methods(["GET", "POST"])
def portfolio_create_view(request):
    """Frontend view: Create new portfolio"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        is_active = request.POST.get('is_active') == 'on'
        
        if name:
            portfolio = Portfolio.objects.create(
                user=request.user,
                name=name,
                description=description,
                is_active=is_active
            )
            messages.success(request, f'Portfolio "{portfolio.name}" created successfully!')
            return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)
        else:
            messages.error(request, 'Portfolio name is required.')
    
    return render(request, 'portfolio/portfolio_form.html', {
        'portfolio': None
    })


@login_required
@require_http_methods(["GET", "POST"])
def portfolio_edit_view(request, pk):
    """Frontend view: Edit portfolio"""
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
    
    if request.method == 'POST':
        portfolio.name = request.POST.get('name', portfolio.name)
        portfolio.description = request.POST.get('description', '')
        portfolio.is_active = request.POST.get('is_active') == 'on'
        portfolio.save()
        
        messages.success(request, f'Portfolio "{portfolio.name}" updated successfully!')
        return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)
    
    return render(request, 'portfolio/portfolio_form.html', {
        'portfolio': portfolio
    })


@login_required
@require_http_methods(["GET", "POST"])
def transaction_create_view(request, portfolio_id):
    """Frontend view: Add transaction to portfolio"""
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
    
    if request.method == 'POST':
        try:
            symbol = request.POST.get('symbol', '').strip().upper()
            
            # Validate symbol is provided
            if not symbol:
                messages.error(request, 'Stock symbol is required.')
                return render(request, 'portfolio/transaction_form.html', {
                    'portfolio': portfolio,
                    'today': datetime.now().strftime('%Y-%m-%d')
                })
            
            # Ensure stock exists in database (auto-fetch if needed)
            success, message, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
            if not success:
                messages.error(request, message)
                return render(request, 'portfolio/transaction_form.html', {
                    'portfolio': portfolio,
                    'today': datetime.now().strftime('%Y-%m-%d')
                })
            
            # Use the resolved symbol from stock object (handles redirects like FB→META)
            resolved_symbol = stock.symbol
            
            # Get and clean form values
            commission_value = request.POST.get('commission', '').strip()
            if not commission_value:
                commission_value = 0
            
            # Create transaction with resolved symbol
            transaction = Transaction.objects.create(
                portfolio=portfolio,
                symbol=resolved_symbol,  # Use resolved symbol, not original input
                transaction_type=request.POST.get('transaction_type'),
                quantity=Decimal(request.POST.get('quantity')),
                price=Decimal(request.POST.get('price')),
                commission=Decimal(str(commission_value)),
                transaction_date=request.POST.get('transaction_date'),
                broker=request.POST.get('broker', ''),
                notes=request.POST.get('notes', '')
            )
            
            # Update position
            PortfolioCalculationService.update_position_from_transaction(transaction)
            
            # Fetch and store buy yield if applicable
            if transaction.transaction_type == 'BUY':
                PortfolioCalculationService.fetch_and_store_buy_yield(transaction)
            
            messages.success(request, f'Transaction for {transaction.symbol} added successfully!')
            return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"ERROR in transaction_create_view: {error_details}")
            messages.error(request, f'Error adding transaction: {str(e)}')
    
    return render(request, 'portfolio/transaction_form.html', {
        'portfolio': portfolio,
        'today': datetime.now().strftime('%Y-%m-%d')
    })


@login_required
def position_detail_view(request, portfolio_id, symbol):
    """Frontend view: Position detail with transactions"""
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
    position = get_object_or_404(Position, portfolio=portfolio, symbol=symbol.upper())
    
    # Get position details with metrics
    position_data = PortfolioCalculationService.get_position_detail(position)
    
    # Get transaction history
    transactions = position.get_transactions()
    
    return render(request, 'portfolio/position_detail.html', {
        'portfolio': portfolio,
        'position': position_data,
        'transactions': transactions
    })
