#!/bin/sh
# Pull a published image tag and restart the stack. Run by CI over SSH, and by
# hand for rollbacks:
#
#   /opt/deployed/timeMe/deploy.sh <commit-sha>
#
# This file is not read from the repo at deploy time — the VPS holds no source
# checkout. Copy it once and re-copy it if it changes here:
#
#   scp scripts/deploy.sh deploy@vps:/opt/deployed/timeMe/deploy.sh
#   ssh deploy@vps chmod +x /opt/deployed/timeMe/deploy.sh
#
# /opt/deployed/timeMe must contain docker-compose.yml, .env and a backups/ directory.
# The tag is written into .env so a later plain `docker compose up -d` brings
# up the same image rather than drifting to :latest.

set -eu

TAG="${1:?usage: deploy.sh <image-tag>}"
DIR="${TIMEME_DIR:-/opt/deployed/timeMe}"
# The app container must report healthy within this window or we roll back.
# Generous: the image's HEALTHCHECK has a 10s start period and a 30s interval.
HEALTH_TIMEOUT=90

cd "$DIR"

log() { echo "[deploy] $*"; }

set_tag() {
    umask 077
    grep -v '^TIMEME_TAG=' .env > .env.next || true
    echo "TIMEME_TAG=$1" >> .env.next
    mv .env.next .env
}

PREVIOUS=$(sed -n 's/^TIMEME_TAG=//p' .env | tail -1)
log "deploying $TAG (previous: ${PREVIOUS:-none})"

set_tag "$TAG"

# Fail before touching the running container if the image is not fetchable.
log "pulling images"
docker compose pull --quiet

log "restarting"
docker compose up -d --remove-orphans

# HEALTHCHECK in the Dockerfile hits /api/health; wait for it to pass so a boot
# failure (bad migration, missing env var) is caught here and not by a user.
log "waiting up to ${HEALTH_TIMEOUT}s for the app to report healthy"
waited=0
while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    status=$(docker inspect -f '{{.State.Health.Status}}' timeme 2>/dev/null || echo missing)
    case "$status" in
        healthy)
            log "healthy after ${waited}s"
            docker image prune -f >/dev/null
            log "done"
            exit 0
            ;;
        unhealthy)
            log "container reported unhealthy"
            break
            ;;
    esac
    sleep 3
    waited=$(( waited + 3 ))
done

log "ERROR: $TAG did not become healthy (last status: ${status:-unknown})"
docker compose logs --tail 50 app || true

if [ -z "$PREVIOUS" ] || [ "$PREVIOUS" = "$TAG" ]; then
    log "no distinct previous tag recorded; leaving the stack as-is for inspection"
    exit 1
fi

log "rolling back to $PREVIOUS"
set_tag "$PREVIOUS"
docker compose up -d
log "rolled back; $TAG was not deployed"
exit 1
