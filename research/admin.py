from django.contrib import admin
from .models import Stock, HistoricalPrice, Dividend, StockSplit, Watchlist, WatchlistItem


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'sector', 'industry', 'exchange', 'last_updated', 'is_active']
    list_filter = ['sector', 'industry', 'exchange', 'is_active']
    search_fields = ['symbol', 'name', 'sector', 'industry']
    readonly_fields = ['last_updated', 'created_at']
    ordering = ['symbol']


@admin.register(HistoricalPrice)
class HistoricalPriceAdmin(admin.ModelAdmin):
    list_display = ['stock', 'date', 'close', 'volume', 'created_at']
    list_filter = ['date', 'stock']
    search_fields = ['stock__symbol', 'stock__name']
    readonly_fields = ['created_at']
    ordering = ['-date']
    date_hierarchy = 'date'


@admin.register(Dividend)
class DividendAdmin(admin.ModelAdmin):
    list_display = ['stock', 'date', 'amount', 'created_at']
    list_filter = ['date', 'stock']
    search_fields = ['stock__symbol', 'stock__name']
    readonly_fields = ['created_at']
    ordering = ['-date']
    date_hierarchy = 'date'


@admin.register(StockSplit)
class StockSplitAdmin(admin.ModelAdmin):
    list_display = ['stock', 'date', 'ratio', 'split_from', 'split_to', 'created_at']
    list_filter = ['date', 'stock']
    search_fields = ['stock__symbol', 'stock__name']
    readonly_fields = ['created_at']
    ordering = ['-date']
    date_hierarchy = 'date'


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'created_at']
    list_filter = ['user', 'created_at']
    search_fields = ['name', 'user__username']
    readonly_fields = ['created_at']


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ['watchlist', 'symbol', 'added_at']
    list_filter = ['watchlist', 'added_at']
    search_fields = ['symbol', 'watchlist__name', 'notes']
    readonly_fields = ['added_at']

