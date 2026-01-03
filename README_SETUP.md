# Stonks - Stock Market Research & Portfolio Management

A Django-based web application for stock market research and personal portfolio management, containerized with Docker.

## Features

### Free Tier - Research
- 🔍 Search for any stock
- 📊 View detailed stock information
- 📈 Historical price data
- 💹 Financial metrics and ratios
- Built using `yfinance` library

### Premium Tier - Portfolio Management
- 📁 Create multiple portfolios
- 💰 Track buy/sell transactions
- 📊 View current positions
- 💵 Dividend tracking
- 📈 Profit/loss calculations

## Tech Stack

- **Backend**: Django 5.0.1 with Django REST Framework
- **Database**: PostgreSQL 15
- **Stock Data**: yfinance
- **Authentication**: JWT (Simple JWT)
- **Containerization**: Docker & Docker Compose
- **Static Files**: WhiteNoise

## Prerequisites

- Docker
- Docker Compose
- Git

## Quick Start

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd py-stonks-cerdos
```

### 2. Create Environment File

Copy the example environment file and update as needed:

```bash
cp .env.example .env
```

Edit `.env` and update the secret key and other settings:

```env
DEBUG=True
SECRET_KEY=your-super-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_NAME=stonks_db
DATABASE_USER=stonks_user
DATABASE_PASSWORD=stonks_password
DATABASE_HOST=db
DATABASE_PORT=5432
```

### 3. Build and Run with Docker

```bash
# Build the containers
docker-compose build

# Start the services
docker-compose up -d

# Run migrations
docker-compose exec web python manage.py migrate

# Create a superuser
docker-compose exec web python manage.py createsuperuser

# Collect static files
docker-compose exec web python manage.py collectstatic --noinput
```

### 4. Access the Application

- **API**: http://localhost:8000
- **Admin Panel**: http://localhost:8000/admin

## Development Setup (Without Docker)

If you prefer to run without Docker:

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Database

Install and start PostgreSQL, then create the database:

```sql
CREATE DATABASE stonks_db;
CREATE USER stonks_user WITH PASSWORD 'stonks_password';
GRANT ALL PRIVILEGES ON DATABASE stonks_db TO stonks_user;
```

### 4. Run Migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Run Development Server

```bash
python manage.py runserver
```

## API Endpoints

### Research (Free Tier - No Authentication Required)

- `GET /api/research/stocks/search/?q=AAPL` - Search for stocks
- `GET /api/research/stocks/<symbol>/` - Get stock details
- `GET /api/research/stocks/<symbol>/history/?period=1mo` - Get historical data
- `GET /api/research/stocks/<symbol>/metrics/` - Get financial metrics

### Portfolio (Premium Tier - Authentication Required)

- `GET /api/portfolio/portfolios/` - List user portfolios
- `POST /api/portfolio/portfolios/` - Create new portfolio
- `GET /api/portfolio/portfolios/<id>/` - Get portfolio details
- `GET /api/portfolio/portfolios/<id>/positions/` - Get portfolio positions
- `GET /api/portfolio/portfolios/<id>/transactions/` - Get portfolio transactions
- `POST /api/portfolio/transactions/` - Create new transaction
- `GET /api/portfolio/dividends/` - List dividends

### Authentication

- `POST /api/token/` - Obtain JWT token
- `POST /api/token/refresh/` - Refresh JWT token

## Testing the API

### Get Stock Information (No Auth Required)

```bash
curl http://localhost:8000/api/research/stocks/AAPL/
```

### Get Historical Data

```bash
curl http://localhost:8000/api/research/stocks/AAPL/history/?period=1y
```

### Authenticate and Access Portfolio

```bash
# Get token
curl -X POST http://localhost:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'

# Use token to access portfolio
curl http://localhost:8000/api/portfolio/portfolios/ \
  -H "Authorization: Bearer <your_access_token>"
```

## Docker Commands

```bash
# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes (CAUTION: This will delete your database)
docker-compose down -v

# Restart services
docker-compose restart

# Run Django commands
docker-compose exec web python manage.py <command>

# Access Django shell
docker-compose exec web python manage.py shell

# Run tests
docker-compose exec web python manage.py test
```

## Project Structure

```
py-stonks-cerdos/
├── stonks_project/          # Main Django project settings
│   ├── settings.py          # Django settings
│   ├── urls.py             # Main URL configuration
│   ├── wsgi.py             # WSGI configuration
│   └── asgi.py             # ASGI configuration
├── research/               # Free tier - Stock research app
│   ├── models.py          # Stock cache, watchlist models
│   ├── views.py           # API views for stock data
│   └── urls.py            # Research endpoints
├── portfolio/             # Premium tier - Portfolio management app
│   ├── models.py         # Portfolio, Transaction, Position, Dividend models
│   ├── views.py          # API views for portfolio management
│   └── urls.py           # Portfolio endpoints
├── manage.py             # Django management script
├── requirements.txt      # Python dependencies
├── Dockerfile           # Docker image configuration
├── docker-compose.yml   # Docker services configuration
├── .dockerignore       # Docker ignore file
└── .env.example        # Example environment variables
```

## Database Models

### Portfolio App

- **Portfolio**: User investment portfolios
- **Transaction**: Buy/sell transactions
- **Position**: Current stock positions
- **Dividend**: Dividend payments received

### Research App

- **StockCache**: Cached stock data
- **Watchlist**: User watchlists
- **WatchlistItem**: Stocks in watchlists

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DEBUG | Debug mode | True |
| SECRET_KEY | Django secret key | (required) |
| ALLOWED_HOSTS | Allowed hosts | localhost,127.0.0.1 |
| DATABASE_NAME | PostgreSQL database name | stonks_db |
| DATABASE_USER | PostgreSQL username | stonks_user |
| DATABASE_PASSWORD | PostgreSQL password | stonks_password |
| DATABASE_HOST | PostgreSQL host | db |
| DATABASE_PORT | PostgreSQL port | 5432 |

## Next Steps

1. ✅ Basic project structure setup
2. ✅ Docker configuration
3. ✅ Database models
4. ✅ Basic API endpoints
5. 🔄 Implement serializers for models
6. 🔄 Add comprehensive stock data fetching
7. 🔄 Implement portfolio calculations
8. 🔄 Add user permissions and tiers
9. 🔄 Frontend development
10. 🔄 Testing and deployment

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.
