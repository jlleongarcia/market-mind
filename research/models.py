from django.db import models


class StockCache(models.Model):
    """Cache for stock data to reduce API calls"""
    symbol = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=200)
    current_price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    market_cap = models.BigIntegerField(null=True, blank=True)
    pe_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dividend_yield = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    week_52_high = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    week_52_low = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['symbol']
        
    def __str__(self):
        return f"{self.symbol} - {self.name}"


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
