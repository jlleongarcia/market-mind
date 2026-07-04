# Dividend Automation

How MarketMind computes **Buy Yield** on purchases, keeps that calculation
accurate over time, and records dividend income against positions —
including ones that have since been fully sold.

For estimating origin-country withholding tax on those dividends, see
[TAX_WITHHOLDING.md](TAX_WITHHOLDING.md) — a separate, per-user concern
layered on top of the ledger described here.

---

## ⏳ Pending check (delete this section once resolved)

No ETF in the database has `declaration_date` populated yet: **IDUS.L 0/54**,
**DGRW.L 0/39**. Unclear which of two explanations it is:

1. Alpha Vantage's quota has simply never been free when these LSE-listed
   symbols came up in the daily backfill rotation, or
2. Alpha Vantage's `DIVIDENDS` endpoint doesn't cover these symbols at all.

**Task:** check again after the daily cron (8:30 AM) has had a few more
attempts — if either stock still shows 0 after several days where the
backfill log shows it was actually queried (not skipped for quota), that
points to (2). Quick check:

```bash
docker exec market-mind-web-1 python manage.py shell -c "
from research.models import Dividend
for sym in ['IDUS.L','DGRW.L']:
    print(sym, Dividend.objects.filter(stock__symbol=sym, declaration_date__isnull=False).count(),
          '/', Dividend.objects.filter(stock__symbol=sym).count())
"
```

**Also check:** `auto_record_dividends` (`portfolio/services.py:952`) currently
creates an Activity-ledger entry as soon as a `research.Dividend` row exists
and the shares-held-before-ex-date eligibility check passes — there's no
check that the ex-date (let alone `payment_date`) has actually occurred yet.
Since AV can report a dividend that's been declared but hasn't gone ex yet
(seen live, e.g. MSFT's next-quarter row), this means a *future*, not-yet-paid
dividend could already show up in the Activity ledger as if it were real
income received. Task: consider gating ledger creation on `payment_date <=
today` (falling back to `ex_dividend_date <= today` when `payment_date` is
unknown) instead of only checking entitlement, so the ledger reflects
dividends actually paid, not merely ones the user is eligible for.

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
