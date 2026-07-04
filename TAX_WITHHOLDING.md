# Dividend Withholding Tax

How MarketMind estimates the origin-country tax withheld on your dividends —
a personal, per-user calculator, not a general tax product. It only computes
tax **at the source** (the country the dividend is paid from) — never your
own country's tax on foreign income, which is a separate personal-filing
concern outside this tool's scope.

---

## The model, in one sentence

`Transaction.tax` (for manually-entered `DIV` transactions) and
`portfolio.Dividend.tax` (for the auto-synced ledger) are both computed as
`gross dividend amount × your rate for this stock`, where "your rate" comes
from `PortfolioCalculationService.get_withholding_tax_rate(user, stock)` —
and is always just a normal editable field afterward, never re-locked.

## Where the rate comes from

Three layers, most specific wins:

1. **A stock-specific rule** (`TaxWithholdingRule.symbol` set) — "I know this
   exact stock is taxed at X% for me, regardless of the general country rule."
2. **A country + entity-type rule** — your general assumption for e.g. "US
   regular corp dividends."
3. **A country + `REGULAR` rule**, as a fallback when the stock is an
   MLP/REIT but you haven't set up an entity-specific rule for that country.
4. Nothing matches → rate is `None`, `tax` stays `0`. The tool won't guess.

All of this is **per-user** (`TaxWithholdingRule.user`) — two people holding
the same stock can have completely different rates (different tax residency,
treaty status, W-8BEN filing). Nothing is shared or global; there's no admin
seed data, no defaults baked into code for "everyone."

Manage your own rules at **Account → Tax settings**
(`portfolio:tax_settings_view`) — add a general country/entity-type rule, or
override a specific stock, and delete anytime.

## Entity type — why MLPs and REITs need their own rate

`research.Stock.entity_type` (`REGULAR` / `MLP` / `REIT`) is an *objective*
classification, not personal — a stock either is an MLP or it isn't,
regardless of who's asking. Auto-detected only when a stock is first created
(`infer_entity_type` in `research/services.py`) and never touched again
afterward, so a manual correction always sticks:

- Name contains "L.P." → **MLP** (e.g. **EPD**, "Enterprise Products
  Partners L.P.") — US MLP distributions are subject to a much higher
  withholding rate (effectively-connected income, not treaty-reducible) than
  a regular corp dividend.
- Sector is "Real Estate" → **REIT** (e.g. **AMT**, American Tower) — REIT
  dividend withholding is genuinely treaty/case-specific; don't assume it
  matches a regular corp dividend without checking.
- Otherwise → **REGULAR**.

Confirmed working end-to-end: a test EPD dividend (10 shares × $2.00 = $20
gross) computed **$7.40 tax** at the 37% MLP rate; a test MSFT dividend (5 ×
$1.00 = $5 gross) computed **$0.75** at the 15% regular rate.

## What's seeded today (one real user, your own defaults)

| Country | Entity type | Rate | Basis |
|---|---|---|---|
| United States | REGULAR | 15% | Standard treaty portfolio-dividend rate with W-8BEN on file |
| United States | MLP | 37% | Effectively-connected income, not treaty-reducible |
| United States | REIT | 15% | |
| United Kingdom | REGULAR | 0% | UK doesn't withhold on dividends, for anyone |
| Ireland | REGULAR | 25% | Standard Irish DWT rate |
| Australia | REGULAR | 0% | |

These are *your* starting assumptions, not universal truths — franking
percentages, treaty status, and paperwork-on-file all vary case by case.
Add more countries yourself in Tax settings as they come up; nothing requires
a code change.

## Live preview in the transaction form

When adding a `DIV` transaction, the "Tax Withheld" field auto-fills as you
type the symbol/quantity/price — computed entirely client-side (no AJAX
round-trip) from a small JSON blob embedded in the page: every tracked
stock's `{country, entity_type}` plus your own `TaxWithholdingRule` rows
(`_tax_lookup_context` in `portfolio/views.py`). It mirrors
`get_withholding_tax_rate`'s exact precedence. Still just a preview — edit
it before submitting if this specific payment differs (e.g. a partially-
franked Australian dividend).

`INT` (interest) transactions have the same `tax` field but **no
auto-compute** — there's no clean "origin instrument" for broker cash
interest the way a dividend has a source stock, so it's purely manual entry.

## Auto-synced dividends (`auto_record_dividends`)

Computed once at creation time from the portfolio owner's rate, same as
manual `DIV` transactions — see `DIVIDEND_AUTOMATION.md` for how the ledger
sync itself works (symbol sourcing, entitlement rules, etc). This tax
computation is independent of that — it just reuses
`get_withholding_tax_rate` at the point each `Dividend` row is created.
