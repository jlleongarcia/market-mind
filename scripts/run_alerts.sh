#!/bin/bash
# Market Mind - cron-safe daily alert evaluation + email/Telegram digests
# Runs after update_financial_metrics.sh (9:00) so rules see fresh metrics
# Uses docker exec directly (no dependency on docker-compose or working directory)
# Runs daily via cron — see crontab / Makefile setup-cron-alerts

set -e

DOCKER="/usr/bin/docker"
WEB_CONTAINER="market-mind-web-1"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting alert evaluation..."

if ! $DOCKER inspect "$WEB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    log "ERROR: Container $WEB_CONTAINER is not running. Aborting."
    exit 1
fi

$DOCKER exec "$WEB_CONTAINER" python manage.py run_alerts

log "Alert evaluation completed."
