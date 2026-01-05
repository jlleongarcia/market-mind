from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Stock(models.Model):
    """Core stock/company information"""
    symbol = models.CharField(max_length=10, primary_key=True, db_index=True)
    name = models.CharField(max_length=200)
    sector = models.CharField(max_length=100, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    exchange = models.CharField(max_length=50, blank=True, null=True)
    currency = models.CharField(max_length=10, default='USD')
    country = models.CharField(max_length=50, blank=True, null=True)
    
    # Metadata
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['symbol']
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['sector', 'industry']),
        ]
        
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class HistoricalPrice(models.Model):
    """Historical OHLCV price data"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='historical_prices')
    date = models.DateField(db_index=True)
    
    # OHLCV data
    open = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    high = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    low = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    close = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    volume = models.BigIntegerField(validators=[MinValueValidator(0)])
    adjusted_close = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['stock', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['stock', '-date']),
            models.Index(fields=['date']),
        ]
        
    def __str__(self):
        return f"{self.stock.symbol} - {self.date}"


class Dividend(models.Model):
    """Dividend payment history"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='dividends')
    date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['stock', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['stock', '-date']),
        ]
        
    def __str__(self):
        return f"{self.stock.symbol} - {self.date}: ${self.amount}"


class StockSplit(models.Model):
    """Stock split history"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='splits')
    date = models.DateField(db_index=True)
    ratio = models.CharField(max_length=20)  # e.g., "2:1", "3:2"
    split_from = models.IntegerField()  # e.g., 2 in "2:1"
    split_to = models.IntegerField()  # e.g., 1 in "2:1"
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['stock', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['stock', '-date']),
        ]
        
    def __str__(self):
        return f"{self.stock.symbol} - {self.date}: {self.ratio}"


class Watchlist(models.Model):
    """User's stock watchlist"""
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='watchlists')
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user.username} - {self.name}"


class WatchlistItem(models.Model):
    """Stocks in a watchlist"""
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE, related_name='items')
    symbol = models.CharField(max_length=10)
    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['watchlist', 'symbol']
        ordering = ['symbol']
        
    def __str__(self):
        return f"{self.watchlist.name} - {self.symbol}"
