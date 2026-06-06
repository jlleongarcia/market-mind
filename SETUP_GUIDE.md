# Stonks Portfolio & Research App

A Django-based web application for stock market research and portfolio management.

## 🚀 Features

- **Research (Free Tier)**: Search for any stock and view metrics and historical data
- **Portfolio (Premium)**: Create and manage personal portfolios with dividend tracking
- **Dockerized**: Fully containerized with Docker and docker-compose
- **REST API**: Built with Django REST Framework
- **PostgreSQL**: Production-ready database

## 📋 Requirements

- Docker
- Docker Compose

## 🛠️ Setup & Installation

### 1. Clone the repository
```bash
cd /home/jlleongarcia/Documents/Github_projects/py-stonks-cerdos
```

### 2. Create environment file
```bash
cp .env.example .env
```

Edit `.env` with your settings if needed.

### 3. Build and start containers
```bash
docker-compose up --build -d
```

### 4. Access the application

- **Web App**: http://localhost:8300
- **Admin Panel**: http://localhost:8300/admin
  - Username: `admin`
  - Password: `admin123`

### 5. Database
- **PostgreSQL**: localhost:5433
- **Database**: stonks_db
- **User**: stonks_user
- **Password**: stonks_password

## 📁 Project Structure

```
.
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Web app container
├── scripts/                   # Shell scripts
│   ├── entrypoint.sh         # Container startup script
│   └── backup_db.sh          # Daily DB backup (cron)
├── manage.py                  # Django management
├── requirements.txt           # Python dependencies
├── stonks_project/           # Django project settings
│   ├── settings.py           # Main configuration
│   └── urls.py               # URL routing
├── research/                 # Research app (free tier)
│   ├── models.py            # Data models
│   ├── views.py             # API views
│   ├── serializers.py       # API serializers
│   └── urls.py              # App URLs
└── portfolio/                # Portfolio app (premium)
    ├── models.py            # Data models
    ├── views.py             # API views
    ├── serializers.py       # API serializers
    └── urls.py              # App URLs
```

## 🐳 Docker Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f web

# Restart services
docker-compose restart

# Rebuild containers
docker-compose up --build -d

# Run migrations
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Access Django shell
docker-compose exec web python manage.py shell
```

## 🔧 Development

### Local Development (without Docker)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver 8300
```

## 📊 API Endpoints

### Research (Public)
- `GET /api/research/stocks/` - List stocks
- `GET /api/research/stocks/{symbol}/` - Stock details
- `GET /api/research/stocks/{symbol}/metrics/` - Stock metrics

### Portfolio (Authenticated)
- `GET /api/portfolio/` - User portfolios
- `POST /api/portfolio/` - Create portfolio
- `GET /api/portfolio/{id}/` - Portfolio details
- `POST /api/portfolio/{id}/transactions/` - Add transaction

### Authentication
- `POST /api/token/` - Obtain JWT token
- `POST /api/token/refresh/` - Refresh JWT token

## 🔑 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Debug mode | `True` |
| `SECRET_KEY` | Django secret key | (auto-generated) |
| `DATABASE_NAME` | PostgreSQL database | `stonks_db` |
| `DATABASE_USER` | Database user | `stonks_user` |
| `DATABASE_PASSWORD` | Database password | `stonks_password` |
| `DATABASE_HOST` | Database host | `db` |
| `DATABASE_PORT` | Database port | `5432` |

## 📦 Technology Stack

- **Backend**: Django 5.0.1
- **API**: Django REST Framework 3.14.0
- **Database**: PostgreSQL 15
- **Stock Data**: yfinance 0.2.37
- **Containerization**: Docker & Docker Compose
- **Data Processing**: pandas, numpy

## 🎯 Next Steps

1. Implement stock data fetching with yfinance
2. Create frontend interface
3. Add user authentication UI
4. Implement portfolio analytics
5. Add dividend tracking features
6. Create data visualization charts
7. Add email notifications
8. Implement caching with Redis

## 📝 License

This project is private and proprietary.
