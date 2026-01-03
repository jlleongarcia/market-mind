from django.urls import path
from . import views

app_name = 'portfolio'

urlpatterns = [
    # Portfolio management endpoints (premium tier)
    path('portfolios/', views.PortfolioListCreateView.as_view(), name='portfolio-list'),
    path('portfolios/<int:pk>/', views.PortfolioDetailView.as_view(), name='portfolio-detail'),
    path('portfolios/<int:pk>/positions/', views.PortfolioPositionsView.as_view(), name='portfolio-positions'),
    path('portfolios/<int:pk>/transactions/', views.PortfolioTransactionsView.as_view(), name='portfolio-transactions'),
    path('transactions/', views.TransactionCreateView.as_view(), name='transaction-create'),
    path('dividends/', views.DividendListView.as_view(), name='dividend-list'),
]
