# Research API - Quick Reference

## 🚀 Quick Start Commands

### Fetch Stock Data
```bash
# Single stock (1 month)
docker-compose exec web python manage.py fetch_stock_data AAPL

# Multiple stocks (1 year)
docker-compose exec web python manage.py fetch_stock_data AAPL MSFT GOOGL --period 1y --delay 3

# Long history (5 years)
docker-compose exec web python manage.py fetch_stock_data AAPL --period 5y
```

### API Endpoints
```bash
# List all stocks
curl http://localhost:8300/api/research/stocks/

# Search stocks
curl "http://localhost:8300/api/research/stocks/?search=apple"

# Get stock details
curl http://localhost:8300/api/research/stocks/AAPL/

# Get prices (last 30 days)
curl "http://localhost:8300/api/research/stocks/AAPL/prices/?days=30"

# Get dividends
curl http://localhost:8300/api/research/stocks/AAPL/dividends/

# Get splits
curl http://localhost:8300/api/research/stocks/AAPL/splits/
```

## 📊 Data Models

```
Stock            → Company info (symbol, name, sector, industry)
HistoricalPrice  → OHLCV daily prices
Dividend         → Dividend payments
StockSplit       → Stock split events
```

## 🔧 Common Tasks

### Check Database
```bash
docker-compose exec web python manage.py shell
>>> from research.models import Stock, HistoricalPrice
>>> Stock.objects.count()
>>> HistoricalPrice.objects.count()
```

### View in Admin
```
1. Go to http://localhost:8300/admin/
2. Navigate to Research section
3. Browse Stocks, Prices, Dividends, Splits
```

### Bulk Load Popular Stocks
```bash
docker-compose exec web python manage.py fetch_stock_data \
  AAPL MSFT GOOGL AMZN TSLA NVDA META NFLX ORCL IBM \
  --period 1y --delay 3
```

## ⚠️ Important Notes

- **Rate Limits**: Yahoo Finance limits requests. Use `--delay 3` or higher
- **429 Error**: "Too Many Requests" - wait a few minutes and retry
- **Auto-fetch**: Requesting a non-existent stock triggers automatic fetch

## 📁 Key Files

```
research/
├── models.py              → Data models
├── services.py            → Data fetching logic
├── serializers.py         → API serializers
├── views.py               → API views
├── urls.py                → URL routing
├── admin.py               → Admin interface
└── management/commands/
    └── fetch_stock_data.py → CLI command
```

## 🔗 Documentation

- [RESEARCH_API_SCOPE.md](RESEARCH_API_SCOPE.md) - Architecture & planning
- [RESEARCH_API_GUIDE.md](RESEARCH_API_GUIDE.md) - Detailed usage guide
- [RESEARCH_API_IMPLEMENTATION_SUMMARY.md](RESEARCH_API_IMPLEMENTATION_SUMMARY.md) - What we built

## 📈 Next Phase

**Phase 2**: Celery for automated daily updates
**Phase 3**: Redis for sub-millisecond caching
**Phase 4**: Technical indicators & advanced features
