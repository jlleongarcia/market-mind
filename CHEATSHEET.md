# 🎯 MarketMind Command Cheat Sheet

Quick reference for the most commonly used commands.

## 🚀 Initial Setup

```bash
make setup    # Complete first-time setup
```

## 🏃 Daily Development

### Start/Stop

```bash
make up       # Start all services (background)
make down     # Stop all services
make dev      # Start with live logs (foreground)
make restart  # Restart everything
```

### View Logs

```bash
make logs         # All logs (follow mode)
make logs-web     # Web server logs only
make logs-db      # Database logs only
```

### Access Shells

```bash
make bash     # Container bash shell
make shell    # Django Python shell
make psql     # PostgreSQL shell
```

## 💾 Database Operations

```bash
make migrate           # Apply migrations
make makemigrations    # Create new migrations
make superuser         # Create admin user
make backup            # Backup database
make restore           # Restore from backup
```

## 🔧 Maintenance

```bash
make collectstatic     # Collect static files
make test              # Run tests
make status            # Check containers
make health            # Health check
make clean             # Remove containers
```

## 📋 Full Command List

Run `make help` to see all available commands with descriptions.

## 🔗 Quick Access URLs

After running `make up`:

- **Main Site:** http://localhost:8300
- **Admin Panel:** http://localhost:8300/admin
- **API Root:** http://localhost:8300/api

**Default Login:**
- Username: `admin`
- Password: `admin123`

## 🆘 Common Issues

### Port conflict (8300 in use)
```bash
# Stop containers and check what's using the port
make down
lsof -i :8300
# Or change port in docker-compose.yml
```

### Database not ready
```bash
# Check if db is healthy
make status
make logs-db
```

### Static files not loading
```bash
make collectstatic
make restart
```

### Complete reset
```bash
make reset    # WARNING: Deletes all data!
make setup    # Start fresh
```

---

💡 **Pro Tip:** Keep this file open while developing!
