#!/bin/bash
# Market Mind - cron-safe daily financial metrics refresh (Payout%, FCF, Payout FCF, P/E, beta, etc.)
# Uses docker exec directly (no dependency on docker-compose or working directory)
# Runs daily via cron — see crontab / Makefile setup-cron-financial-metrics

set -e

DOCKER="/usr/bin/docker"
WEB_CONTAINER="market-mind-web-1"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting financial metrics refresh..."

if ! $DOCKER inspect "$WEB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    log "ERROR: Container $WEB_CONTAINER is not running. Aborting."
    exit 1
fi

$DOCKER exec "$WEB_CONTAINER" python manage.py update_financial_metrics --all

log "Financial metrics refresh completed."
