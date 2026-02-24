"""
DRF Serializers for Research API
"""
from rest_framework import serializers
from .models import Stock, HistoricalPrice, Dividend, StockSplit, Watchlist, WatchlistItem, FinancialMetrics


class StockSerializer(serializers.ModelSerializer):
    """Serializer for Stock model"""
    
    class Meta:
        model = Stock
        fields = [
            'symbol', 'name', 'sector', 'industry', 
            'exchange', 'currency', 'country',
            'last_updated', 'created_at', 'is_active'
        ]
        read_only_fields = ['last_updated', 'created_at']


class HistoricalPriceSerializer(serializers.ModelSerializer):
    """Serializer for HistoricalPrice model"""
    symbol = serializers.CharField(source='stock.symbol', read_only=True)
    
    class Meta:
        model = HistoricalPrice
        fields = [
            'id', 'symbol', 'date', 
            'open', 'high', 'low', 'close', 
            'volume', 'adjusted_close', 'created_at'
        ]
        read_only_fields = ['created_at']


class DividendSerializer(serializers.ModelSerializer):
    """Serializer for Dividend model"""
    symbol = serializers.CharField(source='stock.symbol', read_only=True)
    
    class Meta:
        model = Dividend
        fields = ['id', 'symbol', 'date', 'amount', 'created_at']
        read_only_fields = ['created_at']


class StockSplitSerializer(serializers.ModelSerializer):
    """Serializer for StockSplit model"""
    symbol = serializers.CharField(source='stock.symbol', read_only=True)
    
    class Meta:
        model = StockSplit
        fields = [
            'id', 'symbol', 'date', 'ratio', 
            'split_from', 'split_to', 'created_at'
        ]
        read_only_fields = ['created_at']


class FinancialMetricsSerializer(serializers.ModelSerializer):
    """Serializer for FinancialMetrics model"""
    symbol = serializers.CharField(source='stock.symbol', read_only=True)
    
    class Meta:
        model = FinancialMetrics
        fields = [
            'symbol',
            'trailing_pe',
            'forward_pe',
            'payout_ratio',
            'fcf_payout_ratio',
            'dividend_yield',
            'dividend_growth_1y',
            'dividend_growth_5y',
            'chowder_number',
            'pays_dividend',
            'last_updated',
            'created_at'
        ]
        read_only_fields = ['last_updated', 'created_at']


class StockDetailSerializer(serializers.ModelSerializer):
    """Detailed stock serializer with related data counts"""
    price_count = serializers.IntegerField(
        source='historical_prices.count', 
        read_only=True
    )
    dividend_count = serializers.IntegerField(
        source='dividends.count', 
        read_only=True
    )
    split_count = serializers.IntegerField(
        source='splits.count', 
        read_only=True
    )
    latest_price = serializers.SerializerMethodField()
    financial_metrics = serializers.SerializerMethodField()
    
    class Meta:
        model = Stock
        fields = [
            'symbol', 'name', 'sector', 'industry', 
            'exchange', 'currency', 'country',
            'last_updated', 'created_at', 'is_active',
            'price_count', 'dividend_count', 'split_count',
            'latest_price', 'financial_metrics'
        ]
    
    def get_latest_price(self, obj):
        """Get the most recent price record"""
        latest = obj.historical_prices.first()
        if latest:
            return {
                'date': latest.date,
                'close': str(latest.close),
                'volume': latest.volume
            }
        return None
    
    def get_financial_metrics(self, obj):
        """Get financial metrics for the stock"""
        try:
            if hasattr(obj, 'financial_metrics'):
                return FinancialMetricsSerializer(obj.financial_metrics).data
        except FinancialMetrics.DoesNotExist:
            pass
        return None


class WatchlistItemSerializer(serializers.ModelSerializer):
    """Serializer for WatchlistItem"""
    
    class Meta:
        model = WatchlistItem
        fields = ['id', 'symbol', 'added_at', 'notes']
        read_only_fields = ['added_at']


class WatchlistSerializer(serializers.ModelSerializer):
    """Serializer for Watchlist"""
    items = WatchlistItemSerializer(many=True, read_only=True)
    item_count = serializers.IntegerField(
        source='items.count',
        read_only=True
    )
    
    class Meta:
        model = Watchlist
        fields = ['id', 'name', 'created_at', 'items', 'item_count']
        read_only_fields = ['created_at']
