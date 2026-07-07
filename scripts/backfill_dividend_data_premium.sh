#!/bin/bash
# Market Mind - one-time Alpha Vantage PREMIUM key blitz: backfill
# declaration_date/payment_date for every tracked stock in a single fast
# pass (~1 req/sec, finishes in well under a minute for our stock list).
#
# NOT part of the daily cron — scripts/backfill_dividend_data.sh (the
# free-tier command it runs) is completely untouched by this. Run manually
# as needed during the paid premium month. See DIVIDEND_AUTOMATION.md.
#
# Any arguments are passed straight through to the management command,
# e.g. ./backfill_dividend_data_premium.sh --symbols AAPL MSFT --delay 2

set -e

DOCKER="/usr/bin/docker"
WEB_CONTAINER="market-mind-web-1"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting Alpha Vantage premium dividend-dates blitz..."

if ! $DOCKER inspect "$WEB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    log "ERROR: Container $WEB_CONTAINER is not running. Aborting."
    exit 1
fi

$DOCKER exec "$WEB_CONTAINER" python manage.py backfill_dividend_dates_premium "$@"

log "Premium dividend-dates blitz completed."
