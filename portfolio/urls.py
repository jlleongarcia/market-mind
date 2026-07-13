"""
Portfolio API URL Configuration
"""
from django.urls import path
from . import views

app_name = 'portfolio'

urlpatterns = [
    # ========================================================================
    # Frontend Template Views
    # ========================================================================
    path('', views.portfolio_list_view, name='portfolio_list_view'),
    path('create/', views.portfolio_create_view, name='portfolio_create_view'),
    path('<int:pk>/', views.portfolio_detail_view, name='portfolio_detail_view'),
    path('<int:pk>/edit/', views.portfolio_edit_view, name='portfolio_edit_view'),
    path('<int:portfolio_id>/add-transaction/', views.transaction_create_view, name='transaction_create_view'),
    path('<int:portfolio_id>/transaction/<int:tx_id>/edit/', views.transaction_edit_view, name='transaction_edit_view'),
    path('<int:portfolio_id>/transaction/<int:tx_id>/delete/', views.transaction_delete_view, name='transaction_delete_view'),
    path('<int:portfolio_id>/dividend/<int:dividend_id>/edit/', views.dividend_edit_view, name='dividend_edit_view'),
    path('<int:portfolio_id>/dividend/<int:dividend_id>/delete/', views.dividend_delete_view, name='dividend_delete_view'),
    path('<int:portfolio_id>/position/<str:symbol>/', views.position_detail_view, name='position_detail_view'),
    path('combined/', views.portfolio_combined_view, name='portfolio_combined_view'),
    path('<int:pk>/sync-dividends/', views.portfolio_sync_dividends, name='portfolio_sync_dividends'),
    path('<int:pk>/delete/', views.portfolio_delete_view, name='portfolio_delete_view'),
    path('<int:pk>/tax-report/', views.tax_report_view, name='tax_report_view'),
    path('tax-settings/', views.tax_settings_view, name='tax_settings_view'),
    
    # ========================================================================
    # API Endpoints (JSON responses)
    # ========================================================================
    
    # Portfolio management endpoints
    path('api/portfolios/', views.PortfolioListCreateView.as_view(), name='portfolio-list'),
    path('api/portfolios/<int:pk>/', views.PortfolioDetailView.as_view(), name='portfolio-detail'),
    
    # Portfolio summary and analytics
    path('api/portfolios/<int:pk>/summary/', views.PortfolioSummaryView.as_view(), name='portfolio-summary'),
    path('api/portfolios/<int:pk>/brokers/', views.BrokerSummaryView.as_view(), name='broker-summary'),
    path('api/portfolios/<int:pk>/dividends/history/', views.DividendIncomeHistoryView.as_view(), name='dividend-history'),
    
    # Positions
    path('api/portfolios/<int:pk>/positions/', views.PortfolioPositionsView.as_view(), name='portfolio-positions'),
    path('api/portfolios/<int:portfolio_id>/positions/<str:symbol>/', views.PositionDetailView.as_view(), name='position-detail'),
    
    # Transactions
    path('api/portfolios/<int:pk>/transactions/', views.PortfolioTransactionsView.as_view(), name='portfolio-transactions'),
    path('api/transactions/', views.TransactionCreateView.as_view(), name='transaction-create'),
    
    # Dividends
    path('api/dividends/', views.DividendListView.as_view(), name='dividend-list'),
]


