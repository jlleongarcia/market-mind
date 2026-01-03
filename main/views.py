from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse


@api_view(['GET'])
def api_root(request, format=None):
    """
    API Root - Welcome to Stonks API
    """
    return Response({
        'message': 'Welcome to Stonks - Stock Market Research & Portfolio Management API',
        'version': '1.0.0',
        'endpoints': {
            'admin': reverse('admin:index', request=request, format=format),
            'research': {
                'search_stocks': '/api/research/stocks/search/?q=AAPL',
                'stock_detail': '/api/research/stocks/{symbol}/',
                'stock_history': '/api/research/stocks/{symbol}/history/?period=1mo',
                'stock_metrics': '/api/research/stocks/{symbol}/metrics/',
            },
            'portfolio': {
                'list': reverse('portfolio:portfolio-list', request=request, format=format),
                'transactions': reverse('portfolio:transaction-create', request=request, format=format),
                'dividends': reverse('portfolio:dividend-list', request=request, format=format),
            },
            'authentication': {
                'obtain_token': reverse('token_obtain_pair', request=request, format=format),
                'refresh_token': reverse('token_refresh', request=request, format=format),
            }
        },
        'documentation': {
            'free_tier': 'Research endpoints are available without authentication',
            'premium_tier': 'Portfolio endpoints require JWT authentication',
        }
    })
