# 🚀 Quick Start Guide for Collaborators

## For Your Friend/Collaborator

Hey! Welcome to the MarketMind project. Here's how to get started in **under 2 minutes**.

---

## ⚡ Super Quick Setup (One Command!)

1. **Clone the repo:**
   ```bash
   git clone https://github.com/jlleongarcia/PyStocks.git
   cd PyStocks
   ```

2. **Run the setup script:**
   ```bash
   ./setup.sh
   ```
   
   That's it! The script handles everything automatically. ✨

---

## 🛠️ What You Need Installed

- **Docker** - [Get it here](https://docs.docker.com/get-docker/)
- **Docker Compose** - Usually comes with Docker Desktop
- **Make** (optional but helpful) - Usually pre-installed on Mac/Linux

---

## 📋 Alternative: Using Make

If you prefer Make commands:

```bash
# After cloning the repo
cp .env.example .env
make setup
```

**Done!** 🎉

---

## 🌐 Access the App

Once setup is complete:

| What | Where |
|------|-------|
| **Landing Page** | http://localhost:8300 |
| **Admin Dashboard** | http://localhost:8300/admin |
| **API Docs** | http://localhost:8300/api |

**Login credentials:**
- Username: `admin`
- Password: `admin123`

---

## 🔧 Daily Development Commands

```bash
# Start the app
make up

# Stop the app
make down

# View logs
make logs

# Open a shell in the container
make bash

# Run migrations
make migrate

# See all commands
make help
```

---

## 📝 Making Changes

1. **Create a branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** to the code

3. **Test locally:**
   ```bash
   make test
   ```

4. **Commit and push:**
   ```bash
   git add .
   git commit -m "feat: add awesome feature"
   git push origin feature/my-feature
   ```

5. **Create a Pull Request** on GitHub

---

## 🆘 Having Issues?

### Port Already in Use?
Edit `.env` file and change the ports:
```env
WEB_PORT=8301
POSTGRES_PORT=5434
```

Then restart:
```bash
make restart
```

### Container Won't Start?
```bash
make clean      # Remove everything
make setup      # Start fresh
```

### Need to Reset Database?
```bash
make reset      # WARNING: Deletes all data!
make setup      # Setup again
```

---

## 📚 More Help

- Full contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Detailed README: [readme.md](readme.md)
- Setup documentation: [SETUP_GUIDE.md](SETUP_GUIDE.md)

---

## 🎯 Key Files to Know

| File/Folder | What's Inside |
|------------|---------------|
| `main/` | Django settings & configuration |
| `portfolio/` | Portfolio management features |
| `research/` | Stock research features |
| `templates/` | HTML templates (landing page, etc.) |
| `static/` | CSS, JavaScript, images |
| `Makefile` | All the helpful commands |
| `.env` | Your local configuration |

---

## 💡 Pro Tips

1. **Always pull latest changes before starting work:**
   ```bash
   git pull origin main
   ```

2. **Keep containers running during development:**
   ```bash
   make up    # Start once
   # Code changes will auto-reload!
   ```

3. **Check container status:**
   ```bash
   make status
   ```

4. **Database backup before big changes:**
   ```bash
   make backup
   ```

---

## 🎉 You're All Set!

Questions? Just ask! Happy coding! 🧠✨

---

**MarketMind** - *Intelligent insights for smarter investing*
