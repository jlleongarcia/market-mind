from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.contrib.admin import AdminSite
from copy import deepcopy
from .models import Stock, HistoricalPrice, Dividend, StockSplit, Watchlist, WatchlistItem, UserRegistrationRequest


class CustomAdminSite(AdminSite):
    def get_app_list(self, request, app_label=None):
        """
        Reorganize the app list to show UserRegistrationRequest
        in the Authentication and Authorization section
        """
        app_list = super().get_app_list(request, app_label)
        
        # Find UserRegistrationRequest in Research and move it to Auth
        user_reg_model = None
        
        for app in app_list:
            if app['app_label'] == 'research':
                models_to_keep = []
                for model in app['models']:
                    if model['object_name'] == 'UserRegistrationRequest':
                        user_reg_model = deepcopy(model)
                    else:
                        models_to_keep.append(model)
                app['models'] = models_to_keep
        
        # Add UserRegistrationRequest to Auth if found
        if user_reg_model:
            for app in app_list:
                if app['app_label'] == 'auth':
                    app['models'].append(user_reg_model)
                    break
        
        return app_list


# Use the custom AdminSite
admin.site.__class__ = CustomAdminSite


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


@admin.register(UserRegistrationRequest)
class UserRegistrationRequestAdmin(admin.ModelAdmin):
    """Administration for user registration requests"""
    
    list_display = [
        'username', 
        'first_name', 
        'last_name', 
        'email', 
        'registration_type',
        'status', 
        'request_date',
        'processed_by'
    ]
    
    list_filter = [
        'status', 
        'registration_type',
        'request_date',
        'processed_date'
    ]
    
    search_fields = [
        'username', 
        'email', 
        'first_name', 
        'last_name'
    ]
    
    readonly_fields = [
        'password_hash', 
        'registration_type',
        'google_id',
        'google_picture',
        'request_date', 
        'processed_date'
    ]
    
    fieldsets = (
        ('User Information', {
            'fields': ('username', 'email', 'first_name', 'last_name', 'registration_type')
        }),
        ('Status', {
            'fields': ('status', 'notes')
        }),
        ('Google Information', {
            'fields': ('google_id', 'google_picture'),
            'classes': ('collapse',)
        }),
        ('Technical Information', {
            'fields': ('password_hash',),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('request_date', 'processed_date', 'processed_by'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['approve_requests', 'reject_requests']
    
    def approve_requests(self, request, queryset):
        """Action to approve selected requests"""
        approved = 0
        errors = []
        
        for solicitud in queryset.filter(status='pending'):
            try:
                user = solicitud.approve(request.user, "Approved from admin panel")
                approved += 1
                self.message_user(
                    request, 
                    f"User '{user.username}' created successfully.",
                    level='success'
                )
            except ValueError as e:
                errors.append(f"Error with {solicitud.username}: {str(e)}")
        
        if approved > 0:
            self.message_user(
                request,
                f"{approved} request(s) approved successfully.",
                level='success'
            )
        
        for error in errors:
            self.message_user(request, error, level='error')
    
    approve_requests.short_description = "Approve selected requests"
    
    def reject_requests(self, request, queryset):
        """Action to reject selected requests"""
        rejected = 0
        
        for solicitud in queryset.filter(status='pending'):
            try:
                solicitud.reject(request.user, "Rejected from admin panel")
                rejected += 1
            except ValueError as e:
                self.message_user(request, f"Error: {str(e)}", level='error')
        
        if rejected > 0:
            self.message_user(
                request,
                f"{rejected} request(s) rejected.",
                level='warning'
            )
    
    reject_requests.short_description = "Reject selected requests"
    
    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related('processed_by')
    
    def has_add_permission(self, request):
        """Don't allow adding requests from admin (only from form)"""
        return False

