from django.contrib import admin

from .models import AlertCondition, AlertEvent, AlertRule, NotificationSettings, WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ['user', 'symbol', 'added_at']
    list_filter = ['user']
    search_fields = ['symbol']


class AlertConditionInline(admin.TabularInline):
    model = AlertCondition
    extra = 0


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'scope', 'match', 'is_active', 'cooldown_days']
    list_filter = ['user', 'is_active', 'scope']
    inlines = [AlertConditionInline]


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'kind', 'symbol', 'rule_name', 'emailed', 'telegrammed']
    list_filter = ['user', 'kind', 'emailed', 'telegrammed']
    search_fields = ['symbol', 'message']


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'email_enabled', 'telegram_enabled']
    exclude = ['telegram_link_token']
