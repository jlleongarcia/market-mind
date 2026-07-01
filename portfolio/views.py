"""
Portfolio API Views
Comprehensive views for portfolio management with financial metrics integration
"""
import logging
from collections import defaultdict
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from datetime import datetime, date as date_type

from research.services import PriceCacheService
from .models import Portfolio, Transaction, Position, Dividend
from .serializers import (
    PortfolioSerializer, PortfolioSummarySerializer, TransactionSerializer,
    PositionSerializer, PositionDetailSerializer, DividendSerializer,
    BrokerSummarySerializer, DividendIncomeHistorySerializer
)
from .services import FXLotService, FXRateService, PortfolioCalculationService

logger = logging.getLogger(__name__)


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
from django.urls import reverse


@login_required
def portfolio_list_view(request):
    """Frontend view: List all portfolios"""
    from research.services import PriceCacheService

    portfolios = list(Portfolio.objects.filter(user=request.user).prefetch_related('positions'))

    # Single batch price lookup for every symbol across all portfolios
    all_symbols = list({pos.symbol for p in portfolios for pos in p.positions.all()})
    price_data = PriceCacheService.get_prices(all_symbols) if all_symbols else {}

    for portfolio in portfolios:
        positions = list(portfolio.positions.all())
        portfolio.positions_count = len(positions)

        total_invested = sum(float(pos.total_cost) for pos in positions)
        current_value = sum(
            (price_data[pos.symbol]['price'] if pos.symbol in price_data
             else (float(pos.current_price) if pos.current_price else float(pos.average_cost)))
            * float(pos.quantity)
            for pos in positions
        )
        gain_loss = current_value - total_invested
        portfolio.live_total_value      = round(current_value, 2)
        portfolio.live_total_invested   = round(total_invested, 2)
        portfolio.live_total_return     = round(gain_loss, 2)
        portfolio.live_return_pct       = round(gain_loss / total_invested * 100, 2) if total_invested else 0

    return render(request, 'portfolio/portfolio_list.html', {
        'portfolios': portfolios
    })


@login_required
def portfolio_detail_view(request, pk):
    """Frontend view: Portfolio detail with summary"""
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    summary = PortfolioCalculationService.calculate_portfolio_summary(portfolio)

    # Build unified chronological ledger (transactions + dividend receipts)
    ledger = []

    def _fmt_cur(cur, amount):
        if cur and cur != 'USD':
            return f"{cur} {amount:,.2f}"
        return f"${amount:,.2f}"

    def _fmt_qty(qty):
        return f"{int(qty):,}" if qty == int(qty) else f"{qty:,.4f}".rstrip('0').rstrip('.')

    def _net_display(net_class, cur, amount):
        sign = '+' if net_class == 'positive' else ('-' if net_class == 'negative' else '')
        return sign + _fmt_cur(cur, amount)

    # Forward pass: compute the running average cost per symbol at the exact moment
    # of each SELL, so P&L chips reflect the true cost basis at sale time rather than
    # the current position average (which changes after subsequent buys).
    _run_qty: dict = {}   # symbol → running total shares
    _run_cost: dict = {}  # symbol → running total cost (price*qty + commission)
    _avg_at_sell: dict = {}  # tx.id → avg_cost per share at time of that sell

    for tx in portfolio.transactions.order_by('transaction_date', 'id'):
        sym = tx.symbol
        qty_f = float(tx.quantity)
        price_f = float(tx.price)
        comm_f = float(tx.commission)
        if tx.transaction_type == 'BUY':
            prev_qty = _run_qty.get(sym, 0.0)
            prev_cost = _run_cost.get(sym, 0.0)
            new_qty = prev_qty + qty_f
            _run_qty[sym] = new_qty
            _run_cost[sym] = prev_cost + qty_f * price_f + comm_f
        elif tx.transaction_type == 'SPOF':
            prev_qty = _run_qty.get(sym, 0.0)
            prev_cost = _run_cost.get(sym, 0.0)
            new_qty = prev_qty + qty_f
            _run_qty[sym] = new_qty
            _run_cost[sym] = prev_cost + qty_f * price_f
        elif tx.transaction_type == 'SELL':
            cur_qty = _run_qty.get(sym, 0.0)
            cur_cost = _run_cost.get(sym, 0.0)
            _avg_at_sell[tx.id] = (cur_cost / cur_qty) if cur_qty > 0 else None
            remaining = max(0.0, cur_qty - qty_f)
            _run_qty[sym] = remaining
            _run_cost[sym] = remaining * (_avg_at_sell[tx.id] or 0.0)

    for tx in portfolio.transactions.order_by('-transaction_date'):
        qty = float(tx.quantity)
        price = float(tx.price)
        commission = float(tx.commission)
        tx_date = tx.transaction_date.date() if hasattr(tx.transaction_date, 'date') else tx.transaction_date
        tx_cur = tx.transaction_currency or 'USD'

        if tx.transaction_type == 'BUY':
            chips = [f"Qty: {_fmt_qty(qty)}", f"Price: {_fmt_cur(tx_cur, price)}"]
            if commission:
                chips.append(f"Commission: {_fmt_cur(tx_cur, commission)}")
            if tx.buy_yield:
                chips.append(f"Buy Yield: {float(tx.buy_yield):.2f}%")
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'buy', 'label': 'Buy',
                'description': f"Bought {_fmt_qty(qty)}× {tx.symbol} @ {_fmt_cur(tx_cur, price)}",
                'net_display': _net_display('negative', tx_cur, price * qty + commission),
                'net_class': 'negative',
                'extra': '||'.join(chips),
            })
        elif tx.transaction_type == 'SELL':
            avg = _avg_at_sell.get(tx.id)
            pnl = round((price - avg) * qty - commission, 2) if avg else None
            chips = [f"Qty: {_fmt_qty(qty)}", f"Price: {_fmt_cur(tx_cur, price)}"]
            if avg:
                chips.append(f"Avg Cost: {_fmt_cur(tx_cur, avg)}")
            if commission:
                chips.append(f"Commission: {_fmt_cur(tx_cur, commission)}")
            if pnl is not None:
                pnl_sign = '+' if pnl >= 0 else '-'
                chips.append(f"Net P&L: {pnl_sign}{_fmt_cur(tx_cur, abs(pnl))}")
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'sell', 'label': 'Sell',
                'description': f"Sold {_fmt_qty(qty)}× {tx.symbol} @ {_fmt_cur(tx_cur, price)}",
                'net_display': _net_display('positive', tx_cur, price * qty - commission),
                'net_class': 'positive',
                'extra': '||'.join(chips),
            })
        elif tx.transaction_type == 'DIV':
            chips = []
            if qty:
                chips.append(f"Shares: {_fmt_qty(qty)}")
            if price:
                chips.append(f"Per Share: {_fmt_cur(tx_cur, price)}")
            if commission:
                chips.append(f"Commission: {_fmt_cur(tx_cur, commission)}")
            desc = f"Dividend — {tx.symbol}"
            if qty:
                desc += f" ({_fmt_qty(qty)} sh)"
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'div', 'label': 'Dividend',
                'description': desc,
                'net_display': _net_display('positive', tx_cur, price * qty - commission),
                'net_class': 'positive',
                'extra': '||'.join(chips) if chips else None,
            })
        elif tx.transaction_type == 'SPOF':
            chips = [f"Qty: {_fmt_qty(qty)}", f"Price: {_fmt_cur(tx_cur, price)}"]
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'spof', 'label': 'Spin-Off',
                'description': f"Spin-off — {tx.symbol}",
                'net_display': _fmt_cur(tx_cur, price * qty),
                'net_class': 'neutral',
                'extra': '||'.join(chips),
            })
        elif tx.transaction_type == 'INT':
            chips = []
            if tx.broker:
                chips.append(f"Broker: {tx.broker}")
            if tx.notes:
                chips.append(f"Notes: {tx.notes}")
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'int', 'label': 'Interest',
                'description': "Interest earned",
                'net_display': _net_display('positive', tx_cur, price),
                'net_class': 'positive',
                'extra': '||'.join(chips) if chips else None,
            })
        elif tx.transaction_type == 'DEP':
            chips = []
            if tx.broker:
                chips.append(f"Broker: {tx.broker}")
            if tx.notes:
                chips.append(f"Notes: {tx.notes}")
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'dep', 'label': 'Deposit',
                'description': "Cash deposit",
                'net_display': _net_display('positive', tx_cur, price),
                'net_class': 'positive',
                'extra': '||'.join(chips) if chips else None,
            })
        elif tx.transaction_type == 'WIT':
            chips = []
            if tx.broker:
                chips.append(f"Broker: {tx.broker}")
            if tx.notes:
                chips.append(f"Notes: {tx.notes}")
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'wit', 'label': 'Withdrawal',
                'description': "Cash withdrawal",
                'net_display': _net_display('negative', tx_cur, price),
                'net_class': 'negative',
                'extra': '||'.join(chips) if chips else None,
            })
        elif tx.transaction_type == 'EXC':
            from_cur = tx.from_currency or tx_cur
            to_cur = tx.to_currency or ''
            from_amt = float(tx.from_amount) if tx.from_amount else 0.0
            to_amt = float(tx.to_amount) if tx.to_amount else 0.0
            comm_cur = tx.commission_currency or from_cur or 'USD'
            chips = []
            if from_amt:
                chips.append(f"Paid: {from_cur} {from_amt:,.2f}")
            if to_amt and to_cur:
                chips.append(f"Received: {to_cur} {to_amt:,.2f}")
            if commission:
                chips.append(f"Commission ({comm_cur}): {commission:,.2f}")
            desc = f"Exchange {from_cur} → {to_cur}" if to_cur else f"Exchange {from_cur}"
            if to_amt and to_cur:
                net_disp, net_cls = f"+{to_cur} {to_amt:,.2f}", 'positive'
            else:
                net_disp, net_cls = f"{from_cur} {from_amt:,.2f}", 'neutral'
            ledger.append({
                'tx_id': tx.id, 'date': tx_date,
                'type': 'exc', 'label': 'Exchange',
                'description': desc,
                'net_display': net_disp,
                'net_class': net_cls,
                'extra': '||'.join(chips) if chips else None,
            })

    for div in portfolio.dividends.all():
        pay_date_known = bool(div.payment_date)
        effective_date = div.payment_date or div.ex_dividend_date
        qty = float(div.quantity) if div.quantity else None
        div_per_share = round(float(div.amount) / qty, 4) if qty else None
        chips = []
        if qty:
            chips.append(f"Shares: {_fmt_qty(qty)}")
        if div_per_share:
            chips.append(f"Per Share: {div_per_share:.4f}")
        desc = f"Dividend — {div.symbol}"
        if qty:
            desc += f" ({_fmt_qty(qty)} sh)"
        ledger.append({
            'tx_id': None,
            'date': effective_date,
            'date_estimated': not pay_date_known,
            'type': 'div', 'label': 'Dividend',
            'description': desc,
            'net_display': f"+${float(div.amount):,.2f}",
            'net_class': 'positive',
            'extra': '||'.join(chips) if chips else None,
        })

    ledger.sort(key=lambda x: x['date'] or date_type.min, reverse=True)

    # ── Cash balances per currency ────────────────────────────────────────────
    cash_by_currency: dict[str, float] = defaultdict(float)
    for tx in portfolio.transactions.all():
        cur = tx.transaction_currency or portfolio.native_currency
        p = float(tx.price)
        q = float(tx.quantity)
        c = float(tx.commission)
        if tx.transaction_type == 'DEP':
            cash_by_currency[cur] += p
        elif tx.transaction_type == 'WIT':
            cash_by_currency[cur] -= p
        elif tx.transaction_type == 'INT':
            cash_by_currency[cur] += p
        elif tx.transaction_type == 'BUY':
            cash_by_currency[cur] -= (p * q + c)
        elif tx.transaction_type == 'SELL':
            cash_by_currency[cur] += (p * q - c)
        elif tx.transaction_type == 'DIV':
            cash_by_currency[cur] += (p * q - c)
        elif tx.transaction_type == 'EXC':
            from_cur = tx.from_currency or cur
            to_cur = tx.to_currency or cur
            comm_cur = tx.commission_currency or from_cur
            cash_by_currency[from_cur] -= float(tx.from_amount) if tx.from_amount else 0
            cash_by_currency[to_cur] += float(tx.to_amount) if tx.to_amount else 0
            cash_by_currency[comm_cur] -= c

    cash_balances = [
        {'currency': cur, 'balance': round(bal, 2)}
        for cur, bal in sorted(cash_by_currency.items())
        if abs(bal) >= 0.01
    ]

    # ── Yearly summary ────────────────────────────────────────────────────────
    _zero = lambda: {'deposits': 0.0, 'withdrawals': 0.0, 'invested': 0.0,
                     'sold': 0.0, 'dividends': 0.0, 'interest': 0.0}
    yearly: dict[int, dict] = defaultdict(_zero)
    # per-currency breakdown (raw amounts, no FX conversion)
    yearly_by_cur: dict[int, dict] = defaultdict(lambda: defaultdict(_zero))

    for tx in portfolio.transactions.all():
        year = tx.transaction_date.year
        cur  = tx.transaction_currency or portfolio.native_currency
        p = float(tx.price)
        q = float(tx.quantity)
        c = float(tx.commission)

        def _native(fallback: float) -> float:
            return float(tx.native_amount) if tx.native_amount else fallback

        if tx.transaction_type == 'DEP':
            yearly[year]['deposits']    += _native(p);  yearly_by_cur[year][cur]['deposits']    += p
        elif tx.transaction_type == 'WIT':
            yearly[year]['withdrawals'] += _native(p);  yearly_by_cur[year][cur]['withdrawals'] += p
        elif tx.transaction_type == 'INT':
            yearly[year]['interest']    += _native(p);  yearly_by_cur[year][cur]['interest']    += p
        elif tx.transaction_type == 'BUY':
            yearly[year]['invested']    += _native(p * q + c); yearly_by_cur[year][cur]['invested']    += (p * q + c)
        elif tx.transaction_type == 'SELL':
            yearly[year]['sold']        += _native(p * q - c); yearly_by_cur[year][cur]['sold']        += (p * q - c)
        elif tx.transaction_type in ('DIV', 'SPOF'):
            yearly[year]['dividends']   += _native(p * q - c); yearly_by_cur[year][cur]['dividends']   += (p * q - c)
        # EXC: currency swap, not counted in yearly summary

    for div in portfolio.dividends.all():
        year = (div.payment_date or div.ex_dividend_date).year
        yearly[year]['dividends'] += float(div.amount)

    yearly_summary = []
    for yr, d in sorted(yearly.items(), reverse=True):
        passive = d['dividends'] + d['interest']
        by_cur = []
        for cur, cd in sorted(yearly_by_cur.get(yr, {}).items()):
            cp = cd['dividends'] + cd['interest']
            if any(abs(v) >= 0.01 for v in cd.values()):
                by_cur.append({
                    'currency':      cur,
                    'deposits':      round(cd['deposits'], 2),
                    'withdrawals':   round(cd['withdrawals'], 2),
                    'invested':      round(cd['invested'], 2),
                    'sold':          round(cd['sold'], 2),
                    'dividends':     round(cd['dividends'], 2),
                    'interest':      round(cd['interest'], 2),
                    'passive_income': round(cp, 2),
                })
        yearly_summary.append({
            'year':           yr,
            'deposits':       round(d['deposits'], 2),
            'withdrawals':    round(d['withdrawals'], 2),
            'invested':       round(d['invested'], 2),
            'sold':           round(d['sold'], 2),
            'dividends':      round(d['dividends'], 2),
            'interest':       round(d['interest'], 2),
            'passive_income': round(passive, 2),
            'net_cash':       round(d['deposits'] - d['withdrawals'] + d['interest'], 2),
            'by_currency':    by_cur,
        })

    return render(request, 'portfolio/portfolio_detail.html', {
        'portfolio': portfolio,
        'summary': summary,
        'ledger': ledger,
        'cash_balances': cash_balances,
        'yearly_summary': yearly_summary,
        'native_currency': portfolio.native_currency,
    })


@login_required
@require_http_methods(["GET", "POST"])
def portfolio_create_view(request):
    """Frontend view: Create new portfolio"""
    from .models import CURRENCY_CHOICES
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        is_active = request.POST.get('is_active') == 'on'
        native_currency = request.POST.get('native_currency', 'EUR')

        if name:
            portfolio = Portfolio.objects.create(
                user=request.user,
                name=name,
                description=description,
                is_active=is_active,
                native_currency=native_currency,
            )
            messages.success(request, f'Portfolio "{portfolio.name}" created successfully!')
            return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)
        else:
            messages.error(request, 'Portfolio name is required.')

    return render(request, 'portfolio/portfolio_form.html', {
        'portfolio': None,
        'currency_choices': CURRENCY_CHOICES,
    })


@login_required
@require_http_methods(["GET", "POST"])
def portfolio_edit_view(request, pk):
    """Frontend view: Edit portfolio"""
    from .models import CURRENCY_CHOICES
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    if request.method == 'POST':
        portfolio.name = request.POST.get('name', portfolio.name)
        portfolio.description = request.POST.get('description', '')
        portfolio.is_active = request.POST.get('is_active') == 'on'
        portfolio.native_currency = request.POST.get('native_currency', portfolio.native_currency)
        portfolio.save()

        messages.success(request, f'Portfolio "{portfolio.name}" updated successfully!')
        return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)

    return render(request, 'portfolio/portfolio_form.html', {
        'portfolio': portfolio,
        'currency_choices': CURRENCY_CHOICES,
    })


@login_required
@require_http_methods(["GET", "POST"])
def transaction_create_view(request, portfolio_id):
    """Frontend view: Add transaction to portfolio"""
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)

    CASH_TYPES  = {'INT', 'DEP', 'WIT'}
    STOCK_TYPES = {'BUY', 'SELL', 'DIV', 'SPOF'}
    # Types that need FX processing (all except DEP / WIT)
    FX_TYPES    = {'BUY', 'SELL', 'DIV', 'INT', 'EXC'}

    if request.method == 'POST':
        try:
            tx_type = request.POST.get('transaction_type', '').upper()
            symbol  = request.POST.get('symbol', '').strip().upper()

            if tx_type in STOCK_TYPES:
                if not symbol:
                    messages.error(request, 'Stock symbol is required.')
                    from .models import CURRENCY_CHOICES
                    return render(request, 'portfolio/transaction_form.html', {
                        'portfolio': portfolio,
                        'today': datetime.now().strftime('%Y-%m-%d'),
                        'currency_choices': CURRENCY_CHOICES,
                    })
                success, message, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
                if not success:
                    messages.error(request, message)
                    from .models import CURRENCY_CHOICES
                    return render(request, 'portfolio/transaction_form.html', {
                        'portfolio': portfolio,
                        'today': datetime.now().strftime('%Y-%m-%d'),
                        'currency_choices': CURRENCY_CHOICES,
                    })
                resolved_symbol = stock.symbol
                stock_currency = stock.currency or 'USD'
            else:
                resolved_symbol = symbol
                stock_currency = ''

            commission_value = request.POST.get('commission', '').strip() or '0'
            quantity_raw     = request.POST.get('quantity', '').strip()
            quantity_value   = Decimal(quantity_raw) if quantity_raw else Decimal('1')
            tx_date_str      = request.POST.get('transaction_date', '')

            # ── EXC-specific fields ──────────────────────────────────────────
            from_currency      = request.POST.get('from_currency', '').strip().upper()
            from_amount_raw    = request.POST.get('from_amount', '').strip()
            to_currency        = request.POST.get('to_currency', '').strip().upper()
            to_amount_raw      = request.POST.get('to_amount', '').strip()
            commission_cur     = request.POST.get('commission_currency', '').strip().upper()

            from_amount = Decimal(from_amount_raw) if from_amount_raw else None
            to_amount   = Decimal(to_amount_raw)   if to_amount_raw   else None

            # ── Resolve transaction currency ─────────────────────────────────
            if tx_type == 'EXC':
                tx_currency = to_currency or from_currency
            elif tx_type in STOCK_TYPES:
                tx_currency = request.POST.get('transaction_currency', '').strip().upper() or stock_currency
            elif tx_type in {'DEP', 'WIT'}:
                tx_currency = request.POST.get('dep_wit_currency', '').strip().upper() or portfolio.native_currency
            else:
                # INT
                tx_currency = request.POST.get('transaction_currency', '').strip().upper() or portfolio.native_currency

            # ── FX rate resolution ───────────────────────────────────────────
            manual_fx  = request.POST.get('fx_rate', '').strip()
            fx_rate    = None
            fx_source  = ''
            native_amt = None

            if tx_type in FX_TYPES and tx_currency and tx_currency != portfolio.native_currency:
                tx_date_obj = datetime.strptime(tx_date_str, '%Y-%m-%d').date() if tx_date_str else date_type.today()

                if tx_type == 'EXC' and from_amount and to_amount:
                    # Derive rate directly from the user's own amounts
                    # 1 to_currency = (from_amount / to_amount) native
                    native_cur = portfolio.native_currency
                    if from_currency == native_cur:
                        fx_rate   = from_amount / to_amount
                        fx_source = 'computed'
                    elif to_currency == native_cur:
                        fx_rate   = to_amount / from_amount
                        fx_source = 'computed'
                    else:
                        # Neither side is native — fetch from Frankfurter
                        fx_rate, fx_source = FXRateService.get_rate(tx_currency, portfolio.native_currency, tx_date_obj)
                    native_amt = from_amount  # what was paid in native (or closest proxy)
                elif manual_fx:
                    fx_rate   = Decimal(manual_fx)
                    fx_source = 'manual'
                else:
                    fx_rate, fx_source = FXRateService.get_rate(tx_currency, portfolio.native_currency, tx_date_obj)

                if fx_rate and tx_type != 'EXC':
                    price_val = Decimal(request.POST.get('price', '0') or '0')
                    total_in_stock_cur = quantity_value * price_val
                    if tx_type == 'BUY':
                        total_in_stock_cur += Decimal(commission_value)
                    else:
                        total_in_stock_cur -= Decimal(commission_value)
                    native_amt = total_in_stock_cur * fx_rate

                if fx_source == 'unavailable':
                    messages.warning(
                        request,
                        f"No FX rate found for {tx_currency}/{portfolio.native_currency} around "
                        f"{tx_date_str}. Please enter it manually in the FX Rate field and resubmit."
                    )
                    from .models import CURRENCY_CHOICES
                    return render(request, 'portfolio/transaction_form.html', {
                        'portfolio': portfolio,
                        'today': datetime.now().strftime('%Y-%m-%d'),
                        'fx_warning': True,
                        'post': request.POST,
                        'currency_choices': CURRENCY_CHOICES,
                    })

            transaction = Transaction.objects.create(
                portfolio=portfolio,
                symbol=resolved_symbol,
                transaction_type=tx_type,
                quantity=quantity_value,
                price=Decimal(request.POST.get('price', '0') or '0'),
                commission=Decimal(commission_value),
                transaction_date=tx_date_str,
                broker=request.POST.get('broker', ''),
                notes=request.POST.get('notes', ''),
                # FX fields
                transaction_currency=tx_currency,
                fx_rate=fx_rate,
                native_amount=native_amt,
                fx_rate_source=fx_source,
                # EXC-only
                from_currency=from_currency,
                from_amount=from_amount,
                to_currency=to_currency,
                to_amount=to_amount,
                commission_currency=commission_cur,
            )

            if tx_type in STOCK_TYPES:
                PortfolioCalculationService.update_position_from_transaction(transaction)

            if transaction.transaction_type == 'BUY':
                PortfolioCalculationService.fetch_and_store_buy_yield(transaction)

            # Process FX lots
            if tx_type in FX_TYPES:
                try:
                    FXLotService.process_transaction(transaction)
                except Exception as fx_err:
                    logger.warning("FX lot processing failed for tx %s: %s", transaction.id, fx_err)

            from datetime import date as _date
            from django.core.cache import cache as _cache
            _today = _date.today().isoformat()
            _cache.delete(f"price_range_{portfolio.id}_{_today}")
            if transaction.symbol:
                PriceCacheService.invalidate(transaction.symbol)

            messages.success(request, f'Transaction recorded successfully!')
            return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"ERROR in transaction_create_view: {error_details}")
            messages.error(request, f'Error adding transaction: {str(e)}')

    from .models import CURRENCY_CHOICES
    return render(request, 'portfolio/transaction_form.html', {
        'portfolio': portfolio,
        'today': datetime.now().strftime('%Y-%m-%d'),
        'currency_choices': CURRENCY_CHOICES,
    })


@login_required
@require_http_methods(["POST"])
def portfolio_sync_dividends(request, pk):
    """Refresh research dividend data from yfinance, then auto-record qualifying payments."""
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
    result = PortfolioCalculationService.auto_record_dividends(portfolio)
    if result['created'] > 0:
        messages.success(request, f"{result['created']} dividend payment(s) recorded automatically.")
    else:
        messages.info(request, "No new dividends to record — everything is already up to date.")
    if result.get('refresh_errors'):
        messages.warning(
            request,
            f"Could not refresh data for: {', '.join(result['refresh_errors'])}. "
            "Those symbols may show stale dividends."
        )
    return redirect('portfolio:portfolio_detail_view', pk=pk)


@login_required
@require_http_methods(["POST"])
def portfolio_delete_view(request, pk):
    """Delete a portfolio and all its data after user confirmation."""
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
    name = portfolio.name
    portfolio.delete()
    messages.success(request, f'Portfolio "{name}" has been deleted.')
    return redirect('portfolio:portfolio_list_view')


@login_required
def position_detail_view(request, portfolio_id, symbol):
    """Frontend view: Position detail with transactions"""
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
    position = get_object_or_404(Position, portfolio=portfolio, symbol=symbol.upper())

    position_data = PortfolioCalculationService.get_position_detail(position)
    transactions = position.get_transactions()

    return render(request, 'portfolio/position_detail.html', {
        'portfolio': portfolio,
        'position': position_data,
        'transactions': transactions
    })


@login_required
@require_http_methods(["GET", "POST"])
def transaction_edit_view(request, portfolio_id, tx_id):
    """Frontend view: Edit an existing transaction"""
    from .models import CURRENCY_CHOICES
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
    transaction = get_object_or_404(Transaction, pk=tx_id, portfolio=portfolio)

    STOCK_TYPES = {'BUY', 'SELL', 'DIV', 'SPOF'}
    FX_TYPES    = {'BUY', 'SELL', 'DIV', 'INT', 'EXC'}

    if request.method == 'POST':
        old_symbol = transaction.symbol
        old_type   = transaction.transaction_type

        try:
            tx_type = request.POST.get('transaction_type', '').upper()
            symbol  = request.POST.get('symbol', '').strip().upper()

            if tx_type in STOCK_TYPES and symbol:
                success, message, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
                if not success:
                    messages.error(request, message)
                    return redirect('portfolio:transaction_edit_view', portfolio_id=portfolio_id, tx_id=tx_id)
                resolved_symbol = stock.symbol
                stock_currency  = stock.currency or 'USD'
            else:
                resolved_symbol = ''
                stock_currency  = ''

            commission_value = request.POST.get('commission', '').strip() or '0'
            quantity_raw     = request.POST.get('quantity', '').strip()
            quantity_value   = Decimal(quantity_raw) if quantity_raw else Decimal('1')
            tx_date_str      = request.POST.get('transaction_date', '')

            # Resolve transaction currency
            if tx_type == 'EXC':
                to_currency   = request.POST.get('to_currency', '').strip().upper()
                from_currency = request.POST.get('from_currency', '').strip().upper()
                tx_currency   = to_currency or from_currency
            elif tx_type in STOCK_TYPES:
                tx_currency = request.POST.get('transaction_currency', '').strip().upper() or stock_currency
            elif tx_type in {'DEP', 'WIT'}:
                tx_currency = request.POST.get('dep_wit_currency', '').strip().upper() or portfolio.native_currency
            else:
                tx_currency = request.POST.get('transaction_currency', '').strip().upper() or portfolio.native_currency

            # FX rate resolution (simplified — no unavailable-warning redirect for edits)
            manual_fx  = request.POST.get('fx_rate', '').strip()
            fx_rate    = None
            fx_source  = ''
            native_amt = None

            if tx_type in FX_TYPES and tx_currency and tx_currency != portfolio.native_currency:
                tx_date_obj = datetime.strptime(tx_date_str, '%Y-%m-%d').date() if tx_date_str else date_type.today()
                if manual_fx:
                    fx_rate   = Decimal(manual_fx)
                    fx_source = 'manual'
                else:
                    fx_rate, fx_source = FXRateService.get_rate(tx_currency, portfolio.native_currency, tx_date_obj)

                if fx_rate and tx_type != 'EXC':
                    price_val = Decimal(request.POST.get('price', '0') or '0')
                    total_in_stock_cur = quantity_value * price_val
                    if tx_type == 'BUY':
                        total_in_stock_cur += Decimal(commission_value)
                    else:
                        total_in_stock_cur -= Decimal(commission_value)
                    native_amt = total_in_stock_cur * fx_rate

            # Apply updates
            transaction.symbol           = resolved_symbol
            transaction.transaction_type = tx_type
            transaction.quantity         = quantity_value
            transaction.price            = Decimal(request.POST.get('price', '0') or '0')
            transaction.commission       = Decimal(commission_value)
            transaction.transaction_date = tx_date_str
            transaction.broker           = request.POST.get('broker', '')
            transaction.notes            = request.POST.get('notes', '')
            transaction.transaction_currency = tx_currency
            if fx_rate is not None:
                transaction.fx_rate        = fx_rate
                transaction.native_amount  = native_amt
                transaction.fx_rate_source = fx_source

            if tx_type == 'EXC':
                from_amount_raw = request.POST.get('from_amount', '').strip()
                to_amount_raw   = request.POST.get('to_amount', '').strip()
                transaction.from_currency       = from_currency
                transaction.from_amount         = Decimal(from_amount_raw) if from_amount_raw else None
                transaction.to_currency         = to_currency
                transaction.to_amount           = Decimal(to_amount_raw) if to_amount_raw else None
                transaction.commission_currency = request.POST.get('commission_currency', '').strip().upper()

            transaction.save()

            # Rebuild positions for any affected stock symbols
            symbols_to_rebuild = set()
            if old_symbol and old_type in STOCK_TYPES:
                symbols_to_rebuild.add(old_symbol)
            if resolved_symbol and tx_type in STOCK_TYPES:
                symbols_to_rebuild.add(resolved_symbol)
            for sym in symbols_to_rebuild:
                PortfolioCalculationService.rebuild_position(portfolio, sym)

            messages.success(request, 'Transaction updated successfully!')
            return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)

        except Exception as e:
            import traceback
            logger.error("Error in transaction_edit_view: %s", traceback.format_exc())
            messages.error(request, f'Error updating transaction: {str(e)}')

    # GET: build pre-fill dict from transaction
    tx_date = transaction.transaction_date
    tx_date_str = tx_date.strftime('%Y-%m-%d') if hasattr(tx_date, 'strftime') else str(tx_date)[:10]

    post = {
        'transaction_type':    transaction.transaction_type,
        'symbol':              transaction.symbol or '',
        'quantity':            str(transaction.quantity),
        'price':               str(transaction.price),
        'commission':          str(transaction.commission),
        'transaction_date':    tx_date_str,
        'broker':              transaction.broker or '',
        'notes':               transaction.notes or '',
        'fx_rate':             str(transaction.fx_rate) if transaction.fx_rate else '',
        'transaction_currency': transaction.transaction_currency or '',
        'dep_wit_currency':    transaction.transaction_currency or '',
        'from_currency':       transaction.from_currency or '',
        'from_amount':         str(transaction.from_amount) if transaction.from_amount else '',
        'to_currency':         transaction.to_currency or '',
        'to_amount':           str(transaction.to_amount) if transaction.to_amount else '',
        'commission_currency': transaction.commission_currency or '',
    }

    form_action = reverse('portfolio:transaction_edit_view', kwargs={'portfolio_id': portfolio_id, 'tx_id': tx_id})

    return render(request, 'portfolio/transaction_form.html', {
        'portfolio':       portfolio,
        'today':           datetime.now().strftime('%Y-%m-%d'),
        'is_edit':         True,
        'transaction':     transaction,
        'post':            post,
        'form_action':     form_action,
        'currency_choices': CURRENCY_CHOICES,
    })


@login_required
@require_http_methods(["POST"])
def transaction_delete_view(request, portfolio_id, tx_id):
    """Delete a transaction and rebuild affected positions."""
    portfolio   = get_object_or_404(Portfolio, pk=portfolio_id, user=request.user)
    transaction = get_object_or_404(Transaction, pk=tx_id, portfolio=portfolio)

    STOCK_TYPES = {'BUY', 'SELL', 'DIV', 'SPOF'}
    symbol  = transaction.symbol
    tx_type = transaction.transaction_type

    # Restore FX lot amounts that this transaction consumed (FIFO integrity)
    for consumption in transaction.fx_lot_consumptions.all():
        lot = consumption.lot
        lot.remaining_amount_foreign += consumption.amount_foreign_consumed
        lot.is_closed = False
        lot.save(update_fields=['remaining_amount_foreign', 'is_closed'])

    transaction.delete()  # cascades to FXLot (source) and FXLotConsumption records

    if symbol and tx_type in STOCK_TYPES:
        PortfolioCalculationService.rebuild_position(portfolio, symbol)

    messages.success(request, 'Transaction deleted successfully.')
    return redirect('portfolio:portfolio_detail_view', pk=portfolio.id)


@login_required
def portfolio_combined_view(request):
    """Frontend view: Combined summary of all portfolios with same UI as individual portfolio."""
    from datetime import timedelta
    from research.models import HistoricalPrice
    from django.db.models import Max, Min

    portfolios = list(Portfolio.objects.filter(user=request.user).prefetch_related('positions', 'transactions', 'dividends'))

    if not portfolios:
        return redirect('portfolio:portfolio_list_view')

    # Gather all unique symbols
    all_symbols = list({pos.symbol for p in portfolios for pos in p.positions.all()})

    price_data_map = PriceCacheService.get_prices(all_symbols) if all_symbols else {}

    one_year_ago = date_type.today() - timedelta(days=365)
    price_ranges = HistoricalPrice.objects.filter(
        stock__symbol__in=all_symbols,
        date__gte=one_year_ago,
    ).values('stock__symbol').annotate(high_52w=Max('high'), low_52w=Min('low'))
    price_range_map = {r['stock__symbol']: r for r in price_ranges}

    # Merge positions by symbol
    symbol_data = {}
    for portfolio in portfolios:
        for pos in portfolio.positions.all():
            if pos.symbol not in symbol_data:
                symbol_data[pos.symbol] = {
                    'qty': Decimal('0'),
                    'total_cost': Decimal('0'),
                    'first_pos': pos,
                }
            symbol_data[pos.symbol]['qty']        += pos.quantity
            symbol_data[pos.symbol]['total_cost'] += pos.total_cost

    positions_detail = []
    for symbol, data in symbol_data.items():
        pos      = data['first_pos']
        pos_data = PortfolioCalculationService.get_position_detail(pos, price_range_map, price_data_map)

        total_qty      = float(data['qty'])
        total_invested = float(data['total_cost'])
        avg_cost       = total_invested / total_qty if total_qty > 0 else 0

        price_entry   = price_data_map.get(symbol)
        current_price = price_entry['price'] if price_entry else float(pos.current_price or pos.average_cost)
        current_value = current_price * total_qty
        gain_loss     = current_value - total_invested
        gain_loss_pct = (gain_loss / total_invested * 100) if total_invested > 0 else 0

        pos_data['quantity']      = total_qty
        pos_data['total_invested'] = round(total_invested, 2)
        pos_data['average_cost']  = round(avg_cost, 4)
        pos_data['current_value'] = round(current_value, 2)
        pos_data['gain_loss']     = round(gain_loss, 2)
        pos_data['gain_loss_percentage'] = round(gain_loss_pct, 2)

        # Scale annual dividend income for combined quantity
        if pos_data.get('annual_dividend_income') and float(pos.quantity) > 0:
            per_share = pos_data['annual_dividend_income'] / float(pos.quantity)
            pos_data['annual_dividend_income'] = round(per_share * total_qty, 2)
            if total_invested > 0:
                pos_data['yield_on_cost'] = round(pos_data['annual_dividend_income'] / total_invested * 100, 2)

        positions_detail.append(pos_data)

    positions_detail.sort(key=lambda p: p['current_value'], reverse=True)

    total_invested_all = sum(p['total_invested'] for p in positions_detail)
    current_value_all  = sum(p['current_value']  for p in positions_detail)
    gain_loss_all      = current_value_all - total_invested_all
    gain_loss_pct_all  = (gain_loss_all / total_invested_all * 100) if total_invested_all > 0 else 0
    annual_div_all     = sum(p['annual_dividend_income'] or 0 for p in positions_detail)

    stale_dates = [
        p['price_date'] for p in positions_detail
        if not p.get('price_is_live') and p.get('price_date')
    ]

    # Build combined ledger (read-only — no tx_id needed for edit/delete)
    TYPE_LABELS = {
        'BUY': 'Buy', 'SELL': 'Sell', 'DIV': 'Dividend', 'SPOF': 'Spin-Off',
        'INT': 'Interest', 'DEP': 'Deposit', 'WIT': 'Withdrawal', 'EXC': 'Exchange',
    }
    position_avg = {p['symbol']: p['average_cost'] for p in positions_detail}
    ledger = []

    for portfolio in portfolios:
        for tx in portfolio.transactions.order_by('-transaction_date'):
            qty        = float(tx.quantity)
            price      = float(tx.price)
            commission = float(tx.commission)
            tx_date    = tx.transaction_date.date() if hasattr(tx.transaction_date, 'date') else tx.transaction_date
            tx_type    = tx.transaction_type
            is_cash    = tx_type in {'INT', 'DEP', 'WIT'}
            tx_cur     = tx.transaction_currency or ''

            extra       = None
            extra_class = None
            if tx_type == 'BUY' and tx.buy_yield:
                extra       = f"{float(tx.buy_yield):.2f}%"
                extra_class = 'positive'
            elif tx_type == 'SELL':
                avg = position_avg.get(tx.symbol)
                if avg:
                    pnl         = round((price - avg) * qty - commission, 2)
                    extra       = f"${pnl:+,.2f}"
                    extra_class = 'positive' if pnl >= 0 else 'negative'
            elif tx_type == 'EXC' and tx.to_amount and tx.to_currency:
                extra       = f"{float(tx.to_amount):,.2f} {tx.to_currency}"
                extra_class = 'positive'

            if tx_type == 'EXC':
                ledger.append({
                    'portfolio_name': portfolio.name,
                    'currency': tx.from_currency or tx_cur,
                    'commission_currency': tx.commission_currency or tx.from_currency or tx_cur,
                    'date':       tx_date,
                    'type':       'exc',
                    'label':      'Exchange',
                    'symbol':     f"{tx.from_currency}→{tx.to_currency}" if tx.from_currency and tx.to_currency else (tx.symbol or '—'),
                    'price':      None,
                    'quantity':   None,
                    'commission': commission,
                    'total':      float(tx.from_amount) if tx.from_amount else 0,
                    'extra':      extra,
                    'extra_class': extra_class,
                })
            else:
                ledger.append({
                    'portfolio_name': portfolio.name,
                    'currency': tx_cur,
                    'commission_currency': tx_cur,
                    'date':       tx_date,
                    'type':       tx_type.lower(),
                    'label':      TYPE_LABELS.get(tx_type, tx_type),
                    'symbol':     (tx.transaction_currency or '—') if is_cash else (tx.symbol or '—'),
                    'price':      None if is_cash else price,
                    'quantity':   None if is_cash else qty,
                    'commission': 0 if is_cash else commission,
                    'total':      price if is_cash else price * qty,
                    'extra':      extra,
                    'extra_class': extra_class,
                })

        for div in portfolio.dividends.all():
            pay_date_known = bool(div.payment_date)
            effective_date = div.payment_date or div.ex_dividend_date
            qty_d          = float(div.quantity) if div.quantity else None
            div_per_share  = round(float(div.amount) / qty_d, 4) if qty_d else None
            ledger.append({
                'portfolio_name': portfolio.name,
                'currency': '', 'commission_currency': '',
                'date':       effective_date,
                'date_estimated': not pay_date_known,
                'type':       'div',
                'label':      'Dividend',
                'symbol':     div.symbol,
                'price':      div_per_share,
                'quantity':   qty_d,
                'commission': 0,
                'total':      float(div.amount),
                'extra':      None,
                'extra_class': None,
            })

    ledger.sort(key=lambda x: x['date'] or date_type.min, reverse=True)

    summary = {
        'summary': {
            'current_value':            round(current_value_all, 2),
            'total_invested':           round(total_invested_all, 2),
            'total_gain_loss':          round(gain_loss_all, 2),
            'total_gain_loss_percentage': round(gain_loss_pct_all, 2),
            'annual_dividend_income':   round(annual_div_all, 2),
        },
        'positions': positions_detail,
        'metrics':   {'positions_count': len(positions_detail)},
        'price_as_of': min(stale_dates) if stale_dates else None,
    }

    return render(request, 'portfolio/portfolio_combined.html', {
        'summary':    summary,
        'ledger':     ledger,
        'portfolios': portfolios,
    })


@login_required
def tax_report_view(request, pk):
    """Frontend view: Annual tax report — stock P&L + FX P&L in native currency."""
    from .services import TaxReportService
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    available_years = TaxReportService.available_years(portfolio)
    current_year = date_type.today().year
    if not available_years:
        available_years = [current_year]

    try:
        year = int(request.GET.get('year', available_years[0]))
    except (ValueError, IndexError):
        year = current_year

    report = TaxReportService.calculate(portfolio, year)

    return render(request, 'portfolio/tax_report.html', {
        'portfolio': portfolio,
        'report': report,
        'available_years': available_years,
        'selected_year': year,
    })
