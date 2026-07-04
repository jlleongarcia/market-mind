# Dividend Automation

How MarketMind computes **Buy Yield** on purchases, keeps that calculation
accurate over time, and records dividend income against positions —
including ones that have since been fully sold.

---

## Buy Yield

`Transaction.buy_yield` (BUY transactions only) estimates the forward
dividend yield a purchase locks in:

```
buy_yield = annualised dividend per share / effective cost per share
effective cost per share = (price × quantity + commission) / quantity
annualised dividend per share = reference dividend amount × 4  (quarterly assumption)
```

The part that matters is **which dividend counts as the reference**
(`PortfolioCalculationService.fetch_and_store_buy_yield`,
`portfolio/services.py`):

1. **Preferred** — the dividend with the latest `declaration_date <= buy_date`,
   regardless of whether its ex-dividend date has already passed. A dividend
   that's been publicly declared is a known, current rate even before it
   goes ex — a buyer effectively "locks in" that rate the moment they
   purchase.
2. **Fallback** — when the stock has no `declaration_date` data at all, the
   last dividend with an ex-dividend date strictly before the buy date (the
   original, simpler rule).

### Why this matters: the off-by-one-quarter bug

The fallback rule alone under-counts recent buys. Example (verified against
a real transaction): buying MO on 2023-09-13, one day before its
2023-09-14 ex-date. MO had just raised its dividend from $0.94 to $0.98,
effective that Sept 14 payment. The buyer is entitled to the *new*, higher
dividend (owned the shares before the ex-date) — but the fallback rule only
looks at ex-dates *before* the purchase, so it picks the stale $0.94 and
computes 8.36% instead of the correct 8.71%.

Comparing against `declaration_date` fixes this: the $0.98 dividend was
declared well before 9/13, so rule 1 picks it correctly.

---

## Data sources & a hard limit

Dividend history (`research.Dividend`) is fetched by
`StockDataFetcher.save_dividends` (`research/services.py`):

- **Alpha Vantage `DIVIDENDS` endpoint (preferred)** — the only source that
  provides `declaration_date` (and `payment_date`). Coverage starts around
  **2020**; older dividends will never have a `declaration_date`, and that's
  expected — they just use the fallback rule above.
- **yfinance (fallback)** — used only when Alpha Vantage is unavailable
  (missing key, rate limit, request error). Has no `declaration_date` at
  all, so any dividend saved this way needs a later backfill pass before
  Buy Yield can use rule 1 for it.

**Alpha Vantage's free-tier key is capped at 25 requests/day.** Hitting that
cap is routine, not exceptional — expect to see
`"Alpha Vantage DIVIDENDS no data for X: ... rate limit"` in logs regularly.
When that happens, `save_dividends` transparently falls back to yfinance, so
data keeps flowing — just without `declaration_date` until the next
successful backfill.

---

## Self-healing backfill (daily cron)

Because the AV quota is small and shared across every tracked stock, a
single stock can go a day or more with only yfinance data. Two idempotent
management commands close that gap automatically:

- **`backfill_dividend_declaration_dates`** — update-only: fills in
  `declaration_date` on existing `Dividend` rows, never creates new ones and
  never touches `amount`/`payment_date`. Only targets stocks with a dividend
  dated on/after a **fixed** `2020-01-01` boundary (Alpha Vantage's observed
  `declaration_date` coverage start) that's still missing `declaration_date`
  **and** not yet `declaration_date_checked`. This must be a fixed calendar
  date, not a rolling window relative to "today": a rolling window would
  eventually push a genuinely-recoverable row (e.g. the MO 2023-09-14
  dividend above) out of range purely because time passed, silently
  dropping it from future retries even though Alpha Vantage could still
  supply it. Accepts `--symbols SYM1 SYM2` to target specific stocks and
  `--delay N` to throttle AV calls.

  **`declaration_date_checked`** distinguishes "never verified against AV
  yet" from "AV genuinely has nothing for this one" — set whenever AV
  responds for an exact ex-date, whether or not it had a `declaration_date`
  to give, *except* when the ex-date is still in the future (an
  undeclared-but-upcoming dividend must keep being retried daily until it's
  actually announced — that's the mechanism that fixes cases like MO).
  Without this distinction, a stock with even one permanently-unrecoverable
  gap (Alpha Vantage itself has occasional holes even within its covered
  era — e.g. two of MSFT's own rows never got a `declaration_date` despite
  a fully successful AV response) would resurface in the backlog every
  single day forever, silently eating into the 25/day quota that a
  brand-new stock might need.
- **`recompute_buy_yields`** — reruns `fetch_and_store_buy_yield` for every
  BUY transaction, so any yield computed while data was still incomplete
  gets silently corrected once `declaration_date` shows up.

These run daily at **8:30 AM**, right after the DB backup, via
`scripts/backfill_dividend_data.sh` (registered with `make
setup-cron-dividends` — see `DEPLOYMENT.md`). End result: any stock —
existing or newly added — ends up with correct Buy Yield within a day or
two of being tracked, with no manual intervention.

Run manually any time:

```bash
docker exec market-mind-web-1 python manage.py backfill_dividend_declaration_dates
docker exec market-mind-web-1 python manage.py recompute_buy_yields
```

---

## Dividend ledger sync (`auto_record_dividends`)

Separately from Buy Yield, `PortfolioCalculationService.auto_record_dividends`
(triggered by the "Sync Dividends" button → `portfolio_sync_dividends` view)
creates `portfolio.Dividend` ledger entries (shown in the portfolio's
Activity feed) for dividends a user actually qualified for — held shares at
close of the day before the ex-dividend date.

Symbols are sourced from **transaction history**, not open positions —
a symbol that's been fully sold has no `Position` row anymore, but the user
may still be owed a dividend that went ex-date before the sale (or even
after: selling on/after the ex-date doesn't forfeit that dividend). Sourcing
from `Transaction` history instead ensures fully-closed-out positions still
get checked and recorded.

This sync is **user-triggered only** — it is not run by the daily cron
above, and won't create ledger entries on its own.
