#!/bin/bash
# Runs daily at 8am via cron — see crontab

PROJECT_DIR="/home/jlleongarcia/Documents/Github_projects/Py-Stocks"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sql"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

cd "$PROJECT_DIR" || { log "ERROR: project dir not found"; exit 1; }

# Load DB credentials from .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

DB_USER="${DATABASE_USER:-marketmind_user}"
DB_NAME="${DATABASE_NAME:-marketmind_db}"

mkdir -p "$BACKUP_DIR"

log "Starting backup of $DB_NAME..."

if ! docker-compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"; then
    log "ERROR: pg_dump failed"
    rm -f "$BACKUP_FILE"
    exit 1
fi

BACKUP_SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
log "Backup saved: $BACKUP_FILE ($BACKUP_SIZE)"

# Prune backups older than RETENTION_DAYS
PRUNED=$(find "$BACKUP_DIR" -name "db_backup_*.sql" -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
[ "$PRUNED" -gt 0 ] && log "Pruned $PRUNED backup(s) older than $RETENTION_DAYS days"

log "Done."
