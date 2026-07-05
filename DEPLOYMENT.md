# Deployment

This guide covers deploying MarketMind in a production environment, including HTTPS reverse proxy configuration and the FX rate service.

---

## Environment Configuration

Copy `.env.example` to `.env` and update the following for production:

```env
DEBUG=False
SECRET_KEY=<generate a secure random key — see below>
ALLOWED_HOSTS=your-domain.com

# Required when behind an HTTPS proxy (Cloudflare, Nginx, etc.)
CSRF_TRUSTED_ORIGINS=https://your-domain.com

# Self-hosted Frankfurter v2 for FX rates
FX_RATE_SERVICE_URL=http://<host>:<port>

# Email notifications (optional — see "Email Notifications (SMTP)" below)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=user@example.com
EMAIL_HOST_PASSWORD=<password>
DEFAULT_FROM_EMAIL=user@example.com
ADMIN_EMAIL=admin@example.com
```

**Generate a secure secret key:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Deployment Steps

```bash
cp .env.example .env
# Edit .env with production values

docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
docker compose exec web python manage.py createsuperuser
```

---

## Cloudflare Tunnel

MarketMind works behind Cloudflare Tunnel with no additional infrastructure. The proxy-aware settings are already in place in `settings.py`:

```python
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
```

The only thing you must configure is `CSRF_TRUSTED_ORIGINS` in `.env`:

```env
CSRF_TRUSTED_ORIGINS=https://marketmind.your-domain.com
```

> **Without this setting, all POST requests through Cloudflare will return 403 Forbidden.** This is Django's CSRF protection rejecting requests whose `Origin` header doesn't match a trusted origin.

After updating `.env`:
```bash
docker compose restart web
```

---

## Dividend Data API Keys (FMP + Alpha Vantage)

MarketMind sources dividend history from two providers, routed by exchange
— see [DIVIDEND_AUTOMATION.md](DIVIDEND_AUTOMATION.md#data-sources) for the
full rationale — falling back to yfinance if both are unavailable. Together
they drive:

- **Dividend growth rates** (1Y and 5Y) shown in the portfolio Income and Fundamentals tabs
- **Estimated payment dates** displayed in the transaction ledger
- **Chowder Number** (dividend yield + 5Y growth rate)
- **Buy Yield** on purchases (`declaration_date`-aware, see DIVIDEND_AUTOMATION.md)

Without either key the app falls back to yfinance, which covers basic
dividend amounts but has limited payment-date history and may produce less
accurate growth calculations.

### Getting free keys

**FMP** (US-listed stocks — required for those to get full history):
1. Go to [financialmodelingprep.com](https://site.financialmodelingprep.com/) and create a free account.
2. The free tier allows 250 API calls per day.
3. Add the key to `.env`: `FMP_API_KEY=your_key_here`

**Alpha Vantage** (everything else, e.g. LSE-listed stocks — FMP's free tier blocks non-US symbols outright):
1. Go to [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key) and request a free key.
2. The free tier allows 25 API calls per day — plenty once only non-US symbols are routed here.
3. Add the key to `.env`: `ALPHA_VANTAGE_API_KEY=your_key_here`

Then restart the web container:

```bash
docker compose restart web
```

### What degrades without a key

| Feature | With FMP/Alpha Vantage | Without (yfinance fallback) |
|---|---|---|
| Dividend history | Full history with payment dates | Amounts only, no payment dates |
| Payment date in ledger | Exact date | Estimated (ex-date used as proxy, marked `ex`) |
| Div Growth 1Y / 5Y | Accurate CAGR from complete history | May be inaccurate or unavailable |
| Chowder Number | Reliable | May be missing or wrong |

> If you only set one key, that provider only covers the exchanges it's
> routed for (US-listed for FMP, everything else for Alpha Vantage) —
> stocks routed to the missing key's provider fall back to yfinance. If you
> have a large portfolio and hit a provider's daily cap during a sync, the
> app automatically falls back to yfinance for the remaining tickers.

---

## Email Notifications (SMTP)

MarketMind sends two kinds of transactional email as part of the manual
account-approval flow (`research/adapters.py`, `research/views.py`,
`research/models.py`):

- **New registration request** → sent to the admin (regular sign-up and
  Google OAuth sign-up both trigger this).
- **Approved / rejected** → sent to the user once an admin actions their
  request from the Django admin panel (`UserRegistrationRequest.approve` /
  `.reject`).

**Without SMTP configured, `EMAIL_BACKEND` defaults to Django's console
backend** — emails are written to the web container's stdout instead of
being delivered anywhere. Fine for local development (`docker compose logs
web` to read them), not for production.

### Setup

Any standard SMTP provider works — Gmail, SendGrid, Mailgun, your domain's
own mail server, etc. Gmail is the simplest option for a small/personal
deployment:

1. Enable **2-Step Verification** on the Google account (required for App
   Passwords): [myaccount.google.com/security](https://myaccount.google.com/security).
2. Generate an **App Password** at
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   — pick "Mail" as the app. This is a 16-character password used **instead
   of** your normal Gmail password; Gmail rejects SMTP logins with the
   regular account password.
3. Add to `.env`:
   ```env
   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=you@gmail.com
   EMAIL_HOST_PASSWORD=<16-character App Password, no spaces>
   DEFAULT_FROM_EMAIL=you@gmail.com
   ADMIN_EMAIL=you@gmail.com
   ```
   For a different provider, swap in its SMTP host/port/credentials — the
   Django settings are the same regardless of provider.
4. Restart the web container:
   ```bash
   docker compose restart web
   ```
5. Send a test email to confirm delivery:
   ```bash
   docker compose exec web python manage.py sendtestemail you@gmail.com
   ```
   If it doesn't arrive, check `docker compose logs web` for an SMTP
   authentication or connection error before assuming it's a spam-folder
   issue.

**`ADMIN_EMAIL` is only a fallback** — registration-request notifications go
to the first superuser account's email address if one is set, and only fall
back to `ADMIN_EMAIL` when no superuser has an email configured.

---

## FX Rate Service

MarketMind uses a self-hosted [Frankfurter v2](https://github.com/hakanensari/frankfurter) instance for currency conversion. The service is queried at `GET /v2/rate/{from}/{to}?date=YYYY-MM-DD`.

Deploy Frankfurter alongside the main app (e.g. on port 8301) and point to it via `.env`:

```env
FX_RATE_SERVICE_URL=http://<host>:8301
```

If a rate is unavailable (weekend, bank holiday), the app automatically retries up to five prior business days. If still unavailable, the transaction form shows a warning and allows manual rate entry.

---

## Static Files

Static files are served by WhiteNoise — no Nginx or CDN required. Always run `collectstatic` after pulling frontend changes:

```bash
docker compose exec web python manage.py collectstatic --noinput
```

---

## Updating

```bash
git pull origin main
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
```

---

## CI/CD — Multiarch Image Build

The workflow at `.github/workflows/config.yml` builds a multiarch Docker image (`linux/amd64` + `linux/arm64`) and pushes it to GitHub Container Registry (GHCR) on every manual trigger (or on push to `main` when uncommented).

### Required secret: `market_mind_GHCR`

The workflow authenticates to GHCR using a GitHub Personal Access Token stored as a repository secret. To set it up:

**1. Create a Personal Access Token**

GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**

| Field | Value |
|---|---|
| Note | MarketMind GHCR |
| Expiration | Your preference (90 days recommended) |
| Scopes | `write:packages`, `read:packages`, `delete:packages`, `repo` |

Copy the token — it is only shown once.

**2. Add it as a repository secret**

GitHub → **jlleongarcia/market-mind** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Field | Value |
|---|---|
| Name | `market_mind_GHCR` |
| Secret | Paste the token from step 1 |

**3. Trigger the workflow**

Go to **Actions** → **CI/CD Build MultiArch** → **Run workflow**.

The built image is pushed to:
```
ghcr.io/jlleongarcia/market-mind:latest
ghcr.io/jlleongarcia/market-mind:<git-sha>
```

### Renewing an expired token

Repeat step 1 to generate a new token, then update the secret value in step 2. No workflow changes are needed.

---

## Scheduled Jobs

Two idempotent daily cron jobs, registered via `make setup-cron` /
`make setup-cron-dividends`:

| Time | Script | Purpose |
|---|---|---|
| 8:00 AM | `scripts/backup_db.sh` | Encrypted daily DB backup (see `BACKUP_OFFSITE.md` for the off-site copy) |
| 8:30 AM | `scripts/backfill_dividend_data.sh` | Backfills dividend `declaration_date` from FMP/Alpha Vantage and recomputes Buy Yield — see `DIVIDEND_AUTOMATION.md` |

Both are safe to rerun manually and log to `backups/*.log`.

---

## Monitoring

```bash
make status       # Container status
make logs-web     # Web container logs
make logs-db      # Database logs
```
