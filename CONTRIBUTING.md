# Contributing to MarketMind

Thank you for your interest in contributing to MarketMind! This guide will help you get started.

## 🚀 Quick Setup

### Prerequisites
- Docker & Docker Compose
- Git
- Make (optional but recommended)

### First-Time Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/jlleongarcia/PyStocks.git
   cd PyStocks
   ```

2. **Copy environment file**
   ```bash
   cp .env.example .env
   ```

3. **Run the setup** (Using Make - Recommended)
   ```bash
   make setup
   ```

   Or manually:
   ```bash
   docker-compose build
   docker-compose up -d
   docker-compose exec web python manage.py migrate
   docker-compose exec web python manage.py collectstatic --noinput
   ```

4. **Access the application**
   - Landing Page: http://localhost:8300
   - Admin Panel: http://localhost:8300/admin
   - API: http://localhost:8300/api

5. **Default credentials**
   - Username: `admin`
   - Password: `admin123`

## 📝 Development Workflow

### Using Make Commands

View all available commands:
```bash
make help
```

Common commands:
```bash
make up              # Start services
make down            # Stop services
make logs            # View logs
make bash            # Open shell in web container
make migrate         # Run migrations
make test            # Run tests
```

### Without Make

Start services:
```bash
docker-compose up -d
```

View logs:
```bash
docker-compose logs -f
```

Run migrations:
```bash
docker-compose exec web python manage.py migrate
```

## 🔧 Making Changes

### 1. Create a Branch
```bash
git checkout -b feature/your-feature-name
```

### 2. Make Your Changes

#### Backend (Django)
- Models: Edit files in `portfolio/models.py` or `research/models.py`
- Views: Edit files in `portfolio/views.py` or `research/views.py`
- URLs: Edit files in `portfolio/urls.py` or `research/urls.py`

#### Frontend
- Templates: Edit files in `templates/`
- CSS: Edit `static/css/main.css`
- JavaScript: Edit `static/js/main.js`

### 3. Create Migrations (if models changed)
```bash
make makemigrations
make migrate
```

### 4. Test Your Changes
```bash
make test
```

### 5. Commit Your Changes
```bash
git add .
git commit -m "feat: description of your changes"
```

### 6. Push and Create Pull Request
```bash
git push origin feature/your-feature-name
```

## 📋 Commit Message Guidelines

Follow conventional commits:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, etc.)
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

Examples:
```
feat: add stock search functionality
fix: resolve portfolio calculation error
docs: update API documentation
```

## 🧪 Testing

Run all tests:
```bash
make test
```

Run specific test:
```bash
docker-compose exec web python manage.py test portfolio.tests.TestPortfolio
```

## 🐛 Debugging

### View logs
```bash
make logs          # All services
make logs-web      # Web service only
make logs-db       # Database only
```

### Open Django shell
```bash
make shell
```

### Open container bash
```bash
make bash
```

### Database access
```bash
make psql
```

## 📁 Project Structure

```
PyStocks/
├── main/              # Django project settings
│   ├── settings.py    # Main settings
│   ├── urls.py        # URL routing
│   └── views.py       # Core views
├── portfolio/         # Portfolio management app
│   ├── models.py      # Database models
│   ├── views.py       # API views
│   ├── urls.py        # URL routing
│   └── admin.py       # Admin configuration
├── research/          # Stock research app
│   ├── models.py
│   ├── views.py
│   └── urls.py
├── templates/         # HTML templates
│   ├── base.html      # Base template
│   └── index.html     # Landing page
├── static/            # Static files
│   ├── css/
│   └── js/
├── docker-compose.yml # Docker configuration
├── Dockerfile         # Docker image definition
├── Makefile          # Development commands
└── requirements.txt   # Python dependencies
```

## 🔄 Keeping Your Fork Updated

```bash
# Add upstream remote
git remote add upstream https://github.com/jlleongarcia/PyStocks.git

# Fetch latest changes
git fetch upstream

# Merge changes
git checkout main
git merge upstream/main
```

## 📚 Additional Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Docker Documentation](https://docs.docker.com/)

## 💡 Getting Help

If you need help:
1. Check existing issues on GitHub
2. Review the documentation
3. Ask in the discussions section
4. Contact the maintainers

## ⚠️ Common Issues

### Port already in use
```bash
# Change ports in .env file
WEB_PORT=8301
POSTGRES_PORT=5434
```

### Database connection error
```bash
# Restart services
make restart

# Or rebuild
make clean
make setup
```

### Static files not loading
```bash
make collectstatic
```

## 🎉 Thank You!

Your contributions make MarketMind better for everyone. We appreciate your time and effort!
