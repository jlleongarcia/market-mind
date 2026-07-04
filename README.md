# MarketMind

**Portfolio management and investment analytics, built for real investors.**

MarketMind is a self-hosted Django application for tracking stock portfolios, monitoring dividends, and generating tax-ready gain/loss reports with FIFO lot matching and multi-currency FX support.

![MarketMind](django-pystocks-cerdos.png)

---

## Features

- **Portfolio management** — Create multiple portfolios, track positions across brokers, and monitor real-time valuations with live price feeds.
- **Transaction book** — Record buys, sells, dividends, interest, spin-offs, FX exchanges, deposits, and withdrawals.
- **Live price feed** — Prices fetched from yfinance and cached per symbol, ensuring consistency across all views.
- **Dividend automation** — Sync dividend history from Alpha Vantage (preferred) or yfinance (fallback); qualifying payments are auto-recorded against the right positions, including ones since fully sold. Alpha Vantage also provides declaration/payment-date history, powering accurate dividend growth and Buy Yield calculations — see [DIVIDEND_AUTOMATION.md](DIVIDEND_AUTOMATION.md).
- **Tax reporting** — Per-portfolio P&L reports with FIFO cost-basis matching. Separate stock and FX gain/loss streams as required by most tax authorities.
- **Multi-currency FX book** — Real (EXC) and virtual (SELL / DIV / INT) FX lots tracked with FIFO consumption; gains and losses reported in the portfolio's native currency.
- **FX rate integration** — Currency rates fetched automatically from a self-hosted Frankfurter v2 instance, with weekend/holiday fallback and manual-entry override.
- **Research tools** — Historical price data, fundamental metrics, and company information for any listed symbol.
- **User management** — Google OAuth login, admin approval workflow, and forced password change for temporary credentials.
- **REST API** — Full JSON API with JWT authentication for programmatic access.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.0.1, Django REST Framework |
| Database | PostgreSQL 15 |
| Market data | yfinance, Alpha Vantage (optional) |
| FX rates | Self-hosted Frankfurter v2 |
| Authentication | django-allauth, Google OAuth 2.0 |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Static files | WhiteNoise |
| Containerisation | Docker, Docker Compose |

---

## Quick Start

**Requires Docker and Docker Compose.**

```bash
git clone https://github.com/jlleongarcia/market-mind.git
cd market-mind
cp .env.example .env
make setup
```

Open **http://localhost:8300** — default credentials: `admin` / `admin123`.

---

## Project Structure

```
market-mind/
├── main/              # Django settings, root URLs, middleware
├── portfolio/         # Portfolios, transactions, FX lots, tax reports
│   ├── models.py      # Portfolio, Transaction, FXLot, FXLotConsumption
│   ├── services.py    # FXRateService, FXLotService, TaxReportService
│   └── views.py       # Template views and REST endpoints
├── research/          # Stock search, price cache, market data
├── templates/         # Django HTML templates
├── static/            # CSS and JavaScript
├── docker-compose.yml
├── Dockerfile
└── Makefile
```

---

## Documentation

| Document | Purpose |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Local setup, commands, workflow, and code conventions |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production deployment and Cloudflare configuration |

---

## License

Private and proprietary. All rights reserved.
