"""
Serializers for Portfolio API
"""
from rest_framework import serializers
from .models import Portfolio, Transaction, Position, Dividend
from portfolio.services import PortfolioCalculationService


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for Transaction model"""
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'portfolio', 'symbol', 'transaction_type',
            'quantity', 'price', 'commission', 'tax', 'transaction_date',
            'broker', 'buy_yield', 'notes', 'created_at', 'total_amount'
        ]
        read_only_fields = ['id', 'created_at', 'total_amount']

    def create(self, validated_data):
        """Create transaction and update position"""
        transaction = Transaction.objects.create(**validated_data)

        # Update position based on transaction
        PortfolioCalculationService.update_position_from_transaction(transaction)

        # If it's a BUY transaction and buy_yield is not set, fetch it
        if transaction.transaction_type == 'BUY' and not transaction.buy_yield:
            PortfolioCalculationService.fetch_and_store_buy_yield(transaction)
        elif transaction.transaction_type == 'DIV':
            PortfolioCalculationService.fetch_and_store_transaction_tax(transaction)

        return transaction


class PositionSerializer(serializers.ModelSerializer):
    """Serializer for Position model"""
    company_name = serializers.SerializerMethodField()
    gain_loss = serializers.DecimalField(source='profit_loss', max_digits=15, decimal_places=2, read_only=True)
    gain_loss_percentage = serializers.DecimalField(source='profit_loss_percentage', max_digits=10, decimal_places=2, read_only=True)
    buy_yield = serializers.DecimalField(source='average_buy_yield', max_digits=5, decimal_places=2, read_only=True)
    yield_on_cost = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    annual_dividend_income = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    
    class Meta:
        model = Position
        fields = [
            'id', 'portfolio', 'symbol', 'company_name', 'quantity', 
            'average_cost', 'current_price', 'total_cost', 'current_value',
            'gain_loss', 'gain_loss_percentage', 'buy_yield', 'yield_on_cost',
            'annual_dividend_income', 'last_updated'
        ]
        read_only_fields = ['id', 'last_updated']
    
    def get_company_name(self, obj):
        """Get company name from research.Stock"""
        try:
            from research.models import Stock
            stock = Stock.objects.get(symbol=obj.symbol)
            return stock.name
        except:
            return obj.symbol


class PositionDetailSerializer(serializers.Serializer):
    """Detailed position serializer with financial metrics"""
    symbol = serializers.CharField()
    company_name = serializers.CharField()
    quantity = serializers.FloatField()
    average_cost = serializers.FloatField()
    current_price = serializers.FloatField()
    total_invested = serializers.FloatField()
    current_value = serializers.FloatField()
    gain_loss = serializers.FloatField()
    gain_loss_percentage = serializers.FloatField()
    buy_yield = serializers.FloatField(allow_null=True)
    current_yield = serializers.FloatField(allow_null=True)
    yield_on_cost = serializers.FloatField(allow_null=True)
    annual_dividend_income = serializers.FloatField(allow_null=True)
    pays_dividend = serializers.BooleanField()
    trailing_pe = serializers.FloatField(allow_null=True, required=False)
    forward_pe = serializers.FloatField(allow_null=True, required=False)
    payout_ratio = serializers.FloatField(allow_null=True, required=False)
    dividend_growth_1y = serializers.FloatField(allow_null=True, required=False)
    dividend_growth_5y = serializers.FloatField(allow_null=True, required=False)
    chowder_number = serializers.FloatField(allow_null=True, required=False)


class PortfolioMetricsSerializer(serializers.Serializer):
    """Portfolio-wide metrics"""
    positions_count = serializers.IntegerField()
    dividend_stocks_count = serializers.IntegerField()
    non_dividend_stocks_count = serializers.IntegerField()
    weighted_dividend_yield = serializers.FloatField()


class PortfolioSummaryDataSerializer(serializers.Serializer):
    """Summary data for portfolio"""
    total_invested = serializers.FloatField()
    current_value = serializers.FloatField()
    total_gain_loss = serializers.FloatField()
    total_gain_loss_percentage = serializers.FloatField()
    dividend_income_ytd = serializers.FloatField()
    annual_dividend_income = serializers.FloatField()
    average_yield_on_cost = serializers.FloatField()


class PortfolioSummarySerializer(serializers.Serializer):
    """Complete portfolio summary"""
    portfolio_id = serializers.IntegerField()
    portfolio_name = serializers.CharField()
    summary = PortfolioSummaryDataSerializer()
    positions = PositionDetailSerializer(many=True)
    metrics = PortfolioMetricsSerializer()


class PortfolioSerializer(serializers.ModelSerializer):
    """Basic Portfolio serializer"""
    total_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_invested = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_return = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_return_percentage = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    positions_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Portfolio
        fields = [
            'id', 'user', 'name', 'description', 'is_active',
            'total_value', 'total_invested', 'total_return', 'total_return_percentage',
            'positions_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
    
    def get_positions_count(self, obj):
        return obj.positions.count()


class DividendSerializer(serializers.ModelSerializer):
    """Serializer for Dividend model"""
    
    class Meta:
        model = Dividend
        fields = [
            'id', 'portfolio', 'symbol', 'amount', 'payment_date',
            'ex_dividend_date', 'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class BrokerSummarySerializer(serializers.Serializer):
    """Summary of holdings by broker"""
    broker = serializers.CharField()
    total_invested = serializers.FloatField()
    transactions_count = serializers.IntegerField()


class DividendIncomeHistorySerializer(serializers.Serializer):
    """Dividend income history"""
    year = serializers.IntegerField()
    monthly_income = serializers.ListField(
        child=serializers.DictField()
    )
    total = serializers.FloatField()
