#!/bin/bash
# Market Mind - cron-safe daily DB backup
# Uses docker exec directly (no dependency on docker-compose or working directory)
# Runs daily at 8am via cron — see crontab

set -e

PROJECT_DIR="/home/jlleongarcia/Documents/Github_projects/market-mind"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="db_backup_$TIMESTAMP.sql"

DOCKER="/usr/bin/docker"
DB_CONTAINER="market-mind-db-1"

mkdir -p "$BACKUP_DIR"

# Writing to stdout only — the caller (crontab) redirects stdout/stderr to backup.log.
# Run manually with `... | tee -a backups/backup.log` if you also want to see it live and logged.
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting Market Mind backup..."

# Load DB credentials from .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

DB_USER="${DATABASE_USER:-marketmind_user}"
DB_NAME="${DATABASE_NAME:-marketmind_db}"

if ! $DOCKER inspect "$DB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    log "ERROR: Container $DB_CONTAINER is not running. Aborting."
    exit 1
fi

if ! $DOCKER exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_DIR/$BACKUP_FILE"; then
    log "ERROR: pg_dump failed"
    rm -f "$BACKUP_DIR/$BACKUP_FILE"
    exit 1
fi

if [ ! -s "$BACKUP_DIR/$BACKUP_FILE" ]; then
    log "ERROR: Backup file was not created or is empty."
    rm -f "$BACKUP_DIR/$BACKUP_FILE"
    exit 1
fi

gzip "$BACKUP_DIR/$BACKUP_FILE"
COMPRESSED_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE.gz" | cut -f1)
log "Backup created: $BACKUP_DIR/$BACKUP_FILE.gz ($COMPRESSED_SIZE)"

# Prune backups older than RETENTION_DAYS
PRUNED=$(find "$BACKUP_DIR" -name "db_backup_*.sql.gz" -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
[ "$PRUNED" -gt 0 ] && log "Pruned $PRUNED backup(s) older than $RETENTION_DAYS days"

log "Backup completed."
