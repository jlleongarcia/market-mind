# Contributing

## Local Setup

**Prerequisites:** Docker with Docker Compose, Git.

```bash
git clone https://github.com/jlleongarcia/market-mind.git
cd market-mind
cp .env.example .env
make setup
```

`make setup` builds the images, starts all services, runs migrations, collects static files, and seeds a default admin account.

| URL | Purpose |
|---|---|
| http://localhost:8300 | Application |
| http://localhost:8300/admin | Django admin |
| http://localhost:8300/api | REST API root |

Default login: `admin` / `admin123`

### Environment Variables

`.env.example` contains sensible defaults for local development. Key variables:

| Variable | Description | Default |
|---|---|---|
| `DEBUG` | Django debug mode | `True` |
| `SECRET_KEY` | Django secret key | Change in production |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `localhost,127.0.0.1,*` |
| `DATABASE_NAME` | PostgreSQL database name | `marketmind_db` |
| `WEB_PORT` | Exposed web port | `8300` |
| `FX_RATE_SERVICE_URL` | Self-hosted Frankfurter v2 base URL | — |
| `CSRF_TRUSTED_ORIGINS` | Required when behind an HTTPS proxy | — |

---

## Command Reference

### Services

```bash
make setup            # First-time setup: build, migrate, seed admin
make up               # Start all services (detached)
make down             # Stop all services
make restart          # Restart all services
make status           # Show running containers
```

### Logs & Shells

```bash
make logs             # All services, follow mode
make logs-web         # Web container only
make logs-db          # Database only
make bash             # Bash inside the web container
make shell            # Django Python shell
make psql             # PostgreSQL interactive session
```

### Database & Assets

```bash
make migrate          # Apply pending migrations
make makemigrations   # Generate migrations from model changes
make superuser        # Create a new admin user
make collectstatic    # Collect assets to STATIC_ROOT
make test             # Run the Django test suite
```

### Maintenance

```bash
make clean            # Remove containers (volumes preserved)
make reset            # Remove containers AND volumes — all data lost
```

---

## Development Workflow

### 1. Branch

Always branch off `main`:

```bash
git checkout -b feat/your-feature-name
```

### 2. Make changes

The codebase is split into two Django apps:

| App | Responsibility |
|---|---|
| `portfolio/` | Portfolios, transactions, FX lots, tax reports, price cache |
| `research/` | Stock search, price history, fundamentals, user management |

Key files:

| File | Purpose |
|---|---|
| `portfolio/models.py` | All data models |
| `portfolio/services.py` | `FXRateService`, `FXLotService`, `TaxReportService`, `PriceCacheService` |
| `portfolio/views.py` | Template views and REST API endpoints |
| `templates/` | Django HTML templates |
| `static/css/` | Styles |
| `static/js/` | JavaScript |
| `main/settings.py` | Django settings, driven by `.env` |

### 3. Migrations

If you change any model:

```bash
make makemigrations
make migrate
```

Review the generated migration before committing. Never edit existing migration files.

### 4. Test

```bash
make test
```

### 5. Commit

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use for |
|---|---|
| `feat:` | New functionality |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `refactor:` | Code restructuring without behaviour change |
| `test:` | Adding or updating tests |
| `chore:` | Dependency updates, build config, maintenance |

Examples:
```
feat: add CSV export for portfolio positions
fix: correct FIFO cost basis on partial sell
refactor: extract FX rate fetch into FXRateService
```

### 6. Pull Request

Push your branch and open a PR against `main`. Describe what changed, why, how to test it manually, and any migration notes.

---

## Code Conventions

**Python** — PEP 8 throughout. Comments only when the *why* is non-obvious from the code itself.

**Templates** — Keep logic in views and services. Template tags and filters are fine; complex conditionals belong in Python.

**Services** — Business logic lives in `services.py`, not in views or models. Models hold data; views handle HTTP; services do everything in between.

**FX logic** — All FX rate fetching goes through `FXRateService.get_rate()`. Never bypass it or hardcode rates.

**Idempotency** — `FXLotService.process_transaction()` checks for existing lots before creating new ones. Preserve this invariant when extending the service.

---

## Troubleshooting

**Port 8300 already in use** — Set `WEB_PORT` in `.env` to a free port, then run `make restart`.

**Database connection error on first startup** — Run `make restart` once; the web container may have started before PostgreSQL was ready.

**Complete reset** (deletes all data):
```bash
make clean && make setup
```
