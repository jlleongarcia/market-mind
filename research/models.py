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

    open = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    high = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    low = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    close = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    volume = models.BigIntegerField(validators=[MinValueValidator(0)])
    adjusted_close = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)

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
    date = models.DateField(db_index=True)         # ex-dividend date (authoritative)
    payment_date = models.DateField(null=True, blank=True)  # actual payment date — null for historical records
    declaration_date = models.DateField(null=True, blank=True)  # when the dividend was announced — null for historical records
    # True once Alpha Vantage has responded for this exact ex-date and confirmed it has no
    # declaration_date to give (as opposed to declaration_date simply not having been fetched
    # yet) — lets backfill stop re-querying rows AV will never be able to fill.
    declaration_date_checked = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])

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
    ratio = models.CharField(max_length=20)
    split_from = models.IntegerField()
    split_to = models.IntegerField()

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

    trailing_pe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    forward_pe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payout_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    fcf_payout_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    dividend_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="Annual dividend per share in the stock's native currency (e.g. 3.32 for MSFT)")
    dividend_yield = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    dividend_growth_1y = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dividend_growth_5y = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    chowder_number = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    beta = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    pays_dividend = models.BooleanField(default=False)

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
        if not self.pays_dividend:
            return False
        return all([
            self.dividend_rate is not None,
            self.dividend_yield is not None,
            self.dividend_growth_1y is not None,
            self.dividend_growth_5y is not None,
            self.chowder_number is not None,
        ])

    @property
    def has_cash_flow_data(self):
        return self.fcf_payout_ratio is not None


class UserRegistrationRequest(models.Model):
    """Pending user registration requests — used by the Google OAuth approval flow."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    REGISTRATION_TYPE_CHOICES = [
        ('manual', 'Manual Registration'),
        ('google', 'Google Registration'),
    ]

    username = models.CharField(max_length=150)
    email = models.EmailField()
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=150)
    password_hash = models.CharField(max_length=128, null=True, blank=True)

    registration_type = models.CharField(max_length=20, choices=REGISTRATION_TYPE_CHOICES, default='manual')
    google_id = models.CharField(max_length=255, null=True, blank=True)
    google_picture = models.URLField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    request_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Registration Request"
        verbose_name_plural = "Registration Requests"
        ordering = ['-request_date']

    def __str__(self):
        return f"{self.username} ({self.first_name} {self.last_name}) - {self.get_status_display()}"

    def approve(self, admin_user, notes=""):
        from django.contrib.auth.hashers import make_password
        from django.utils import timezone

        if self.status != 'pending':
            raise ValueError("Only pending requests can be approved")
        if User.objects.filter(username=self.username).exists():
            raise ValueError("Username already exists")

        if self.registration_type == 'google':
            import secrets
            user = User.objects.create(
                username=self.username,
                email=self.email,
                first_name=self.first_name,
                last_name=self.last_name,
                password=make_password(secrets.token_urlsafe(32)),
                is_active=True,
            )
            self._create_social_account(user)
        else:
            user = User.objects.create(
                username=self.username,
                email=self.email,
                first_name=self.first_name,
                last_name=self.last_name,
                password=self.password_hash,
                is_active=True,
            )

        self.status = 'approved'
        self.processed_date = timezone.now()
        self.processed_by = admin_user
        self.notes = notes
        self.save()
        self._send_approval_email()
        return user

    def _create_social_account(self, user):
        if self.registration_type == 'google' and self.google_id:
            from allauth.socialaccount.models import SocialAccount, SocialApp
            try:
                SocialApp.objects.get(provider='google')
                SocialAccount.objects.create(
                    user=user,
                    provider='google',
                    uid=self.google_id,
                    extra_data={
                        'picture': self.google_picture,
                        'name': f"{self.first_name} {self.last_name}",
                        'email': self.email,
                    },
                )
            except SocialApp.DoesNotExist:
                pass

    def reject(self, admin_user, notes=""):
        from django.utils import timezone
        if self.status != 'pending':
            raise ValueError("Only pending requests can be rejected")
        self.status = 'rejected'
        self.processed_date = timezone.now()
        self.processed_by = admin_user
        self.notes = notes
        self.save()
        self._send_rejection_email(notes)

    def _get_login_url(self):
        from django.conf import settings
        import re
        allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
        domain = 'localhost:8000'
        for host in allowed_hosts:
            if host not in ['*', 'localhost', '127.0.0.1', '0.0.0.0']:
                if re.search(r'[a-zA-Z]', host):
                    domain = host
                    break
        protocol = "https" if domain != 'localhost:8000' else "http"
        return f"{protocol}://{domain}{settings.LOGIN_URL}"

    def _send_approval_email(self):
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            login_url = self._get_login_url()
            credentials_info = (
                "You can now access the system using your Google account."
                if self.registration_type == 'google'
                else f"Username: {self.username}\nPassword: The one you provided when registering"
            )
            send_mail(
                subject='[Market Mind] Your request has been approved!',
                message=f"Hello {self.first_name},\n\nYour registration has been approved.\n\n{credentials_info}\n\nSign in: {login_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.email],
                fail_silently=True,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Approval email error: {e}")

    def _send_rejection_email(self, notes=""):
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                subject='[Market Mind] Registration request not approved',
                message=(
                    f"Hello {self.first_name},\n\n"
                    f"Your registration request was not approved at this time.\n"
                    f"{f'Reason: {notes}' if notes else ''}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.email],
                fail_silently=True,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Rejection email error: {e}")
