#!/bin/bash
# Market Mind - cron-safe daily dividend declaration_date backfill + buy_yield recompute
# Uses docker exec directly (no dependency on docker-compose or working directory)
# Runs daily via cron — see crontab / Makefile setup-cron-dividends

set -e

DOCKER="/usr/bin/docker"
WEB_CONTAINER="market-mind-web-1"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting dividend declaration_date backfill..."

if ! $DOCKER inspect "$WEB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    log "ERROR: Container $WEB_CONTAINER is not running. Aborting."
    exit 1
fi

$DOCKER exec "$WEB_CONTAINER" python manage.py backfill_dividend_declaration_dates
$DOCKER exec "$WEB_CONTAINER" python manage.py recompute_buy_yields

log "Dividend backfill and buy_yield recompute completed."
