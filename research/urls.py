from django.urls import path
from . import views

app_name = 'research'

urlpatterns = [
    # Frontend Pages (Template Views)
    path('', views.StockListPageView.as_view(), name='stock_list_page'),
    path('stocks/<str:symbol>/', views.StockDetailPageView.as_view(), name='stock_detail_page'),
    
    # Authentication URLs
    path('register/', views.user_registration, name='user_registration'),
    path('register/success/', views.registration_success, name='registration_success'),
    path('account/', views.account_panel, name='account_panel'),
    path('account/settings/', views.account_settings, name='account_settings'),
    path('account/password/', views.change_password, name='change_password'),
    
    # API Endpoints (with 'api/' prefix to avoid conflicts)
    path('api/stocks/', views.StockListView.as_view(), name='stock-list'),
    path('api/stocks/<str:symbol>/', views.StockDetailView.as_view(), name='stock-detail'),
    path('api/stocks/<str:symbol>/metrics/', views.StockFinancialMetricsView.as_view(), name='stock-metrics'),
    path('api/stocks/<str:symbol>/prices/', views.StockPriceHistoryView.as_view(), name='stock-prices'),
    path('api/stocks/<str:symbol>/dividends/', views.StockDividendsView.as_view(), name='stock-dividends'),
    path('api/stocks/<str:symbol>/splits/', views.StockSplitsView.as_view(), name='stock-splits'),
    path('api/fetch/', views.FetchStockDataView.as_view(), name='fetch-stock-data'),
]
