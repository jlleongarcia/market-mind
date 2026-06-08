from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """Extended user profile with additional security settings"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    force_password_change = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile for {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Automatically create profile when user is created"""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save profile when user is saved"""
    if hasattr(instance, 'profile'):
        instance.profile.save()


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
    
    @property
    def total_return_percentage(self):
        """Calculate total return as percentage"""
        if self.total_invested > 0:
            return (self.total_return / self.total_invested) * 100
        return 0
    
    @property
    def total_dividend_income(self):
        """Calculate total dividend income from all dividends"""
        return sum(float(div.amount) for div in self.dividends.all())
    
    @property
    def annual_dividend_income(self):
        """Estimated annual dividend income from all positions"""
        total = 0
        for position in self.positions.all():
            income = position.annual_dividend_income
            if income:
                total += income
        return round(total, 2) if total > 0 else 0
    
    @property
    def dividend_positions_count(self):
        """Count positions that pay dividends"""
        count = 0
        for position in self.positions.all():
            metrics = position.get_current_metrics()
            if metrics and metrics.pays_dividend:
                count += 1
        return count
    
    @property
    def weighted_dividend_yield(self):
        """Calculate portfolio-wide weighted dividend yield"""
        total_value = 0
        weighted_yield_sum = 0
        
        for position in self.positions.all():
            metrics = position.get_current_metrics()
            if metrics and metrics.pays_dividend and metrics.dividend_yield:
                position_value = float(position.current_value)
                total_value += position_value
                weighted_yield_sum += position_value * float(metrics.dividend_yield)
        
        if total_value > 0:
            return round(weighted_yield_sum / total_value, 2)
        return 0


class Transaction(models.Model):
    """Stock buy/sell transactions"""
    TRANSACTION_TYPES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
        ('DIV', 'Dividend'),
        ('SPOF', 'Spin-Off'),
        ('INT', 'Interest'),
        ('DEP', 'Deposit'),
        ('WIT', 'Withdrawal'),
        ('EXC', 'Exchange'),
    ]

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='transactions')
    symbol = models.CharField(max_length=10, blank=True)
    transaction_type = models.CharField(max_length=8, choices=TRANSACTION_TYPES)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    price = models.DecimalField(max_digits=15, decimal_places=4)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transaction_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    
    # New fields for Portfolio API
    broker = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        help_text="Broker used for this transaction (e.g., 'Robinhood', 'Fidelity')"
    )
    buy_yield = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Dividend yield at time of purchase (as percentage)"
    )
    
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
    
    def get_current_metrics(self):
        """Get current financial metrics from research app"""
        try:
            from research.models import FinancialMetrics
            return FinancialMetrics.objects.select_related('stock').get(stock__symbol=self.symbol)
        except:
            return None


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
    
    def get_current_metrics(self):
        """Get current financial metrics from research app"""
        try:
            from research.models import FinancialMetrics
            return FinancialMetrics.objects.select_related('stock').get(stock__symbol=self.symbol)
        except:
            return None
    
    def get_transactions(self):
        """Get all transactions for this position"""
        return self.portfolio.transactions.filter(symbol=self.symbol).order_by('transaction_date')
    
    @property
    def average_buy_yield(self):
        """Calculate weighted average buy yield from transactions"""
        buy_transactions = self.portfolio.transactions.filter(
            symbol=self.symbol,
            transaction_type='BUY',
            buy_yield__isnull=False
        )
        
        if not buy_transactions.exists():
            return None
        
        total_weighted_yield = sum(
            float(t.buy_yield) * float(t.quantity) * float(t.price)
            for t in buy_transactions
        )
        total_investment = sum(
            float(t.quantity) * float(t.price)
            for t in buy_transactions
        )
        
        if total_investment > 0:
            return round(total_weighted_yield / total_investment, 2)
        return None
    
    @property
    def yield_on_cost(self):
        """Calculate Yield on Cost (YoC) - current dividend income vs. original investment"""
        metrics = self.get_current_metrics()
        if not metrics or not metrics.pays_dividend or not metrics.dividend_yield:
            return None
        
        # Get current stock price (use current_price if available, else average_cost)
        current_stock_price = float(self.current_price) if self.current_price else float(self.average_cost)
        
        # Calculate annual dividend per share
        annual_dividend_per_share = (float(metrics.dividend_yield) / 100) * current_stock_price
        
        # Calculate total annual dividend income
        total_annual_dividend = annual_dividend_per_share * float(self.quantity)
        
        # Calculate YoC: (Annual Dividend Income / Total Cost) * 100
        if float(self.total_cost) > 0:
            yoc = (total_annual_dividend / float(self.total_cost)) * 100
            return round(yoc, 2)
        return None
    
    @property
    def annual_dividend_income(self):
        """Estimated annual dividend income from this position"""
        metrics = self.get_current_metrics()
        if not metrics or not metrics.pays_dividend or not metrics.dividend_yield:
            return None
        
        current_stock_price = float(self.current_price) if self.current_price else float(self.average_cost)
        annual_dividend_per_share = (float(metrics.dividend_yield) / 100) * current_stock_price
        total_annual_dividend = annual_dividend_per_share * float(self.quantity)
        
        return round(total_annual_dividend, 2)


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
