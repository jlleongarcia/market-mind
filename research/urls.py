from django.urls import path
from . import views

app_name = 'research'

urlpatterns = [
    # Frontend Pages (Template Views)
    path('', views.StockListPageView.as_view(), name='stock_list_page'),
    path('stocks/<str:symbol>/', views.StockDetailPageView.as_view(), name='stock_detail_page'),
]

# API Endpoints (keep separate for clarity)
api_urlpatterns = [
    # Stock listing and search
    path('stocks/', views.StockListView.as_view(), name='stock-list'),
    path('stocks/<str:symbol>/', views.StockDetailView.as_view(), name='stock-detail'),
    
    # Historical data endpoints
    path('stocks/<str:symbol>/prices/', views.StockPriceHistoryView.as_view(), name='stock-prices'),
    path('stocks/<str:symbol>/dividends/', views.StockDividendsView.as_view(), name='stock-dividends'),
    path('stocks/<str:symbol>/splits/', views.StockSplitsView.as_view(), name='stock-splits'),
    
    # Admin/management endpoints
    path('fetch/', views.FetchStockDataView.as_view(), name='fetch-stock-data'),
]

urlpatterns += api_urlpatterns
