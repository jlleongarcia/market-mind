"""
Portfolio calculation services
Handles complex portfolio analytics and calculations
"""
import logging
import requests
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.cache import cache
from django.db.models import Max, Min, Sum, Q
from research.models import FinancialMetrics, HistoricalPrice, Stock
from research.services import PriceCacheService

logger = logging.getLogger(__name__)


class FXRateService:
    """Fetch historical FX rates from the self-hosted Frankfurter v2 instance."""

    BASE_URL = getattr(settings, 'FX_RATE_SERVICE_URL', 'http://100.86.241.113:8301').rstrip('/')
    # How many prior business days to try when the requested date has no ECB data
    MAX_LOOKBACK_DAYS = 5

    @classmethod
    def get_rate(cls, from_currency: str, to_currency: str, on_date: date) -> tuple[Decimal | None, str]:
        """
        Return (rate, source) where rate is 1 from_currency = rate to_currency.
        source is 'frankfurter' or 'manual' (manual means caller must ask the user).
        Returns (None, 'unavailable') when no rate could be fetched.
        """
        if from_currency == to_currency:
            return Decimal('1'), 'same_currency'

        cache_key = f"fx_rate_{from_currency}_{to_currency}_{on_date.isoformat()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Decimal(str(cached)), 'frankfurter'

        candidate = on_date
        for _ in range(cls.MAX_LOOKBACK_DAYS + 1):
            rate = cls._fetch(from_currency, to_currency, candidate)
            if rate is not None:
                # Cache for 24 h — historical rates don't change
                cache.set(cache_key, str(rate), 86400)
                return rate, 'frankfurter'
            candidate = candidate - timedelta(days=1)

        return None, 'unavailable'

    @classmethod
    def _fetch(cls, from_currency: str, to_currency: str, on_date: date) -> Decimal | None:
        try:
            url = f"{cls.BASE_URL}/v2/rate/{from_currency}/{to_currency}"
            resp = requests.get(url, params={'date': on_date.isoformat()}, timeout=5)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return Decimal(str(data['rate']))
        except Exception as exc:
            logger.warning("FXRateService fetch failed (%s/%s %s): %s", from_currency, to_currency, on_date, exc)
            return None


class FXLotService:
    """
    Manage the per-portfolio FX book.

    The FX book tracks lots of foreign currency (real + virtual) and provides
    FIFO matching so that realised FX gains/losses can be computed for tax.

    Lot creation
    ─────────────
    • EXC transaction  → REAL lot in the purchased (to) currency
    • SELL profit/loss → VIRTUAL_SELL lot (positive balance = lot received;
                          negative balance = lot consumed via FIFO)
    • DIV / INT        → VIRTUAL_DIV / VIRTUAL_INT lot received

    Lot consumption (FIFO)
    ──────────────────────
    When foreign currency "leaves" the book (SELL loss consumes existing lots)
    we match oldest lots first, record FXLotConsumption entries and compute
    the realised FX gain/loss in native currency.
    """

    # Transaction types that generate FX events
    FX_TYPES = {'BUY', 'SELL', 'DIV', 'INT', 'EXC'}

    @staticmethod
    def process_transaction(transaction):
        """
        Entry point: analyse a saved Transaction and create/consume FX lots as needed.
        Safe to call multiple times — checks for existing lots first.
        """
        from portfolio.models import FXLot, FXLotConsumption

        tx_type = transaction.transaction_type
        portfolio = transaction.portfolio
        native = portfolio.native_currency
        tx_currency = transaction.transaction_currency

        if tx_type not in FXLotService.FX_TYPES:
            return
        if not tx_currency or tx_currency == native:
            return  # same currency — no FX event

        # Avoid duplicate processing
        if transaction.fx_lots.exists():
            return

        tx_date = transaction.transaction_date.date() if hasattr(transaction.transaction_date, 'date') else transaction.transaction_date

        if tx_type == 'EXC':
            FXLotService._process_exc(transaction, tx_date)
        elif tx_type == 'SELL':
            FXLotService._process_sell(transaction, tx_date)
        elif tx_type in ('DIV', 'INT'):
            FXLotService._process_income(transaction, tx_date)
        # BUY: no FX lot created — the funding EXC already handled it

    @staticmethod
    def _process_exc(transaction, tx_date):
        """Real currency exchange: create a lot in the purchased currency."""
        from portfolio.models import FXLot
        if not (transaction.to_currency and transaction.to_amount):
            return

        native      = transaction.portfolio.native_currency
        to_cur      = transaction.to_currency
        to_amt      = transaction.to_amount
        from_amt    = transaction.from_amount or Decimal('1')
        commission  = transaction.commission or Decimal('0')
        # Default commission currency to from_currency when not specified
        comm_cur    = transaction.commission_currency or transaction.from_currency

        if to_cur == native:
            fx_rate     = Decimal('1')
            native_cost = to_amt
        else:
            # Total native cost = what you spent (from_amount) + commission in native terms.
            if not comm_cur or comm_cur == transaction.from_currency:
                # Commission paid in the source currency — add directly.
                native_cost = from_amt + commission
            elif comm_cur == to_cur:
                # Commission deducted from the received side — convert to source currency
                # using the implied rate before the fee.
                implied_rate = from_amt / to_amt if to_amt else Decimal('0')
                native_cost  = from_amt + commission * implied_rate
            else:
                # Unknown commission currency — fall back to ignoring it.
                native_cost = from_amt

            fx_rate = native_cost / to_amt if to_amt else Decimal('1')

        FXLot.objects.create(
            portfolio=transaction.portfolio,
            currency=to_cur,
            source_transaction=transaction,
            lot_type='REAL',
            created_date=tx_date,
            original_amount_foreign=to_amt,
            remaining_amount_foreign=to_amt,
            fx_rate=fx_rate,
            original_amount_native=native_cost,
        )

    @staticmethod
    def _process_sell(transaction, tx_date):
        """
        Compute the 'balance' of this SELL vs FIFO cost basis.
        Positive balance → virtual lot received (profit).
        Negative balance → consume existing lots (loss).
        """
        from portfolio.models import FXLot, Transaction as Tx

        portfolio = transaction.portfolio
        symbol = transaction.symbol
        tx_currency = transaction.transaction_currency
        fx_rate = transaction.fx_rate or Decimal('1')

        # FIFO cost basis in stock-currency for the sold quantity
        fifo_cost = FXLotService._fifo_cost_basis_stock_currency(portfolio, symbol, transaction.quantity, tx_date)
        # Net proceeds: subtract sell commission so the virtual lot matches TaxReportService
        proceeds = transaction.quantity * transaction.price - (transaction.commission or Decimal('0'))

        balance = proceeds - fifo_cost  # positive = profit, negative = loss

        if balance == 0:
            return

        amount_abs = abs(balance)

        if balance > 0:
            # Profit: virtual lot received in stock-currency
            FXLot.objects.create(
                portfolio=portfolio,
                currency=tx_currency,
                source_transaction=transaction,
                lot_type='VIRTUAL_SELL',
                created_date=tx_date,
                original_amount_foreign=amount_abs,
                remaining_amount_foreign=amount_abs,
                fx_rate=fx_rate,
                original_amount_native=amount_abs * fx_rate,
            )
        else:
            # Loss: consume existing lots FIFO
            FXLotService._consume_fifo(portfolio, tx_currency, amount_abs, fx_rate, tx_date, transaction)

    @staticmethod
    def _process_income(transaction, tx_date):
        """DIV / INT: virtual lot received in the income currency."""
        from portfolio.models import FXLot

        amount = transaction.quantity * transaction.price
        fx_rate = transaction.fx_rate or Decimal('1')
        lot_type = 'VIRTUAL_DIV' if transaction.transaction_type == 'DIV' else 'VIRTUAL_INT'

        FXLot.objects.create(
            portfolio=transaction.portfolio,
            currency=transaction.transaction_currency,
            source_transaction=transaction,
            lot_type=lot_type,
            created_date=tx_date,
            original_amount_foreign=amount,
            remaining_amount_foreign=amount,
            fx_rate=fx_rate,
            original_amount_native=amount * fx_rate,
        )

    @staticmethod
    def _consume_fifo(portfolio, currency, amount_to_consume, fx_rate_now, on_date, consuming_tx):
        """
        Consume `amount_to_consume` units of `currency` from oldest open lots (FIFO).
        Creates FXLotConsumption records and calculates FX gain/loss.
        """
        from portfolio.models import FXLot, FXLotConsumption

        lots = FXLot.objects.filter(
            portfolio=portfolio,
            currency=currency,
            is_closed=False,
            remaining_amount_foreign__gt=0,
        ).order_by('created_date', 'id')

        remaining = Decimal(str(amount_to_consume))

        for lot in lots:
            if remaining <= 0:
                break

            to_take = min(lot.remaining_amount_foreign, remaining)
            cost_native = to_take * lot.fx_rate
            proceeds_native = to_take * fx_rate_now
            gain_loss = proceeds_native - cost_native

            FXLotConsumption.objects.create(
                lot=lot,
                consuming_transaction=consuming_tx,
                amount_foreign_consumed=to_take,
                fx_rate_at_consumption=fx_rate_now,
                fx_gain_loss_native=gain_loss,
                consumption_date=on_date,
            )

            lot.remaining_amount_foreign -= to_take
            if lot.remaining_amount_foreign <= 0:
                lot.is_closed = True
            lot.save(update_fields=['remaining_amount_foreign', 'is_closed'])
            remaining -= to_take

    @staticmethod
    def _fifo_cost_basis_stock_currency(portfolio, symbol, quantity_sold, as_of_date):
        """
        FIFO cost basis in stock-currency for `quantity_sold` shares sold on `as_of_date`.
        Walks BUY/SPOF transactions oldest-first to determine which lots are consumed.
        """
        from portfolio.models import Transaction as Tx

        buys = Tx.objects.filter(
            portfolio=portfolio,
            symbol=symbol,
            transaction_type__in=['BUY', 'SPOF'],
            transaction_date__date__lt=as_of_date,
        ).order_by('transaction_date')

        # Also consume prior SELLs to know remaining lots
        sells = Tx.objects.filter(
            portfolio=portfolio,
            symbol=symbol,
            transaction_type='SELL',
            transaction_date__date__lt=as_of_date,
        ).order_by('transaction_date')

        # Build list of remaining buy lots [(qty_remaining, effective_price_per_share)]
        # Effective price includes commission amortised over the purchased shares so
        # that the cost basis correctly reflects total acquisition cost.
        buy_lots = [
            [
                float(b.quantity),
                float(b.price) + (float(b.commission) / float(b.quantity) if b.quantity else 0),
            ]
            for b in buys
        ]
        sold_so_far = sum(float(s.quantity) for s in sells)

        # Consume prior sales from oldest lots
        for lot in buy_lots:
            if sold_so_far <= 0:
                break
            take = min(lot[0], sold_so_far)
            lot[0] -= take
            sold_so_far -= take

        # Now consume quantity_sold from remaining lots
        qty_to_consume = float(quantity_sold)
        cost = Decimal('0')
        for lot in buy_lots:
            if qty_to_consume <= 0:
                break
            take = min(lot[0], qty_to_consume)
            cost += Decimal(str(take)) * Decimal(str(lot[1]))
            qty_to_consume -= take

        return cost


class TaxReportService:
    """
    Compute annual tax report for a portfolio.

    Two separate P&L streams:
    1. Stock P&L   — realised gain/loss per sold position in native currency (FIFO lots)
    2. FX P&L      — realised FX gain/loss from FXLotConsumption records
    """

    @staticmethod
    def calculate(portfolio, year: int) -> dict:
        from portfolio.models import Transaction, FXLotConsumption

        native = portfolio.native_currency

        stock_events  = TaxReportService._stock_pnl(portfolio, year, native)
        fx_events     = TaxReportService._fx_pnl(portfolio, year)
        stock_total   = sum(e['gain_loss_native'] for e in stock_events)
        fx_total      = sum(e['gain_loss_native'] for e in fx_events)

        return {
            'year': year,
            'native_currency': native,
            'stock_events': stock_events,
            'stock_total': stock_total,
            'fx_events': fx_events,
            'fx_total': fx_total,
            'grand_total': stock_total + fx_total,
        }

    @staticmethod
    def _stock_pnl(portfolio, year, native):
        """
        For each SELL transaction in `year`, compute realised P&L in native currency.
        Cost basis uses FIFO in stock-currency, then converts via fx_rate at sell date.
        """
        from portfolio.models import Transaction

        sells = Transaction.objects.filter(
            portfolio=portfolio,
            transaction_type='SELL',
            transaction_date__year=year,
        ).order_by('transaction_date')

        events = []
        for sell in sells:
            fifo_cost_stock = FXLotService._fifo_cost_basis_stock_currency(
                portfolio, sell.symbol, sell.quantity,
                sell.transaction_date.date() if hasattr(sell.transaction_date, 'date') else sell.transaction_date
            )
            proceeds_stock = sell.quantity * sell.price - sell.commission
            gain_loss_stock = proceeds_stock - fifo_cost_stock

            # Convert to native
            fx = sell.fx_rate or Decimal('1')
            gain_loss_native = gain_loss_stock * fx

            events.append({
                'date': sell.transaction_date,
                'symbol': sell.symbol,
                'quantity': sell.quantity,
                'proceeds_stock': proceeds_stock,
                'cost_basis_stock': fifo_cost_stock,
                'gain_loss_stock': gain_loss_stock,
                'stock_currency': sell.transaction_currency or native,
                'fx_rate': fx,
                'gain_loss_native': gain_loss_native,
            })
        return events

    @staticmethod
    def _fx_pnl(portfolio, year):
        """Return list of FX consumption events for `year`."""
        from portfolio.models import FXLotConsumption

        consumptions = FXLotConsumption.objects.filter(
            lot__portfolio=portfolio,
            consumption_date__year=year,
        ).select_related('lot', 'consuming_transaction').order_by('consumption_date')

        events = []
        for c in consumptions:
            events.append({
                'date': c.consumption_date,
                'currency': c.lot.currency,
                'amount_foreign': c.amount_foreign_consumed,
                'cost_rate': c.lot.fx_rate,
                'sale_rate': c.fx_rate_at_consumption,
                'gain_loss_native': c.fx_gain_loss_native,
                'lot_type': c.lot.lot_type,
                'source_tx': c.consuming_transaction,
            })
        return events

    @staticmethod
    def available_years(portfolio) -> list[int]:
        from portfolio.models import Transaction
        years = (
            Transaction.objects.filter(portfolio=portfolio, transaction_type='SELL')
            .values_list('transaction_date__year', flat=True)
            .distinct()
            .order_by('-transaction_date__year')
        )
        return list(years)


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
            if metrics.dividend_rate and position_data['current_price']:
                position_data['current_yield'] = round(
                    (float(metrics.dividend_rate) / position_data['current_price']) * 100, 2
                )
            else:
                position_data['current_yield'] = None
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
            # Calculate new average cost including commission so that unrealized P&L
            # and yield figures reflect true acquisition cost.
            old_total_cost   = position.quantity * position.average_cost
            transaction_cost = transaction.quantity * transaction.price + transaction.commission
            new_quantity     = position.quantity + transaction.quantity

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
    def rebuild_position(portfolio, symbol):
        """Rebuild position for a symbol from scratch by replaying all BUY/SELL/SPOF transactions."""
        from portfolio.models import Position, Transaction

        Position.objects.filter(portfolio=portfolio, symbol=symbol).delete()

        transactions = Transaction.objects.filter(
            portfolio=portfolio,
            symbol=symbol,
            transaction_type__in=['BUY', 'SELL', 'SPOF'],
        ).order_by('transaction_date')

        for tx in transactions:
            PortfolioCalculationService.update_position_from_transaction(tx)

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
