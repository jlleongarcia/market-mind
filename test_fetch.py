from research.services import StockDataFetcher

# Test fetching AAPL data
fetcher = StockDataFetcher()
result = fetcher.fetch_and_save_all('AAPL', period='1mo')
print("\n=== Fetch Results ===")
print(f"Symbol: {result['symbol']}")
print(f"Success: {result['success']}")
print(f"Stock saved: {result['stock_saved']}")
print(f"Prices created: {result['prices_created']}")
print(f"Prices updated: {result['prices_updated']}")
print(f"Dividends saved: {result['dividends_saved']}")
print(f"Splits saved: {result['splits_saved']}")
if result['errors']:
    print(f"Errors: {result['errors']}")
