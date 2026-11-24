"""
Wishlist + rule-based alerts.

Uses plain symbol CharFields rather than FKs to research.Stock, matching the
loose-coupling convention of the portfolio app.
"""
from django.contrib.auth.models import User
from django.db import models


class WishlistItem(models.Model):
    """A company the user is watching but doesn't necessarily own."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    symbol = models.CharField(max_length=10)
    note = models.TextField(blank=True, help_text="Why you want this company — quoted back in its alerts")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'symbol']
        ordering = ['symbol']

    def __str__(self):
        return f"{self.user.username} — {self.symbol}"


class AlertRule(models.Model):
    """
    A user-defined trigger: a set of conditions combined with ALL/ANY,
    evaluated daily against every symbol in its scope.
    """
    SCOPE_CHOICES = [
        ('BOTH', 'Wishlist + portfolio'),
        ('WISHLIST', 'Wishlist only'),
        ('PORTFOLIO', 'Portfolio only'),
        ('SYMBOL', 'A single symbol'),
    ]
    MATCH_CHOICES = [
        ('ALL', 'All conditions'),
        ('ANY', 'Any condition'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alert_rules')
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default='BOTH')
    symbol = models.CharField(max_length=10, blank=True, help_text="Only used when scope is SYMBOL")
    match = models.CharField(max_length=3, choices=MATCH_CHOICES, default='ALL')
    is_active = models.BooleanField(default=True)
    cooldown_days = models.PositiveIntegerField(
        default=7,
        help_text="After firing for a symbol, don't fire again for it within this many days "
                  "even if the conditions flip off and back on",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.user.username} — {self.name}"


class AlertCondition(models.Model):
    """One `metric operator value` comparison. Metric keys are defined in alerts.metrics.METRICS."""
    OPERATOR_CHOICES = [
        ('lt', '<'),
        ('lte', '≤'),
        ('gt', '>'),
        ('gte', '≥'),
    ]

    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='conditions')
    metric = models.CharField(max_length=30)
    operator = models.CharField(max_length=3, choices=OPERATOR_CHOICES)
    value = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.metric} {self.get_operator_display()} {self.value_display}"

    @property
    def value_display(self):
        return f"{float(self.value):g}"


class AlertState(models.Model):
    """
    Whether a trigger currently holds for a symbol — lets alerts fire only on
    the false → true transition instead of every day the condition stays true.

    `key` is "rule:<id>" for user rules (rule FK also set, so deleting the rule
    cascades) or "warn:<kind>" for built-in threshold warnings (rule null).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alert_states')
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, null=True, blank=True, related_name='states')
    key = models.CharField(max_length=40)
    symbol = models.CharField(max_length=10)
    is_matching = models.BooleanField(default=False)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'key', 'symbol']


class AlertEvent(models.Model):
    """A fired alert — the History page, and the content of each day's digest."""
    KIND_CHOICES = [
        ('RULE', 'Rule matched'),
        ('DIVIDEND_CUT', 'Dividend cut'),
        ('DIVIDEND_FREEZE', 'Dividend freeze'),
        ('PAYOUT_HIGH', 'Payout ratio above 100%'),
        ('FCF_PAYOUT_HIGH', 'FCF payout above 100%'),
        ('EX_DIVIDEND', 'Ex-dividend date approaching'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alert_events')
    rule = models.ForeignKey(AlertRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    rule_name = models.CharField(max_length=100, blank=True, help_text="Kept so history survives rule deletion")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    symbol = models.CharField(max_length=10)
    # Identifies one-off events (a specific dividend cut, freeze streak or
    # ex-date) so each is only ever reported once.
    event_key = models.CharField(max_length=60, blank=True)
    message = models.TextField()
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    emailed = models.BooleanField(default=False)
    telegrammed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'kind', 'symbol', 'event_key']),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.get_kind_display()} — {self.symbol}"


class NotificationSettings(models.Model):
    """Per-user delivery channels and built-in warning toggles."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_settings')

    email_enabled = models.BooleanField(default=True)
    telegram_enabled = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    telegram_link_token = models.CharField(max_length=64, blank=True)

    warn_dividend_cut = models.BooleanField(default=True)
    warn_dividend_freeze = models.BooleanField(default=True)
    warn_payout = models.BooleanField(default=True, help_text="Payout or FCF payout above 100%")
    warn_ex_dividend = models.BooleanField(default=False)
    ex_dividend_days = models.PositiveSmallIntegerField(default=7)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} — notification settings"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
