# Wishlist & Alerts — Manual Test Plan

Checklist for testing issue #21 before merging. Tick items as you go.
All commands run inside the web container (`market-mind-web-1`) via `docker exec`.

> Tip: take a DB backup before step 0 (`make backup`). Everything below writes to the DB.

---

## 0. Deploy

- [x] Image built with the branch and container restarted
- [x] Migrations applied. The container's entrypoint runs `migrate --noinput` on every start, so no manual step is needed. Verify with:
  `docker exec market-mind-web-1 python manage.py showmigrations alerts research` (`alerts 0001_initial` and `research 0016_financialmetrics_price_history` marked `[X]`)
- [x] `docker exec market-mind-web-1 python manage.py migrate --check` exits with no output (nothing pending)
- [x] App loads, no errors in `docker logs market-mind-web-1`
- [x] Sidebar shows a new **Alerts** section: Wishlist, Alert Rules, Alert History
- [x] Account panel shows a **Notification settings** button

## 1. Data layer (new FinancialMetrics fields)

- [x] `docker exec market-mind-web-1 python manage.py update_financial_metrics --all` completes. Note how long it takes compared with before (it now does one extra yfinance call per stock): 2 min, it's fine.
- [ ] Admin → Financial Metrics: `current_price`, `price_date`, `week52_low`, `week52_high`, `current_yield` and `avg_yield_5y` are filled for most stocks
- [ ] Spot-check 3–4 stocks against a site you trust (e.g. Seeking Alpha / Koyfin):
  - [ ] 52-week low/high match
  - [ ] 5y average yield is in the right ballpark (KO ≈ 2.9%, O ≈ 5.2%). Expect it to read **about 1.5–3.5% higher** than trailing-12-month sites. That gap is intended; see DIVIDEND_AUTOMATION.md → "Current yield & 5-year average yield"
- [ ] A stock that split recently (e.g. SCHD 3:1) has a sensible 5y average yield (≈ 3.4%, not ⅓ or 3× that)
- [ ] An ETF has `avg_yield_5y` filled
- [ ] A stock with under 3 years of history has `avg_yield_5y` empty (on purpose)
- [ ] A non-dividend stock: price fields filled, yield fields empty, no crash
- [ ] **Regression:** the **Sync dividends** button on a portfolio still works, and is no slower than before (it skips the history download)
- [ ] **Regression:** portfolio detail, position detail and the combined view still render correctly

## 2. Wishlist

- [ ] Add a stock that's already in the DB (e.g. one you own): it appears instantly with the **owned** badge
- [ ] Add a stock that's never been tracked: it takes a few seconds and arrives with metrics filled
- [ ] Add an invalid symbol (e.g. `ZZZZZZ`): you get an error message and nothing is created
- [ ] Adding the same symbol twice shows "already on your wishlist"
- [ ] Lower-case input (`ko`) is saved as `KO`
- [ ] Edit a note → Save → it persists after a reload
- [ ] Remove → confirm dialog → item gone
- [ ] 52w percentile badge colours: green ≤ 33, red ≥ 67, grey in between
- [ ] "vs avg" is green with a `+` when the yield is above its 5y average
- [ ] Stale or missing data shows the orange reason under the symbol, and "—" in the cells
- [ ] The empty wishlist shows the empty state
- [ ] Narrow (mobile-width) window: the table scrolls sideways and nothing breaks

## 3. Alert rules — editor

- [ ] Each preset button creates a rule and opens it in the editor:
  - [ ] Yield above its 5y average
  - [ ] Low third of its 52-week range
  - [ ] Both combined
- [ ] New rule: add and remove condition rows (you can't remove the last one)
- [ ] The Symbol field only appears when "A single symbol" is selected
- [ ] Single-symbol rule for a stock not yet in the DB: saving fetches it; an invalid symbol shows an error
- [ ] Validation errors keep what you typed:
  - [ ] no name
  - [ ] no conditions
  - [ ] non-number value
- [ ] Edit an existing rule: values show cleanly (`33`, not `33.0000`)
- [ ] Pause / Enable toggles; a paused rule looks faded and is skipped by the engine
- [ ] Delete removes the rule; its past events stay in History, still showing the rule name

## 4. Alert rules — "Test now"

- [ ] Shows "X of Y companies match today", with matches first, then missing data, then non-matches
- [ ] Each metric column is green when it passes and orange when the data is missing
- [ ] Works on an **unsaved** rule (change a value, press Test, without saving)
- [ ] Scopes behave correctly:
  - [ ] Wishlist only
  - [ ] Portfolio only
  - [ ] Both
  - [ ] Single symbol
- [ ] ALL vs ANY gives different results on the same conditions
- [ ] "Price vs my average cost" only has values for owned stocks
- [ ] Testing sends nothing and creates nothing (History stays empty)

## 5. Engine — dry run first

- [ ] `docker exec market-mind-web-1 python manage.py run_alerts --dry-run` lists what would fire for each user, plus "couldn't evaluate" lines
- [ ] `docker exec market-mind-web-1 python manage.py run_alerts --dry-run --user <you>` limits it to you
- [ ] After a dry run: History is still empty, nothing was sent, and Admin → Alert states is empty

## 6. Engine — real run & firing behaviour

- [ ] `docker exec market-mind-web-1 python manage.py run_alerts`: you receive **one** summary (not one per stock) and History shows the events
- [ ] The first run fires every rule that's already true (expected)
- [ ] **Run it again right away: nothing new fires** (the "nothing to send" status)
- [ ] Owned stock alerts include "current yield X% vs your best buy yield Y%"
- [ ] Wishlist alerts quote your note
- [ ] Re-arm test:
  1. Edit a rule so it matches nothing → run (state resets to false)
  2. Edit it back so it matches → run → it fires again

  Note: saving a rule resets its state, so step 2 fires even without step 1.
- [ ] Cooldown test (needs a few days, or the Django shell): a rule that flips false → true within its cooldown does **not** re-fire
- [ ] Missing data: a stock with stale metrics appears under "couldn't evaluate" in the summary and doesn't fire

## 7. Built-in warnings (owned stocks only)

- [ ] **Payout > 100%:** pick an owned stock with a payout ratio above 100% (or temporarily edit it in admin) → run → one PAYOUT_HIGH warning; run again → silent
- [ ] The same stock on the wishlist only (not owned) → no warning
- [ ] **Dividend freeze:** a holding with 5+ equal quarterly payments fires once; running again stays silent
- [ ] **Dividend cut:** a holding whose latest payment dropped within the last 120 days fires once
- [ ] **Variable payers (BHP etc.):** check how noisy the cut warnings are; tell me if the 1% tolerance needs changing
- [ ] ETFs never get cut or freeze warnings
- [ ] **Ex-dividend:** enable it in settings with N days → a holding with an ex-date in that window fires once per ex-date
- [ ] Turning each warning off in settings stops it

## 8. Email

- [ ] Notification settings → **Send test email** arrives (check spam)
- [ ] Digest subject lists the symbols, e.g. `[Market Mind] 3 alerts: KO, O, PEP`
- [ ] The body ends with the History link (`SITE_URL/alerts/history/`) and the disclaimer
- [ ] Untick "Email digest" → run → no email
- [ ] User with no email address: the test button is disabled and runs don't crash

## 9. Telegram

- [ ] Create a bot with @BotFather; set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` (without `@`) in `.env`; restart
- [ ] Before the env vars are set, the settings page shows the "isn't set up on this server" message
- [ ] **Connect Telegram** → open the link → press Start → **Verify** → "connected", and a ✅ message arrives in Telegram
- [ ] Pressing Verify *before* pressing Start shows the "didn't find your /start message" error
- [ ] **Send test** arrives
- [ ] A run delivers the summary to Telegram; History shows the "Telegram" marker
- [ ] A long summary (many alerts) is split into several messages without cutting an alert in half
- [ ] Disconnect → the checkbox is disabled and nothing is sent
- [ ] Second user links their own Telegram → each gets only their own alerts

## 10. Multi-user isolation

- [ ] User B can't see user A's wishlist, rules or history
- [ ] Opening `/alerts/rules/<A's rule id>/edit/` as user B returns 404
- [ ] A's rules never evaluate B's portfolio

## 11. Failure handling

- [ ] Break the SMTP password temporarily → run → event saved, "email failed" in the log → fix it → next run sends the pending events (retried for up to 3 days)
- [ ] Wrong Telegram token → errors are shown, nothing crashes

## 12. Cron

- [ ] `make setup-cron-alerts` registers the job; running it twice says "already registered"
- [ ] `crontab -l` shows the alerts job **after** the 9:00 metrics job
- [ ] The next morning, `backups/alerts.log` shows a run with a line per user
- [ ] The metrics job finished before the alerts job started (compare the timestamps in `financial_metrics.log` and `alerts.log`)

## 13. Docs

- [ ] `ALERTS.md` matches how it actually behaves
- [ ] The README links to it

---

## Notes / bugs found

| # | Area | What happened | Expected |
|---|---|---|---|
| 1 | | | |
