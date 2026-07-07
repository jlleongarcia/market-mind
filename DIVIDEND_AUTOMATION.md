# Dividend Automation

How MarketMind computes **Buy Yield** on purchases, keeps that calculation
accurate over time, and records dividend income against positions —
including ones that have since been fully sold.

For estimating origin-country withholding tax on those dividends, see
[TAX_WITHHOLDING.md](TAX_WITHHOLDING.md) — a separate, per-user concern
layered on top of the ledger described here.

---

## 🔜 Near-future checks

Things still open, kept here deliberately separate from the rest of this
doc (which describes how the system works *today*) so they don't get lost:

- **FMP Terms of Service unreviewed.** We checked Finnhub's and Tiingo's ToS
  before ruling them out (redistribution/storage clauses, personal-use
  disqualifiers), but never did the same for FMP before wiring it in as a
  primary source. Worth reading `financialmodelingprep.com`'s ToS for the
  same clauses — redistribution of derived data, storage/caching on
  cancellation, personal- vs. commercial-use terms — before leaning on it
  further.
- **Watch Alpha Vantage's quota now that two things share it**: the
  handful of genuinely AV-only (non-US) symbols, *and* the new FMP-failure
  fallback (below) for premium-gated US tickers like `CAT`/`HON`/`MO`/`WDS`.
  Both are small today, but confirm over the next several daily cron runs
  that the fallback's extra spending never actually starves the AV-primary
  symbols (they're processed first specifically to prevent this — worth
  checking the log order holds).
- **Watch FMP's real daily request volume** against its 250/day free cap
  once live in production — fine now with ~25 US tickers, but worth
  revisiting if the tracked stock list grows substantially.
- **No way to know in advance which US tickers FMP premium-gates** short of
  calling it live — `CAT`, `HON`, `MO`, `WDS` were only discovered by
  checking why they stayed at 0 declared after the hybrid went live. Worth
  periodically re-running the per-stock audit (see `Data sources`) to catch
  any newly-added stock that turns out to need the Alpha Vantage fallback
  too.

---

## Buy Yield

`Transaction.buy_yield` (BUY transactions only) estimates the forward
dividend yield a purchase locks in:

```
buy_yield = annualised dividend per share / effective cost per share
effective cost per share = (price × quantity + commission) / quantity
```

Two things determine the annualised dividend: **payment frequency** (not
everyone pays quarterly) and **which dividend counts as the reference**
(`PortfolioCalculationService.fetch_and_store_buy_yield`, `portfolio/services.py`).

### Payment frequency isn't always 4

`research.services.infer_dividend_frequency(stock, as_of_date)` derives
payments/year from the stock's *actual* history instead of assuming
quarterly: it takes the median gap (in days) between consecutive ex-dividend
dates over the trailing ~5 years and buckets it (≤45d → 12/yr, ≤135d → 4/yr,
≤275d → 2/yr, else 1/yr). Median, not average or raw payment count, so a
handful of special dividends — which insert extra, anomalously-short gaps —
don't distort the true recurring cadence. Falls back to 4 when there's fewer
than 2 dividends to compare.

**Real bug this caught:** BHP is a genuine semi-annual payer. Before this
fix, its `buy_yield` was computing at **24.18%** — nonsensical — because the
code assumed quarterly (`× 4`) for every stock. `infer_dividend_frequency`
correctly resolves it to 2/yr even though 2 of the last 8 years had a 3rd
(special) payment thrown in, since the median of `[2,2,2,2,3,2,2,2]` is
still 2.

### Reference dividend — and the outlier guard

For regular stocks (not ETFs, see below), the reference amount is:

1. **Preferred** — the dividend with the latest `declaration_date <= buy_date`,
   regardless of whether its ex-dividend date has already passed. A dividend
   that's been publicly declared is a known, current rate even before it
   goes ex — a buyer effectively "locks in" that rate the moment they
   purchase.
2. **Fallback** — when the stock has no `declaration_date` data at all, the
   last dividend with an ex-dividend date strictly before the buy date (the
   original, simpler rule).

That reference amount is then checked against the **median of the trailing
2×frequency actual payments** (the stock's own recent "normal" range). If
it's more than **1.75×** that median, it's treated as a special dividend and
the median is used instead — a real dividend raise never jumps this much in
one step (MO's raise was 1.04×, HON's would-be raise 1.05×), so this only
catches genuine outliers. This is what fixes BHP fully: its reference
dividend for a 2021-12-21 purchase was a **$3.5682** payment — itself a
special-dividend-inflated outlier (~2.8× the stock's own recent median of
~$1.28) — swapping in the median drops `buy_yield` from 24.18% to a sane
**4.32%**.

The annualised dividend per share is then `reference_amount × frequency`.

### Why the declaration_date preference matters: the off-by-one-quarter bug

The fallback rule alone under-counts recent buys. Example (verified against
a real transaction): buying MO on 2023-09-13, one day before its
2023-09-14 ex-date. MO had just raised its dividend from $0.94 to $0.98,
effective that Sept 14 payment. The buyer is entitled to the *new*, higher
dividend (owned the shares before the ex-date) — but the fallback rule only
looks at ex-dates *before* the purchase, so it picks the stale $0.94 and
computes 8.36% instead of the correct 8.71%.

Comparing against `declaration_date` fixes this: the $0.98 dividend was
declared well before 9/13, so rule 1 picks it correctly.

### ETFs are handled differently — no single reference dividend

`Stock.is_etf` (from yfinance's `quoteType`, auto-populated whenever stock
info is fetched/refreshed — no manual tagging) switches the whole approach.
ETF distributions commonly vary payment-to-payment (underlying yield,
turnover, capital gains components) with no board-declared "rate" to lock
in — there's no single stable value to extrapolate from, outlier or not. So
for ETFs, the annualised dividend is simply the **sum of the last
`frequency` distributions known as of the buy date** — a trailing realised
total rather than an extrapolation from any one payment.

"Known as of the buy date" uses the *exact same* declaration_date-preferred/
ex_date-fallback rule as regular stocks (a distribution already announced
but not yet gone ex still counts) — only the single-value-vs-sum part
differs between ETFs and equities. The data pipeline is identical too:
`save_dividends` and `backfill_dividend_declaration_dates` are symbol-based
with no ETF/equity branching at all, so ETFs get `declaration_date` and
`declaration_date_checked` populated (or not) exactly the same way regular
stocks do.

### Dividend growth has the same frequency fix

`StockDataFetcher.calculate_dividend_growth` (1Y/5Y growth shown on the
research/position views) had the identical latent bug: it hardcoded "last 4
dividends = 1 year" for the comparison windows. For a semi-annual payer like
BHP, "last 4" actually spans ~2 years, so its "1Y growth" was quietly wrong
too. Now uses `infer_dividend_frequency` in place of the hardcoded 4 for both
the 1Y window (`last freq / previous freq`) and the 5Y CAGR base window.

After changing this logic, existing values need a refresh — `manage.py
update_financial_metrics --all` recomputes and stores it for every tracked
stock; `manage.py recompute_buy_yields` does the equivalent for `buy_yield`
on existing transactions. Both are safe to rerun any time.

---

## Data sources

Dividend history (`research.Dividend`) is fetched by
`StockDataFetcher.save_dividends` (`research/services.py`), which routes to
one of two primary sources depending on the stock's exchange
(`StockDataFetcher.dividend_source_name` / `_fetch_dividends_primary`),
falling back to yfinance if the routed source fails:

- **FMP `/stable/dividends` (US-listed stocks)** — `Stock.exchange` in
  `{NMS, NYQ, NYSE, NASDAQ}` routes here. Free tier gives full history in a
  single request per symbol, including `declaration_date`, back to the
  1990s for most tickers (deeper than Alpha Vantage). **Blocks non-US
  symbols outright** even with a paid-for key ("Premium Query Parameter"),
  which is why non-US stocks are routed to Alpha Vantage instead — this
  isn't optional. It **also premium-gates a subset of well-known US
  tickers** the same way — confirmed live for `CAT`, `HON`, `MO`, `WDS`
  (HTTP 402, `"Premium Query Parameter: Special Endpoint..."`, not a rate
  limit) — so the FMP/Alpha Vantage split isn't purely a US/non-US
  boundary; some US names need the fallback below too. Free-tier quota:
  **250 requests/day**, comfortably covering the whole US-listed stock list
  with room to spare.
- **Alpha Vantage `DIVIDENDS` endpoint (everything else — LSE etc.)** — same
  single-request-per-symbol shape, also provides `declaration_date` (and
  `payment_date`), but coverage only starts around **2020**; older
  dividends will never have a `declaration_date` there, and that's
  expected — they just use the fallback rule above. Free-tier quota: **25
  requests/day**, now shared only across the handful of non-US symbols
  (previously shared across the entire stock list, which used to cause the
  quota to run out before the first stock in the daily rotation).
- **yfinance (universal fallback)** — used only when the routed primary
  source is unavailable (missing key, rate limit, premium-gated, request
  error). Has no `declaration_date` at all, so any dividend saved this way
  needs a later backfill pass before Buy Yield can use rule 1 for it.

Both primary sources fetch a symbol's **entire** dividend history
(`declaration_date`, `ex_date`, `payment_date` all included) in **one**
request — there's no cheaper way to get these three dates, so this is
already the minimum possible call count per symbol per refresh.

**Alpha Vantage's free-tier key is capped at 25 requests/day** (FMP's is
250/day). Expect to see `"FMP dividends no data for X: ..."` or `"Alpha
Vantage DIVIDENDS no data for X: ... rate limit"` in logs occasionally.
When that happens, `save_dividends` transparently falls back to yfinance, so
data keeps flowing — just without `declaration_date` until the next
successful backfill.

**Not every symbol has dividend history on its routed source, and that's a
real, permanent answer, not a quota problem.** Confirmed live for two LSE
ETFs, IDUS.L and DGRW.L: calling Alpha Vantage's `DIVIDENDS` endpoint
directly (with a delay between calls, to rule out the burst-rate-limit
false negative) returned a clean, non-error `{"data": []}` for both — zero
dividend history, ever, not a rate-limit message. FMP can't help either
(non-US block). These two will permanently rely on the ex-date-only
fallback rule for Buy Yield. `backfill_dividend_declaration_dates` (below)
detects this "clean empty response" case and marks every eligible row
`declaration_date_checked` immediately, instead of retrying forever.

**Other providers evaluated and rejected (2026-07-05):** Finnhub's free tier
gates *both* of its dividend endpoints behind a paid plan, for any market —
confirmed via their own published API schema (`"premium": "Premium Access
Required"`), not just marketing copy. Tiingo's corporate-actions/dividends
endpoint returned live `403 Forbidden` on a real free-tier key (the same key
works fine on Tiingo's free EOD-prices endpoint) — their docs say this
endpoint needs discretionary Beta/enterprise approval from support, not a
standard free-tier grant. Neither is used anywhere in this codebase.

---

## Self-healing backfill (daily cron)

Because Alpha Vantage's quota is small — and, before the FMP hybrid, was
shared across every tracked stock — a single stock could go a day or more
with only yfinance data. Two idempotent management commands close that gap
automatically:

- **`backfill_dividend_declaration_dates`** — update-only: fills in
  `declaration_date` **and `payment_date`** on existing `Dividend` rows,
  never creates new ones and never touches `amount`. Routes each stock to
  FMP or Alpha Vantage the same way `save_dividends` does
  (`dividend_source_name`), so US stocks no longer compete with LSE ones
  for Alpha Vantage's 25/day cap.

  **`payment_date` backfill is a free side effect, not an extra request:**
  both FMP and Alpha Vantage already return `payment_date` in the exact
  same response used for `declaration_date`, so filling it in costs
  nothing beyond what the command already fetches. It's strictly
  additive — only fills rows where `payment_date` is currently `NULL`,
  never overwrites an existing value — same safety profile as the
  `declaration_date` fill. Unlike `declaration_date`, there's no separate
  "confirmed absent" bookkeeping for it: whether a stock gets re-attempted
  at all is governed entirely by `declaration_date_checked`, so a row
  missing only `payment_date` (with `declaration_date` already known)
  won't be revisited by this command specifically for that gap — the
  fuller `save_dividends` sync path would pick it up instead.

  **FMP-failure fallback (this command only):** if an FMP-routed stock's
  request fails for any reason — including FMP's per-symbol premium gate,
  not just a genuine rate limit — this command retries via Alpha Vantage
  before giving up. Confirmed live: `CAT`/`HON`/`MO`/`WDS` are all
  premium-gated on FMP but have full `declaration_date` history on Alpha
  Vantage, previously wasted as a permanent, silent daily failure (see
  above). Stocks are processed **Alpha-Vantage-primary (non-US) first**,
  specifically so this fallback's spending never starves the handful of
  genuinely AV-only symbols of their own quota. Deliberately *not* shared
  with `save_dividends`'s ordinary sync path: this cron runs sequentially
  and throttled by `--delay`, so it's safe to spend Alpha Vantage's
  near-entirely-unused spare quota here, whereas `save_dividends` can run
  from parallel, uncoordinated contexts (e.g. `auto_record_dividends`'s
  `ThreadPoolExecutor`) where the same fallback could reintroduce the quota
  contention the FMP/Alpha Vantage split was built to fix in the first
  place.

  Only targets stocks with a dividend dated on/after a **fixed** `2020-01-01`
  boundary (Alpha Vantage's observed `declaration_date` coverage start —
  shared as a conservative floor for FMP too, even though FMP's own coverage
  goes deeper) that's still missing `declaration_date` **and** not yet
  `declaration_date_checked`. This must be a fixed calendar date, not a
  rolling window relative to "today": a rolling window would eventually push
  a genuinely-recoverable row (e.g. the MO 2023-09-14 dividend above) out of
  range purely because time passed, silently dropping it from future
  retries even though the source could still supply it. Accepts `--symbols
  SYM1 SYM2` to target specific stocks and `--delay N` to throttle calls.

  **`declaration_date_checked`** distinguishes "never verified against the
  routed source yet" from "that source genuinely has nothing for this one"
  — set whenever the source responds for an exact ex-date, whether or not
  it had a `declaration_date` to give, *except* when the ex-date is still in
  the future (an undeclared-but-upcoming dividend must keep being retried
  daily until it's actually announced — that's the mechanism that fixes
  cases like MO). Same idea applies one level up: if a stock's routed source
  answers with a clean, empty history (no rate-limit error, just zero
  entries — confirmed for IDUS.L/DGRW.L above), every eligible row for that
  stock is marked checked immediately, rather than resurfacing in the
  backlog every single day forever and silently eating into whichever
  source's quota it's routed to.
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

### Only records dividends actually paid, not merely declared

Holding shares before the ex-date makes a user *entitled* to a dividend, but
the routed source can report one that's been declared and already has an
ex-date without it having been paid yet (or even before it's gone ex at
all) — e.g. MSFT's next-quarter row showing up in `research.Dividend` ahead
of time. Recording that immediately would put a future, not-yet-received
payment in the Activity ledger as if it were real income already banked.

So ledger creation is gated on the dividend having actually occurred:
`payment_date <= today`, falling back to `ex_dividend_date <= today` when
`payment_date` is unknown. A dividend that fails this check is simply left
uncreated — since the sync is re-run from scratch each time (idempotent,
keyed on symbol + ex-date), it gets picked up automatically on a later sync
once its payment date has passed.
