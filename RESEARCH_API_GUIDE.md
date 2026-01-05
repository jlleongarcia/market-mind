# Research API - Implementation Guide

## Overview

The Research API is now implemented with a **hybrid storage architecture** that combines:
- **PostgreSQL** for persistent historical data storage
- **Redis** for high-speed caching (coming in Phase 3)
- **yfinance** as the data source

## Phase 1 Complete ✅

### What's Implemented

#### Database Models
- `Stock` - Core company information (symbol, name, sector, industry, etc.)
- `HistoricalPrice` - OHLCV price data with indexes for fast queries
- `Dividend` - Dividend payment history
- `StockSplit` - Stock split events
- `Watchlist` & `WatchlistItem` - User watchlists (existing)

#### Services
- `StockDataFetcher` - Service class for fetching data from yfinance and storing in database
  - `fetch_and_save_all()` - Fetch all data for a symbol
  - `save_stock_info()` - Fetch and save basic stock info
  - `save_historical_prices()` - Fetch and save price history
  - `save_dividends()` - Fetch and save dividend history
  - `save_splits()` - Fetch and save split history

#### API Endpoints
```
GET  /api/research/stocks/                      - List all stocks with search/filter
GET  /api/research/stocks/{symbol}/             - Get stock details
GET  /api/research/stocks/{symbol}/prices/      - Get historical prices
GET  /api/research/stocks/{symbol}/dividends/   - Get dividend history
GET  /api/research/stocks/{symbol}/splits/      - Get split history
POST /api/research/fetch/                       - Manually trigger data fetch (auth required)
```

#### Management Commands
```bash
# Fetch stock data from command line
docker-compose exec web python manage.py fetch_stock_data AAPL MSFT GOOGL --period 1y --delay 2
```

---

## Quick Start

### 1. Fetch Stock Data

**Using Management Command:**
```bash
# Fetch single stock
docker-compose exec web python manage.py fetch_stock_data AAPL

# Fetch multiple stocks with 1 year of data
docker-compose exec web python manage.py fetch_stock_data AAPL MSFT GOOGL TSLA --period 1y

# Fetch with longer history
docker-compose exec web python manage.py fetch_stock_data AAPL --period 5y

# Adjust delay to avoid rate limits (default is 2 seconds)
docker-compose exec web python manage.py fetch_stock_data AAPL MSFT --delay 5
```

**Using API (requires authentication):**
```bash
curl -X POST http://localhost:8300/api/research/fetch/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"symbol": "AAPL", "period": "1y"}'
```

### 2. Query Stock Data

**List All Stocks:**
```bash
curl http://localhost:8300/api/research/stocks/
```

**Search Stocks:**
```bash
# Search by symbol or name
curl "http://localhost:8300/api/research/stocks/?search=apple"

# Filter by sector
curl "http://localhost:8300/api/research/stocks/?sector=Technology"

# Filter by industry
curl "http://localhost:8300/api/research/stocks/?industry=Consumer Electronics"
```

**Get Stock Details:**
```bash
curl http://localhost:8300/api/research/stocks/AAPL/
```

**Get Historical Prices:**
```bash
# Last 365 days (default)
curl http://localhost:8300/api/research/stocks/AAPL/prices/

# Last 30 days
curl "http://localhost:8300/api/research/stocks/AAPL/prices/?days=30"

# Custom date range
curl "http://localhost:8300/api/research/stocks/AAPL/prices/?start=2024-01-01&end=2024-12-31"
```

**Get Dividends:**
```bash
curl http://localhost:8300/api/research/stocks/AAPL/dividends/
```

**Get Stock Splits:**
```bash
curl http://localhost:8300/api/research/stocks/AAPL/splits/
```

### 3. Auto-Fetch on Demand

When you request a stock that doesn't exist in the database, the API will automatically fetch it from yfinance:

```bash
# First request - fetches from yfinance (slower, ~2-3 seconds)
curl http://localhost:8300/api/research/stocks/NVDA/

# Subsequent requests - served from database (faster, <100ms)
curl http://localhost:8300/api/research/stocks/NVDA/
```

---

## Data Flow

```
User Request
    ↓
Cache Check (Redis) [Phase 3]
    ↓ (miss)
Database Query (PostgreSQL)
    ↓ (not found)
Fetch from yfinance
    ↓
Store in Database
    ↓
Cache Result
    ↓
Return to User
```

---

## Admin Interface

Access the Django admin to view and manage data:

1. Navigate to: `http://localhost:8300/admin/`
2. Go to "Research" section
3. View:
   - Stocks
   - Historical Prices
   - Dividends
   - Stock Splits
   - Watchlists

---

## Database Schema

### Stock
```sql
symbol (PK)       - Stock ticker
name              - Company name
sector            - Business sector
industry          - Industry classification
exchange          - Stock exchange
currency          - Trading currency
country           - Company country
last_updated      - Last update timestamp
created_at        - Record creation
is_active         - Active status
```

### HistoricalPrice
```sql
id (PK)
stock_id (FK)     - Reference to Stock
date              - Trading date
open, high, low, close - OHLC prices
volume            - Trading volume
adjusted_close    - Split/dividend adjusted close
created_at        - Record creation

UNIQUE(stock, date)
INDEX(stock, -date)
```

### Dividend & StockSplit
Similar structure with date-based unique constraints and indexes.

---

## Performance Characteristics

### Current (Phase 1)
- **Database queries**: ~50-200ms (no cache)
- **First fetch**: ~2-3 seconds (yfinance download)
- **Subsequent requests**: ~50-200ms (database)

### Coming in Phase 3 (with Redis)
- **Cached queries**: ~1-5ms
- **Recent data cache**: 5 minute TTL
- **Historical data cache**: 24 hour TTL

---

## Rate Limiting Considerations

**yfinance limitations:**
- Too many requests in short time → HTTP 429 error
- Recommended: 2-3 second delay between fetches
- Use `--delay` parameter in management command

**Strategies:**
1. Fetch popular stocks during off-peak hours
2. Use longer delays for bulk imports
3. Implement exponential backoff (future enhancement)

---

## Next Steps (Phase 2 & 3)

### Phase 2: Data Synchronization
- [ ] Celery task for daily EOD updates
- [ ] Celery task for incremental sync
- [ ] Monitoring and error handling
- [ ] Data validation and integrity checks

### Phase 3: Caching & Optimization
- [ ] Redis integration
- [ ] Cache warming strategies
- [ ] Query optimization
- [ ] Performance benchmarking

---

## Troubleshooting

### "Too Many Requests" Error
**Solution**: Increase delay between fetches
```bash
docker-compose exec web python manage.py fetch_stock_data AAPL MSFT --delay 5
```

### Empty Results
**Check 1**: Verify stock symbol is valid
```bash
# Try on Yahoo Finance first: https://finance.yahoo.com/quote/AAPL
```

**Check 2**: Check database
```bash
docker-compose exec web python manage.py shell
>>> from research.models import Stock
>>> Stock.objects.all()
```

### Database Connection Issues
```bash
# Check Docker containers
docker-compose ps

# Restart if needed
docker-compose restart

# Check migrations
docker-compose exec web python manage.py showmigrations research
```

---

## Examples

### Populate Database with Popular Stocks
```bash
docker-compose exec web python manage.py fetch_stock_data \
  AAPL MSFT GOOGL AMZN TSLA NVDA META NFLX \
  --period 1y --delay 3
```

### Query Latest Prices
```bash
# Get latest price for multiple stocks
for symbol in AAPL MSFT GOOGL; do
  echo "=== $symbol ==="
  curl -s "http://localhost:8300/api/research/stocks/$symbol/prices/?days=1" | jq '.prices[0]'
done
```

### Export to CSV (using jq)
```bash
curl -s "http://localhost:8300/api/research/stocks/AAPL/prices/?days=30" | \
  jq -r '.prices[] | [.date, .open, .high, .low, .close, .volume] | @csv'
```

---

## Testing

```bash
# Test basic functionality
docker-compose exec web python manage.py shell

>>> from research.services import StockDataFetcher
>>> fetcher = StockDataFetcher()
>>> result = fetcher.fetch_and_save_all('AAPL', period='1mo')
>>> print(result)
```

---

*For architectural details, see [RESEARCH_API_SCOPE.md](RESEARCH_API_SCOPE.md)*
