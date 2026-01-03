from django.db import models
from django.contrib.auth.models import User


class Portfolio(models.Model):
    """User's investment portfolio"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user.username} - {self.name}"
    
    @property
    def total_value(self):
        """Calculate total portfolio value"""
        return sum(position.current_value for position in self.positions.all())
    
    @property
    def total_invested(self):
        """Calculate total amount invested"""
        return sum(position.total_cost for position in self.positions.all())
    
    @property
    def total_return(self):
        """Calculate total return (profit/loss)"""
        return self.total_value - self.total_invested


class Transaction(models.Model):
    """Stock buy/sell transactions"""
    TRANSACTION_TYPES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]
    
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='transactions')
    symbol = models.CharField(max_length=10)
    transaction_type = models.CharField(max_length=4, choices=TRANSACTION_TYPES)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    price = models.DecimalField(max_digits=15, decimal_places=4)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transaction_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        
    def __str__(self):
        return f"{self.transaction_type} {self.quantity} {self.symbol} @ ${self.price}"
    
    @property
    def total_amount(self):
        """Total transaction amount including commission"""
        base_amount = self.quantity * self.price
        if self.transaction_type == 'BUY':
            return base_amount + self.commission
        return base_amount - self.commission


class Position(models.Model):
    """Current stock positions in portfolio"""
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='positions')
    symbol = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    average_cost = models.DecimalField(max_digits=15, decimal_places=4)
    current_price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['portfolio', 'symbol']
        ordering = ['symbol']
        
    def __str__(self):
        return f"{self.symbol} - {self.quantity} shares"
    
    @property
    def total_cost(self):
        """Total cost basis"""
        return self.quantity * self.average_cost
    
    @property
    def current_value(self):
        """Current market value"""
        if self.current_price:
            return self.quantity * self.current_price
        return self.total_cost
    
    @property
    def profit_loss(self):
        """Unrealized profit or loss"""
        return self.current_value - self.total_cost
    
    @property
    def profit_loss_percentage(self):
        """Profit/loss as percentage"""
        if self.total_cost > 0:
            return (self.profit_loss / self.total_cost) * 100
        return 0


class Dividend(models.Model):
    """Dividend payments received"""
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='dividends')
    symbol = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    ex_dividend_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-payment_date']
        
    def __str__(self):
        return f"{self.symbol} - ${self.amount} on {self.payment_date}"
