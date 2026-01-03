from django.urls import path
from . import views

app_name = 'research'

urlpatterns = [
    # Stock research endpoints (free tier)
    path('stocks/search/', views.SearchStockView.as_view(), name='search-stock'),
    path('stocks/<str:symbol>/', views.StockDetailView.as_view(), name='stock-detail'),
    path('stocks/<str:symbol>/history/', views.StockHistoryView.as_view(), name='stock-history'),
    path('stocks/<str:symbol>/metrics/', views.StockMetricsView.as_view(), name='stock-metrics'),
]
