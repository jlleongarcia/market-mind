# Research API Scope

## Overview

MarketMind will be structured around two main APIs:
1. **Research API** - Market data, analysis, and insights
2. **Portfolio Management API** - User portfolio tracking and management

This document focuses on the **Research API** implementation strategy.

---

## Research API Foundation

### Core Library
- **Primary**: [Stonks](https://github.com/lukaszbanasiak/stonks) Python library
- **Data Source**: yfinance (initial implementation)
- **Future Considerations**: Alternative data sources (Alpha Vantage, Polygon.io, etc.)

### Data Types to Collect
- **Historical Prices**: OHLCV (Open, High, Low, Close, Volume)
- **Dividends**: Historical dividend payments
- **Splits**: Stock split history
- **Company Info**: Basic company metadata
- **Financial Statements** (future): Balance sheet, income statement, cash flow

---

## Data Storage Strategy: Key Decision

### Option 1: Storage-First Approach (Recommended)
**Store historical data in a persistent volume/database and update incrementally**

#### Advantages:
- ✅ Faster response times for users
- ✅ Reduced API rate limiting issues
- ✅ Lower dependency on external data providers
- ✅ Ability to backfill historical data
- ✅ Better for analytics and bulk operations
- ✅ Cost-effective for high-traffic scenarios
- ✅ Offline capabilities

#### Challenges:
- ❌ Storage costs (relatively minimal for financial data)
- ❌ Data synchronization complexity
- ❌ Need for update scheduling system
- ❌ Data freshness management

#### Implementation Strategy:
```python
# Workflow:
1. Initial bulk download of historical data for tracked symbols
2. Store in PostgreSQL database with optimized schema
3. Daily/hourly incremental updates for recent data
4. User requests served from database
5. Cache layer (Redis) for frequently accessed data
```

#### Data Update Optimization:
- **Daily Updates**: EOD (End of Day) data for all tracked symbols
- **Intraday Updates**: Real-time/15-min delayed for actively viewed symbols
- **On-Demand Backfill**: New symbols added when first requested
- **Smart Scheduling**: Off-peak hours for bulk updates
- **Incremental Sync**: Only fetch missing date ranges

---

### Option 2: Fetch-On-Demand Approach
**Fetch data from yfinance each time a user requests it**

#### Advantages:
- ✅ Always fresh data
- ✅ No storage infrastructure needed
- ✅ Simpler initial implementation
- ✅ No data synchronization logic

#### Challenges:
- ❌ Slower response times
- ❌ API rate limiting risks
- ❌ Higher latency for users
- ❌ Dependent on external service availability
- ❌ Expensive for repeated requests
- ❌ Cannot perform bulk analytics efficiently

---

## Recommended Architecture: Hybrid Approach

### Database Schema (PostgreSQL)
```sql
-- Core tables
stocks (
    symbol PRIMARY KEY,
    name,
    sector,
    industry,
    last_updated
)

historical_prices (
    id,
    symbol FK,
    date,
    open, high, low, close,
    volume,
    adjusted_close,
    UNIQUE(symbol, date)
)

dividends (
    id,
    symbol FK,
    date,
    amount,
    UNIQUE(symbol, date)
)

splits (
    id,
    symbol FK,
    date,
    ratio
)
```

### Caching Strategy (Redis)
```python
# Cache layers with TTL (Time To Live):
- Recent price data (1-7 days): TTL 5 minutes
- Historical data (>7 days): TTL 24 hours
- Company metadata: TTL 1 week
- Calculated metrics: TTL 1 hour
```

#### Cache Expiration & Memory Management
- **TTL-Based Expiration**: Cache entries automatically expire after their TTL, ensuring data freshness and preventing stale data
- **Memory Threshold**: Monitor Redis memory usage with a defined threshold (e.g., 80% of allocated memory)
  - When threshold is reached → Flush entire cache to prevent memory overflow
  - Cache rebuilds naturally through subsequent user requests
  - Alerts/logging when threshold flush occurs for capacity planning
- **Eviction Policy**: Configure Redis with `allkeys-lru` (Least Recently Used) as backup eviction policy
- **Memory Allocation**: Start with 512MB-1GB Redis memory limit, scale based on usage patterns

### Data Pipeline
```
┌─────────────┐
│  User Query │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Redis Cache │──── Cache Hit ────┐
└──────┬──────┘                   │
       │ Cache Miss               │
       ▼                          ▼
┌─────────────┐            ┌──────────┐
│  PostgreSQL │────────────► Response │
└──────┬──────┘            └──────────┘
       │ Data Missing
       ▼
┌─────────────┐
│  yfinance   │──── Fetch & Store
└─────────────┘
```

---

## Implementation Phases

### Phase 1: Basic Storage & Retrieval
- [ ] Set up PostgreSQL schema
- [ ] Implement Stonks/yfinance data fetcher
- [ ] Create Django models for financial data
- [ ] Build basic CRUD operations
- [ ] Implement symbol lookup and metadata storage

### Phase 2: Data Synchronization
- [ ] Create Celery tasks for scheduled updates
- [ ] Implement incremental data sync logic
- [ ] Add data validation and integrity checks
- [ ] Build monitoring for update failures
- [ ] Create admin dashboard for data status

### Phase 3: Caching & Optimization
- [ ] Integrate Redis caching layer
- [ ] Optimize database queries with indexes
- [ ] Implement query result caching
- [ ] Add rate limiting for external API calls
- [ ] Performance benchmarking

### Phase 4: API Endpoints
- [ ] RESTful API for stock data retrieval
- [ ] Historical price range queries
- [ ] Dividend history endpoints
- [ ] Company search and filter
- [ ] Bulk data export capabilities

### Phase 5: Advanced Features
- [ ] Technical indicators calculation
- [ ] Financial ratios and metrics
- [ ] Comparative analysis tools
- [ ] Watchlist management
- [ ] Alert system for price changes

---

## Technology Stack

### Backend
- **Framework**: Django + Django REST Framework
- **Database**: PostgreSQL (time-series optimized)
- **Cache**: Redis
- **Task Queue**: Celery + Redis
- **API Client**: Stonks library + yfinance

### Data Storage Considerations
- **Volume Mount**: PostgreSQL data directory
- **Backup Strategy**: Daily snapshots
- **Retention Policy**: Full history (no deletion)
- **Estimated Size**: ~500MB per 1000 symbols (5 years history)

---

## Performance Targets

- **API Response Time**: < 100ms (cached), < 500ms (database)
- **Data Freshness**: EOD data within 1 hour of market close
- **Update Frequency**: Daily for historical, hourly for recent
- **Concurrent Users**: Support 100+ simultaneous requests
- **Data Availability**: 99.9% uptime

---

## Risk Mitigation

### Data Provider Risks
- **Rate Limiting**: Implement exponential backoff and request throttling
- **Service Downtime**: Queue failed requests for retry
- **Data Quality**: Validation rules and anomaly detection

### Storage Risks
- **Disk Space**: Monitoring and alerts for capacity
- **Data Corruption**: Regular integrity checks and backups
- **Performance Degradation**: Query optimization and indexing strategy

---

## Next Steps

1. **Prototype**: Build proof-of-concept with single symbol
2. **Benchmark**: Compare storage vs. fetch-on-demand performance
3. **Schema Design**: Finalize database schema with proper indexes
4. **Pipeline Setup**: Implement basic data sync workflow
5. **Testing**: Validate data accuracy against yfinance

---

## Open Questions

1. How many symbols should we support initially? (S&P 500? Custom watchlists?)
2. Should we support international markets from day one?
3. What's the priority for real-time vs. EOD data?
4. Do we need options/futures data, or just equities?
5. Should we implement our own technical indicators or use a library?

---

*Last Updated: January 5, 2026*
