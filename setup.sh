#!/bin/bash

# ============================================
# MarketMind Quick Setup Script
# ============================================

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    🧠 MarketMind                             ║"
echo "║            Quick Setup Script                                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    echo "✅ .env file created!"
    echo ""
    echo "⚠️  Please review and update .env file with your settings"
    echo ""
else
    echo "✅ .env file already exists"
    echo ""
fi

# Check if Make is installed
if command -v make &> /dev/null; then
    echo "✅ Make is installed - you can use make commands!"
    echo ""
    read -p "🚀 Do you want to run 'make setup' now? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        make setup
    else
        echo ""
        echo "📋 To set up later, run: make setup"
        echo "📋 To see all commands: make help"
    fi
else
    echo "⚠️  Make is not installed (optional)"
    echo ""
    read -p "🚀 Do you want to run manual setup now? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo ""
        echo "📦 Building Docker containers..."
        docker-compose build
        echo ""
        echo "🔧 Starting services..."
        docker-compose up -d
        echo ""
        echo "⏳ Waiting for database to be ready..."
        sleep 10
        echo ""
        echo "📊 Running migrations..."
        docker-compose exec -T web python manage.py migrate
        echo ""
        echo "📁 Collecting static files..."
        docker-compose exec -T web python manage.py collectstatic --noinput
        echo ""
        echo "✅ Setup complete!"
        echo ""
        echo "🌐 Access the application:"
        echo "   Landing Page: http://localhost:8300"
        echo "   Admin Panel:  http://localhost:8300/admin"
        echo "   API Root:     http://localhost:8300/api"
        echo ""
        echo "🔐 Default credentials:"
        echo "   Username: admin"
        echo "   Password: admin123"
        echo ""
        echo "🔧 Setting up git hooks..."
        ./.githooks/setup-hooks.sh
        echo ""
        echo "⏰ Setting up daily DB backup cron job..."
        chmod +x ./scripts/backup_db.sh
        make setup-cron
        echo ""
    else
        echo ""
        echo "📋 To set up later, run:"
        echo "   docker-compose build"
        echo "   docker-compose up -d"
        echo "   docker-compose exec web python manage.py migrate"
        echo "   docker-compose exec web python manage.py collectstatic --noinput"
    fi
fi

echo ""
echo "🎉 Setup script finished!"
echo ""
