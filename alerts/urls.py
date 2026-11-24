from django.urls import path

from . import views

app_name = 'alerts'

urlpatterns = [
    path('', views.wishlist_view, name='wishlist_view'),
    path('rules/', views.rules_view, name='rules_view'),
    path('rules/new/', views.rule_edit_view, name='rule_create_view'),
    path('rules/<int:pk>/edit/', views.rule_edit_view, name='rule_edit_view'),
    path('rules/preview/', views.rule_preview_api, name='rule_preview_api'),
    path('history/', views.history_view, name='history_view'),
    path('settings/', views.notification_settings_view, name='notification_settings_view'),
]
