# Dividend Automation

How MarketMind computes **Buy Yield** on purchases, keeps that calculation
accurate over time, and records dividend income against positions —
including ones that have since been fully sold.

For estimating origin-country withholding tax on those dividends, see
[TAX_WITHHOLDING.md](TAX_WITHHOLDING.md) — a separate, per-user concern
layered on top of the ledger described here.

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

Accumulating ETFs (e.g. `CSPX.L`) reinvest distributions internally rather
than paying cash dividends — zero `Dividend` rows for one of these is the
correct, expected state, not a sync gap.

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
  single request per symbol, including `declaration_date`/`payment_date`,
  back to the 1990s for most tickers (deeper than Alpha Vantage). **Blocks
  non-US symbols outright** even with a paid-for key ("Premium Query
  Parameter"), which is why non-US stocks are routed to Alpha Vantage
  instead — this isn't optional. It **also premium-gates a subset of
  well-known US tickers the same way** (e.g. `CAT`, `HON`, `MO`, `WDS` —
  HTTP 402, `"Premium Query Parameter: Special Endpoint..."`, not a rate
  limit), with **no way to predict which symbols in advance** short of
  calling the endpoint live — see the FMP-failure fallback below for how
  those are still recovered. Free-tier quota: 250 requests/day, comfortably
  covering the whole US-listed stock list with room to spare.
- **Alpha Vantage `DIVIDENDS` endpoint (everything else — LSE etc.)** — same
  single-request-per-symbol shape. Has ex-dividend dates and amounts going
  back decades, but `declaration_date`/`record_date`/`payment_date` are only
  populated from **~2020 onward** — a hard boundary in Alpha Vantage's own
  data (present on both free and premium tiers), not a quota effect. Older
  dividends fall back to the ex-date-only rule for Buy Yield. Free-tier
  quota: 25 requests/day, dedicated to the handful of non-US symbols plus
  the FMP-failure fallback below.
- **yfinance (universal fallback)** — used only when the routed primary
  source is unavailable (missing key, rate limit, premium-gated, request
  error). Has no `declaration_date` at all, so any dividend saved this way
  needs a later backfill pass before Buy Yield can use rule 1 for it.

Both primary sources fetch a symbol's **entire** dividend history in **one**
request — there's no cheaper way to get `declaration_date`, `ex_date`, and
`payment_date`, so this is already the minimum possible call count per
symbol per refresh.

**Some symbols have no dividend history on either source, permanently —
confirmed, not a retry-forever situation.** `IDUS.L`, `DGRW.L`, and
`FUSD.L` (all LSE) return a clean, non-error empty response from Alpha
Vantage, and FMP can't help either (non-US block). `backfill_dividend_declaration_dates`
detects this and marks every eligible row `declaration_date_checked`
immediately instead of retrying forever (see below).

**Practical coverage ceiling, given the above:** for the ~2020-onward window
(where both sources can realistically have data), regular equities/ETFs
land around **~90% `declaration_date` / ~86% `payment_date`** coverage. The
remaining gaps are individual dividend events where both Alpha Vantage and
FMP independently have no record of a declaration or payment date — a hole
in the underlying source data, not a processing backlog. Older dividend
history often has ex-date and amount but no `declaration_date`/`payment_date`
at all (falls back to the ex-date-only rule for Buy Yield), and that share
is expected to stay low permanently given Alpha Vantage's 2020 boundary.

**Other providers evaluated, both rejected:** Finnhub gates *both* of its
dividend endpoints behind a paid plan, for any market — confirmed via their
own published API schema (`"premium": "Premium Access Required"`), not just
marketing copy. Tiingo's corporate-actions/dividends endpoint returns
`403 Forbidden` on a real free-tier key (the same key works fine on
Tiingo's free EOD-prices endpoint) — their docs say this endpoint needs
discretionary Beta/enterprise approval from support, not a standard
free-tier grant. Neither is used anywhere in this codebase. FMP's own
Terms of Service (redistribution/storage clauses, personal- vs.
commercial-use terms) haven't been reviewed the same way — worth doing
before leaning on it further.

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

  `payment_date` backfill is a free side effect, not an extra request: both
  providers already return it alongside `declaration_date` in the same
  response, so filling it costs nothing extra. Strictly additive — only
  fills rows where `payment_date` is currently `NULL`, never overwrites an
  existing value. Unlike `declaration_date`, there's no separate "confirmed
  absent" bookkeeping for it: whether a stock gets re-attempted at all is
  governed entirely by `declaration_date_checked`, so a row missing only
  `payment_date` (with `declaration_date` already known) won't be revisited
  by this command specifically for that gap — the fuller `save_dividends`
  sync path would pick it up instead.

  **FMP-failure fallback (this command only):** if an FMP-routed stock's
  request fails for any reason — including FMP's per-symbol premium gate,
  not just a genuine rate limit — this command retries via Alpha Vantage
  before giving up (e.g. `CAT`/`HON`/`MO`/`WDS`, premium-gated on FMP but
  fully available on Alpha Vantage). Stocks are processed
  **Alpha-Vantage-primary (non-US) first**, specifically so this fallback's
  spending never starves the handful of genuinely AV-only symbols of their
  own quota. Deliberately *not* shared with `save_dividends`'s ordinary
  sync path: this cron runs sequentially and throttled by `--delay`, so
  it's safe to spend Alpha Vantage's near-entirely-unused spare quota here,
  whereas `save_dividends` can run from parallel, uncoordinated contexts
  (e.g. `auto_record_dividends`'s `ThreadPoolExecutor`) where the same
  fallback could reintroduce the quota contention the FMP/Alpha Vantage
  split was built to fix in the first place.

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
  answers with a clean, empty history, every eligible row for that stock is
  marked checked immediately, rather than resurfacing in the backlog every
  single day forever and silently eating into whichever source's quota it's
  routed to.
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

## Premium Alpha Vantage blitz (optional, not cron)

A paid Alpha Vantage key (75 req/min, no daily cap) unlocks a faster,
broader one-off sweep than the free-tier daily cron can do — useful for
quickly clearing a large backlog rather than waiting on the 25/day cap over
many days. `backfill_dividend_dates_premium` (+
`scripts/backfill_dividend_data_premium.sh`) is a **separate,
self-contained tool** for this — it duplicates the small amount of Alpha
Vantage fetch/parse logic it needs rather than importing from
`research/services.py`, so it never touches the free-tier key, the daily
cron command, or anything else already in place. Requires
`ALPHA_VANTAGE_PREMIUM_API_KEY` in `.env`; inert without it. Not registered
in cron or the Makefile — run manually as needed.

Three deliberate differences from the daily cron command:
- **Processes every stock unconditionally** (or a `--symbols` subset),
  ignoring `declaration_date_checked` — the daily cron skips any stock
  that's already fully "resolved," even if it's still missing
  `payment_date`, which only gets backfilled as a side effect of a stock
  the daily cron happens to revisit.
- **Alpha Vantage only, no FMP routing** — pointless to route around
  Alpha Vantage's limits when a premium key removes them.
- **No `2020-01-01` coverage-start boundary** — that boundary exists on the
  free-tier command purely to avoid wasting scarce quota on symbols with no
  realistic chance of a match. With the cap effectively gone, there's no
  reason to skip older rows; if Alpha Vantage genuinely has nothing for
  them, the update simply matches zero rows, same as always.

Because it's Alpha Vantage-only, it can't recover data that only exists on
FMP's side (e.g. deep `payment_date` history reached via FMP's longer
lookback) — the ceiling described in `Data sources` applies regardless of
which Alpha Vantage tier is used.

```bash
./scripts/backfill_dividend_data_premium.sh                      # every stock
./scripts/backfill_dividend_data_premium.sh --symbols AAPL MSFT  # subset
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
all) — e.g. a next-quarter row showing up in `research.Dividend` ahead of
time. Recording that immediately would put a future, not-yet-received
payment in the Activity ledger as if it were real income already banked.

So ledger creation is gated on the dividend having actually occurred:
`payment_date <= today`, falling back to `ex_dividend_date <= today` when
`payment_date` is unknown. A dividend that fails this check is simply left
uncreated — since the sync is re-run from scratch each time (idempotent,
keyed on symbol + ex-date), it gets picked up automatically on a later sync
once its payment date has passed.
