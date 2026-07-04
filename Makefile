.PHONY: help setup build up down restart logs clean test migrate makemigrations shell superuser collectstatic

# Default target
help:
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║                    🧠 MarketMind                             ║"
	@echo "║            Intelligent Stock Market Insights                 ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Available commands:"
	@echo ""
	@echo "  make setup          - Complete project setup (first time)"
	@echo "  make build          - Build Docker containers"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make logs           - View logs from all services"
	@echo "  make logs-web       - View web service logs"
	@echo "  make logs-db        - View database logs"
	@echo "  make clean          - Stop and remove all containers"
	@echo ""
	@echo "  make migrate        - Run database migrations"
	@echo "  make makemigrations - Create new migrations"
	@echo "  make shell          - Open Django shell"
	@echo "  make superuser      - Create superuser"
	@echo "  make collectstatic  - Collect static files"
	@echo ""
	@echo "  make test           - Run tests"
	@echo "  make bash           - Open bash in web container"
	@echo "  make psql           - Open PostgreSQL shell"
	@echo ""
	@echo "  make reset          - Complete reset (destructive!)"
	@echo "  make status         - Show running containers"
	@echo ""

# Complete setup for first time users
setup:
	@echo "🚀 Setting up MarketMind..."
	@echo ""
	@echo "📦 Step 1/5: Building Docker containers..."
	docker-compose build
	@echo ""
	@echo "🔧 Step 2/5: Starting services..."
	docker-compose up -d
	@echo ""
	@echo "⏳ Step 3/5: Waiting for database to be ready..."
	@sleep 10
	@echo ""
	@echo "📊 Step 4/5: Running migrations..."
	docker-compose exec -T web python manage.py migrate
	@echo ""
	@echo "📁 Step 5/5: Collecting static files..."
	docker-compose exec -T web python manage.py collectstatic --noinput
	@echo ""
	@echo "✅ Setup complete!"
	@echo ""
	@echo "🌐 Access the application:"
	@echo "   Landing Page: http://localhost:8300"
	@echo "   Admin Panel:  http://localhost:8300/admin"
	@echo "   API Root:     http://localhost:8300/api"
	@echo ""
	@echo "🔐 Default credentials:"
	@echo "   Username: admin"
	@echo "   Password: admin123"
	@echo ""
	@echo "📝 Note: Superuser is automatically created on first run"
	@echo ""

# Build containers
build:
	@echo "🔨 Building Docker containers..."
	docker-compose build

# Start services
up:
	@echo "🚀 Starting services..."
	docker-compose up -d
	@echo "✅ Services started!"
	@echo "🌐 Application: http://localhost:8300"

# Stop services
down:
	@echo "⏹️  Stopping services..."
	docker-compose down
	@echo "✅ Services stopped!"

# Restart services
restart:
	@echo "🔄 Restarting services..."
	docker-compose restart
	@echo "✅ Services restarted!"

# View logs
logs:
	docker-compose logs -f

logs-web:
	docker-compose logs -f web

logs-db:
	docker-compose logs -f db

# Clean up
clean:
	@echo "🧹 Cleaning up containers and volumes..."
	docker-compose down -v
	@echo "✅ Cleanup complete!"

# Complete reset (DESTRUCTIVE!)
reset:
	@echo "⚠️  WARNING: This will delete all containers, volumes, and data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "🗑️  Removing all containers, volumes, and data..."; \
		docker-compose down -v; \
		rm -rf staticfiles/*; \
		echo "✅ Reset complete! Run 'make setup' to start fresh."; \
	else \
		echo "❌ Reset cancelled."; \
	fi

# Database migrations
migrate:
	@echo "📊 Running migrations..."
	docker-compose exec web python manage.py migrate
	@echo "✅ Migrations complete!"

makemigrations:
	@echo "📝 Creating new migrations..."
	docker-compose exec web python manage.py makemigrations
	@echo "✅ Migrations created!"

# Django shell
shell:
	@echo "🐚 Opening Django shell..."
	docker-compose exec web python manage.py shell

# Create superuser
superuser:
	@echo "👤 Creating superuser..."
	docker-compose exec web python manage.py createsuperuser

# Collect static files
collectstatic:
	@echo "📁 Collecting static files..."
	docker-compose exec web python manage.py collectstatic --noinput
	@echo "✅ Static files collected!"

# Run tests
test:
	@echo "🧪 Running tests..."
	docker-compose exec web python manage.py test

# Open bash in web container
bash:
	@echo "💻 Opening bash in web container..."
	docker-compose exec web bash

# Open PostgreSQL shell
psql:
	@echo "🐘 Opening PostgreSQL shell..."
	docker-compose exec db psql -U postgres -d marketmind_db

# Show status
status:
	@echo "📊 Container Status:"
	@docker-compose ps

# Development hot reload
dev:
	@echo "🔥 Starting development mode with hot reload..."
	docker-compose up

# Check container health
health:
	@echo "🏥 Checking container health..."
	@docker-compose ps
	@echo ""
	@echo "Database connection test:"
	@docker-compose exec -T web python manage.py check --database default

# Register daily 8am cron job for DB backup (idempotent)
setup-cron:
	@SCRIPT="$$(pwd)/scripts/backup_db.sh"; \
	LOG="$$(pwd)/backups/backup.log"; \
	ENTRY="0 8 * * * $$SCRIPT >> $$LOG 2>&1"; \
	if crontab -l 2>/dev/null | grep -qF "$$SCRIPT"; then \
		echo "✅ Backup cron job already registered"; \
	else \
		(crontab -l 2>/dev/null; echo "# Py-Stocks - daily DB backup (8:00 AM)"; echo "$$ENTRY") | crontab -; \
		echo "✅ Backup cron job registered (daily at 8:00 AM)"; \
	fi

# Register daily 8:30am cron job for dividend declaration_date backfill + buy_yield recompute (idempotent)
setup-cron-dividends:
	@SCRIPT="$$(pwd)/scripts/backfill_dividend_data.sh"; \
	LOG="$$(pwd)/backups/dividend_backfill.log"; \
	ENTRY="30 8 * * * $$SCRIPT >> $$LOG 2>&1"; \
	if crontab -l 2>/dev/null | grep -qF "$$SCRIPT"; then \
		echo "✅ Dividend backfill cron job already registered"; \
	else \
		(crontab -l 2>/dev/null; echo "# Market Mind - daily dividend declaration_date backfill (8:30 AM)"; echo "$$ENTRY") | crontab -; \
		echo "✅ Dividend backfill cron job registered (daily at 8:30 AM)"; \
	fi

# Backup database
backup:
	@echo "💾 Creating database backup..."
	@mkdir -p backups
	@docker-compose exec -T db pg_dump -U $${DATABASE_USER:-marketmind_user} $${DATABASE_NAME:-marketmind_db} > backups/db_backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✅ Backup created in backups/ directory"

# Restore database from backup
restore:
	@echo "⚠️  This will restore database from latest backup"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		LATEST=$$(ls -t backups/*.sql | head -1); \
		echo "📂 Restoring from: $$LATEST"; \
		docker-compose exec -T db psql -U postgres -d marketmind_db < $$LATEST; \
		echo "✅ Database restored!"; \
	fi

# Install Python dependencies (if running locally without Docker)
install:
	@echo "📦 Installing Python dependencies..."
	pip install -r requirements.txt

# Code formatting (if you have black/flake8 installed)
format:
	@echo "✨ Formatting code..."
	docker-compose exec web black .
	@echo "✅ Code formatted!"

lint:
	@echo "🔍 Linting code..."
	docker-compose exec web flake8 .

# Update dependencies
update:
	@echo "🔄 Updating dependencies..."
	docker-compose exec web pip install --upgrade -r requirements.txt
	@echo "✅ Dependencies updated!"
