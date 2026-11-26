# Wishlist & Alerts

Stop staring at tickers: put companies on a wishlist, describe *your* entry
conditions once, and get one digest each morning (email and/or Telegram) when
they start holding — for wishlist companies, your holdings, or both.

These alerts report conditions you defined. They are not investment advice.

---

## Daily pipeline

| Time | Job | What it does |
|---|---|---|
| 9:00 | `scripts/update_financial_metrics.sh` | Refreshes `FinancialMetrics` for every active stock, now including `current_price`, `week52_low/high`, `current_yield` and `avg_yield_5y` from one ~6y yfinance history pull per stock |
| 9:30 | `scripts/run_alerts.sh` → `manage.py run_alerts` | Evaluates every user's rules + warnings against the DB and sends one digest per user |

Register the second one with `make setup-cron-alerts`. Logs go to `backups/alerts.log`.

The alert engine only reads the DB — no yfinance calls — so it's fast and the
rule editor's **Test now** can use the same code safely. Everything is based on
the previous market close; this is a daily system, not real-time.

`manage.py run_alerts --dry-run [--user NAME]` prints what would fire without
saving state or sending anything.

## Metrics available to rules

| Metric | Meaning |
|---|---|
| Yield vs its 5y average (%) | `(current_yield / avg_yield_5y − 1) × 100`. `> 0` = any amount above average; `> 10` = at least 10% above |
| 52-week range percentile | `0` = at the 52-week low, `100` = at the high. `≤ 33` = low third of the range |
| Dividend yield (%) | `dividend_rate / price` |
| Price | Last close, stock's own currency |
| Price vs my average cost (%) | Quantity-weighted across all your portfolios; owned stocks only |
| P/E (trailing), Payout ratio, FCF payout ratio, Chowder number, 5y dividend growth | Straight from `FinancialMetrics` |

Yields use a **forward basis**, the same as Buy Yield: the latest regular
dividend × payments per year ÷ price. That makes them read about 1.5–3.5%
higher than websites that use trailing-twelve-months yields. It's
deliberate, so that current yield and the 5y average compare like-for-like.
The full method and the measured differences are in
[DIVIDEND_AUTOMATION.md](DIVIDEND_AUTOMATION.md#current-yield--5-year-average-yield-forward-basis).

## Rules

A rule = conditions combined with **ALL** or **ANY**, a **scope** (wishlist,
portfolio, both, or one symbol) and a **cooldown**.

- **Fires on the transition only.** `AlertState` remembers whether a rule
  currently holds for each symbol; it fires when that flips false → true, not
  every day it stays true.
- **Cooldown** (default 7 days): after firing, a rule stays silent for that
  symbol for this long even if the conditions flicker off and on.
- **Missing or stale data never counts as a match.** Metrics older than 5 days
  (or price data older than 5 days) are treated as unknown. A rule that can't
  be evaluated leaves its state untouched, so a one-day data gap neither
  re-arms nor fires it, and the digest lists it under "couldn't evaluate."
- Editing a rule's conditions resets its state, so it re-evaluates fresh.

For owned stocks, every alert adds your current yield vs your best buy yield
(across all portfolios). Wishlist notes are quoted back in the alert.

## Built-in warnings (owned stocks)

Toggle these in **Account → Notification settings**:

| Warning | Fires when | Reported |
|---|---|---|
| Dividend cut | Latest regular payment (split-adjusted, includes already-declared future ones) is >1% below the previous, within the last 120 days | Once per cut |
| Dividend freeze | The last *frequency + 1* regular payments are equal (5× quarterly, 13× monthly, 3× semi-annual, 2× annual) — no raise in over a year | Once per streak |
| Payout / FCF payout > 100% | The dividend isn't covered | On the transition, 30-day cooldown |
| Ex-dividend soon (off by default) | An ex-date falls within N days | Once per ex-date |

Cut and freeze are skipped for ETFs, whose distributions vary by design.

## Delivery

One digest per user per run, on each enabled channel. Events that fail to send
(e.g. SMTP down) are retried by the next runs for up to 3 days.

**Email** uses the existing `EMAIL_*` settings.

**Telegram** (optional):

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`, then copy the token and the bot's username.
2. Add to `.env`: `TELEGRAM_BOT_TOKEN=...` and `TELEGRAM_BOT_USERNAME=...` (without the `@`), then restart.
3. Each user: **Notification settings → Connect Telegram** → open the link → press **Start** → **Verify**.

Linking polls the Bot API's `getUpdates` for the `/start <token>` message, so
no webhook or extra public endpoint is needed. Don't point a webhook at the bot:
`getUpdates` stops working when one is set.
