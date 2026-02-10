from django.db import models
from django.contrib.auth.models import User
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


class FinancialMetrics(models.Model):
    """Financial metrics and ratios for stocks"""
    stock = models.OneToOneField(Stock, on_delete=models.CASCADE, related_name='financial_metrics', primary_key=True)
    
    # P/E Ratios (from yfinance)
    trailing_pe = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Trailing 12-month Price-to-Earnings ratio"
    )
    forward_pe = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Forward Price-to-Earnings ratio"
    )
    
    # Dividend metrics (from yfinance)
    payout_ratio = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Dividend payout ratio as percentage (0-100)"
    )
    dividend_yield = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Current dividend yield as percentage"
    )
    
    # Computed dividend growth (from historical data)
    dividend_growth_1y = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="1-year dividend growth rate as percentage"
    )
    dividend_growth_5y = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="5-year dividend growth CAGR as percentage"
    )
    
    # Chowder Number (computed)
    chowder_number = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Chowder Number: Dividend Yield + 5Y Dividend Growth"
    )
    
    # Additional useful metrics
    pays_dividend = models.BooleanField(
        default=False,
        help_text="Whether the stock pays dividends"
    )
    
    # Metadata
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Financial Metrics"
        verbose_name_plural = "Financial Metrics"
        indexes = [
            models.Index(fields=['pays_dividend']),
            models.Index(fields=['last_updated']),
        ]
        
    def __str__(self):
        return f"{self.stock.symbol} - Financial Metrics"
    
    @property
    def has_complete_dividend_data(self):
        """Check if all dividend metrics are available"""
        if not self.pays_dividend:
            return False
        return all([
            self.dividend_yield is not None,
            self.dividend_growth_1y is not None,
            self.dividend_growth_5y is not None,
            self.chowder_number is not None
        ])


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


class UserRegistrationRequest(models.Model):
    """Model to store user registration requests pending approval"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    REGISTRATION_TYPE_CHOICES = [
        ('manual', 'Manual Registration'),
        ('google', 'Google Registration'),
    ]
    
    username = models.CharField(
        max_length=150,
        verbose_name="Username",
        help_text="Unique username for the new user"
    )
    email = models.EmailField(
        verbose_name="Email",
        help_text="Email address of the applicant"
    )
    first_name = models.CharField(
        max_length=30,
        verbose_name="First Name",
        help_text="First name of the applicant"
    )
    last_name = models.CharField(
        max_length=150,
        verbose_name="Last Name",
        help_text="Last name of the applicant"
    )
    password_hash = models.CharField(
        max_length=128,
        verbose_name="Password Hash",
        help_text="Hash of the user's password",
        null=True,
        blank=True  # For Google accounts we don't need password
    )
    
    # New fields to handle social accounts
    registration_type = models.CharField(
        max_length=20,
        choices=REGISTRATION_TYPE_CHOICES,
        default='manual',
        verbose_name="Registration Type",
        help_text="Method used for registration"
    )
    google_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Google ID",
        help_text="User's unique Google ID"
    )
    google_picture = models.URLField(
        null=True,
        blank=True,
        verbose_name="Google Picture",
        help_text="URL of the Google profile picture"
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Status",
        help_text="Current status of the request"
    )
    
    request_date = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Request Date",
        help_text="Date and time of the request"
    )
    processed_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Processed Date",
        help_text="Date and time of approval/rejection"
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Processed By",
        help_text="Administrator who processed the request"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Notes",
        help_text="Additional administrator notes"
    )
    
    class Meta:
        verbose_name = "Registration Request"
        verbose_name_plural = "Registration Requests"
        ordering = ['-request_date']
    
    def __str__(self):
        return f"{self.username} ({self.first_name} {self.last_name}) - {self.get_status_display()}"
    
    def approve(self, admin_user, notes=""):
        """Approve the request and create the user"""
        from django.contrib.auth.hashers import make_password
        from django.utils import timezone
        
        if self.status != 'pending':
            raise ValueError("Only pending requests can be approved")
        
        # Check that username doesn't exist
        if User.objects.filter(username=self.username).exists():
            raise ValueError("Username already exists")
        
        # Create user with configuration based on registration type
        if self.registration_type == 'google':
            # For Google accounts, generate random password (won't be used)
            import secrets
            random_password = secrets.token_urlsafe(32)
            user = User.objects.create(
                username=self.username,
                email=self.email,
                first_name=self.first_name,
                last_name=self.last_name,
                password=make_password(random_password),
                is_active=True
            )
            
            # Create the linked social account
            self._create_social_account(user)
        else:
            # For manual accounts, use provided password
            user = User.objects.create(
                username=self.username,
                email=self.email,
                first_name=self.first_name,
                last_name=self.last_name,
                password=self.password_hash,  # Already hashed
                is_active=True
            )
        
        # Update the request
        self.status = 'approved'
        self.processed_date = timezone.now()
        self.processed_by = admin_user
        self.notes = notes
        self.save()
        
        # Send approval email notification
        self._send_approval_email()
        
        return user
    
    def _create_social_account(self, user):
        """Create the linked social account for Google users"""
        if self.registration_type == 'google' and self.google_id:
            from allauth.socialaccount.models import SocialAccount, SocialApp
            
            try:
                # Find the Google social app
                google_app = SocialApp.objects.get(provider='google')
                
                # Create the social account
                social_account = SocialAccount.objects.create(
                    user=user,
                    provider='google',
                    uid=self.google_id,
                    extra_data={
                        'picture': self.google_picture,
                        'name': f"{self.first_name} {self.last_name}",
                        'email': self.email,
                    }
                )
                social_account.save()
                
            except SocialApp.DoesNotExist:
                # If Google app not configured, continue without creating social account
                pass
    
    def reject(self, admin_user, notes=""):
        """Reject the request"""
        from django.utils import timezone
        
        if self.status != 'pending':
            raise ValueError("Only pending requests can be rejected")
        
        self.status = 'rejected'
        self.processed_date = timezone.now()
        self.processed_by = admin_user
        self.notes = notes
        self.save()
        
        # Send rejection email notification
        self._send_rejection_email(notes)
    
    def _get_login_url(self):
        """Get login URL with correct main domain"""
        from django.conf import settings
        import re
        
        allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
        domain = 'localhost:8000'  # fallback
        
        # Look for real domains first (containing letters, not just IP)
        for host in allowed_hosts:
            if host not in ['*', 'localhost', '127.0.0.1', '0.0.0.0']:
                # Check that it's not an IP (contains letters, not just numbers and dots)
                if re.search(r'[a-zA-Z]', host):
                    domain = host
                    break
        
        # If no domain with letters found, use any non-excluded host
        if domain == 'localhost:8000':
            for host in allowed_hosts:
                if host not in ['*', 'localhost', '127.0.0.1', '0.0.0.0']:
                    domain = host
                    break
        
        # Build complete URL
        protocol = "https" if domain != 'localhost:8000' else "http"
        return f"{protocol}://{domain}{settings.LOGIN_URL}"
    
    def _send_approval_email(self):
        """Send email notification when request is approved"""
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            import logging
            
            logger = logging.getLogger(__name__)
            
            # Get login URL with correct domain
            login_url = self._get_login_url()
            
            # Different message based on registration type
            if self.registration_type == 'google':
                credentials_info = "You can now access the system using your Google account ('Sign in with Google' button)."
            else:
                credentials_info = f"""You can now access the system with your credentials:
- Username: {self.username}
- Password: The one you provided when registering"""
            
            subject = '[Py-Stocks] Your request has been approved!'
            message = f"""
Hello {self.first_name},

Great news! Your registration request for Py-Stocks has been approved.

{credentials_info}

Access the system:
🔗 Sign in: {login_url}

Welcome to Py-Stocks!

Best regards,
The Py-Stocks Team
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.email],
                fail_silently=False,
            )
            logger.info(f"Approval email sent successfully to {self.email}")
            
        except Exception as e:
            # Log error but don't fail the approval
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error sending approval email to {self.email}: {str(e)}")
            print(f"Error sending approval email to {self.email}: {str(e)}")
    
    def _send_rejection_email(self, notes=""):
        """Send email notification when request is rejected"""
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            import logging
            
            logger = logging.getLogger(__name__)
            
            subject = '[Py-Stocks] Registration request not approved'
            message = f"""
Hello {self.first_name},

We regret to inform you that your registration request for Py-Stocks has not been approved at this time.

Request details:
- Requested username: {self.username}
- Email: {self.email}
- Request date: {self.request_date.strftime('%m/%d/%Y %H:%M')}

{f"Reason: {notes}" if notes else ""}

If you have questions about this decision, you can contact the administrator.

Best regards,
The Py-Stocks Team
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.email],
                fail_silently=False,
            )
            logger.info(f"Rejection email sent successfully to {self.email}")
            
        except Exception as e:
            # Log error but don't fail the rejection
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error sending rejection email to {self.email}: {str(e)}")
            print(f"Error sending rejection email to {self.email}: {str(e)}")
