# 🧠 MarketMind

**Intelligent Stock Market Insights & Portfolio Management**

MarketMind is a comprehensive stock market research and portfolio management platform built with Django and modern web technologies. Designed for both beginner and experienced investors, it combines cutting-edge analytics with real-time market data to help you make informed investment decisions.

## 👥 For Collaborators

**First time here?** Just run this in your terminal:

```bash
git clone https://github.com/jlleongarcia/PyStocks.git
cd PyStocks
make setup
```

Then open http://localhost:8300 - **Done!** 🎉

📖 See [CONTRIBUTING.md](CONTRIBUTING.md) and [QUICKSTART.md](QUICKSTART.md) for detailed setup instructions.

## ✨ Features

- **Real-Time Analytics** - Live market data and advanced charting tools
- **Portfolio Tracking** - Monitor all your investments in one place
- **Stock Research** - Deep dive into company fundamentals and financial statements
- **Smart Alerts** - Custom alerts for price movements and news events
- **Performance Reports** - Comprehensive portfolio analytics and insights
- **Bank-Level Security** - Industry-leading encryption and security protocols

## 🚀 Quick Start for Collaborators

**New to the project?** Getting started is super easy!

### One-Command Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/jlleongarcia/PyStocks.git
cd PyStocks

# Complete setup with one command!
make setup
```

That's it! The `make setup` command will:
- ✅ Create `.env` file from template
- ✅ Build Docker containers
- ✅ Start all services (database + web)
- ✅ Run database migrations
- ✅ Collect static files
- ✅ Create default superuser (admin/admin123)

**No Make?** Use the setup script instead:
```bash
./setup.sh
```

### Alternative: Automated Setup Script

```bash
# Clone the repository
git clone https://github.com/jlleongarcia/PyStocks.git
cd PyStocks

# Run the setup script
./setup.sh
```

### Option 3: Manual Setup

```bash
# Clone and enter directory
git clone https://github.com/jlleongarcia/PyStocks.git
cd PyStocks

# Copy environment file
cp .env.example .env

# Build and start containers
docker-compose build
docker-compose up -d

# Wait for database, then run migrations
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py collectstatic --noinput
```

### 🌐 Access Points

After setup, access the application at:
- **Landing Page:** http://localhost:8300
- **Admin Panel:** http://localhost:8300/admin
- **API Root:** http://localhost:8300/api

### Common Make Commands

```bash
make help           # Show all available commands
make up             # Start all services
make down           # Stop all services
make logs           # View application logs
make migrate        # Run database migrations
make test           # Run tests
make bash           # Open shell in web container
```

## 🔐 Default Credentials

- **Username:** admin
- **Password:** admin123

## 📚 Documentation

Quick links for collaborators:
- 🚀 **[QUICKSTART.md](QUICKSTART.md)** - Get started in under 5 minutes
- 📋 **[CHEATSHEET.md](CHEATSHEET.md)** - Command reference card
- 🤝 **[CONTRIBUTING.md](CONTRIBUTING.md)** - Detailed contribution guide
- ⚙️ **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - In-depth setup instructions
- 📖 **[brd.md](brd.md)** - Business requirements document

**First time?** Start with [QUICKSTART.md](QUICKSTART.md)!

## 🛠️ Tech Stack

- **Backend:** Django 5.0, Django REST Framework
- **Database:** PostgreSQL 15
- **Frontend:** HTML5, CSS3, JavaScript (Vanilla)
- **Containerization:** Docker & Docker Compose
- **API Integration:** Stock market data APIs

## 📊 Project Structure

```
PyStocks/
├── main/              # Django project settings
├── portfolio/         # Portfolio management app
├── research/          # Stock research app
├── templates/         # HTML templates
├── static/           # Static files (CSS, JS)
└── docker-compose.yml
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License.

## 🌟 Acknowledgments

Built with passion for the investing community.

---

**MarketMind** - *Intelligent insights for smarter investing*

