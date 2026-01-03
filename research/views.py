from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
import yfinance as yf
from datetime import datetime, timedelta


class SearchStockView(APIView):
    """Search for stocks (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        query = request.query_params.get('q', '')
        if not query:
            return Response({'error': 'Query parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Placeholder - will implement search logic with yfinance
        return Response({
            'message': 'Stock search endpoint',
            'query': query,
            'results': []
        })


class StockDetailView(APIView):
    """Get detailed stock information (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        try:
            stock = yf.Ticker(symbol.upper())
            info = stock.info
            
            return Response({
                'symbol': symbol.upper(),
                'name': info.get('longName', ''),
                'current_price': info.get('currentPrice'),
                'previous_close': info.get('previousClose'),
                'open': info.get('open'),
                'day_high': info.get('dayHigh'),
                'day_low': info.get('dayLow'),
                'volume': info.get('volume'),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'dividend_yield': info.get('dividendYield'),
                '52_week_high': info.get('fiftyTwoWeekHigh'),
                '52_week_low': info.get('fiftyTwoWeekLow'),
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StockHistoryView(APIView):
    """Get historical stock data (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        period = request.query_params.get('period', '1mo')  # 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max
        
        try:
            stock = yf.Ticker(symbol.upper())
            hist = stock.history(period=period)
            
            data = []
            for date, row in hist.iterrows():
                data.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'open': round(row['Open'], 2),
                    'high': round(row['High'], 2),
                    'low': round(row['Low'], 2),
                    'close': round(row['Close'], 2),
                    'volume': int(row['Volume'])
                })
            
            return Response({
                'symbol': symbol.upper(),
                'period': period,
                'data': data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StockMetricsView(APIView):
    """Get financial metrics for a stock (free tier)"""
    permission_classes = [AllowAny]
    
    def get(self, request, symbol):
        try:
            stock = yf.Ticker(symbol.upper())
            info = stock.info
            
            return Response({
                'symbol': symbol.upper(),
                'metrics': {
                    'market_cap': info.get('marketCap'),
                    'pe_ratio': info.get('trailingPE'),
                    'forward_pe': info.get('forwardPE'),
                    'peg_ratio': info.get('pegRatio'),
                    'price_to_book': info.get('priceToBook'),
                    'dividend_yield': info.get('dividendYield'),
                    'profit_margin': info.get('profitMargins'),
                    'operating_margin': info.get('operatingMargins'),
                    'return_on_assets': info.get('returnOnAssets'),
                    'return_on_equity': info.get('returnOnEquity'),
                    'revenue': info.get('totalRevenue'),
                    'revenue_per_share': info.get('revenuePerShare'),
                    'earnings_growth': info.get('earningsGrowth'),
                    'revenue_growth': info.get('revenueGrowth'),
                    'beta': info.get('beta'),
                }
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
