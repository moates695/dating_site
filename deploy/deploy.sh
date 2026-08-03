#!/usr/bin/env bash
#
# Deploy the dating site to the production droplet.
#
#   1. Ships the current committed code (git HEAD) to the droplet build context.
#   2. Rebuilds the image and recreates the container via docker compose.
#   3. Applies any pending migrations inside the container.
#   4. Verifies the container is up and the public endpoint answers.
#
# This only ships application code. Page bundles are shipped separately by
# scripts/publish.py, and /opt/dating_site/.env is managed by hand on the
# droplet; neither is touched here.
#
# Usage:
#   deploy/deploy.sh                # deploy committed HEAD
#   deploy/deploy.sh --allow-dirty  # deploy HEAD even with a dirty tree
#
# Config (override via env):
#   DATES_SSH_HOST    ssh host/alias for the droplet  (default: do)
#   DATES_REMOTE_DIR  build context on the droplet    (default: /opt/dating_site)
#   DATES_URL         public endpoint to verify       (default: https://dates.moates.com.au/healthz)

set -euo pipefail

SSH_HOST="${DATES_SSH_HOST:-do}"
REMOTE_DIR="${DATES_REMOTE_DIR:-/opt/dating_site}"
PUBLIC_URL="${DATES_URL:-https://dates.moates.com.au/healthz}"
CONTAINER="dates-prod"

ALLOW_DIRTY=0
[[ "${1:-}" == "--allow-dirty" ]] && ALLOW_DIRTY=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- Preflight -------------------------------------------------------------
command -v git >/dev/null || die "git not found"
git rev-parse --git-dir >/dev/null 2>&1 || die "not inside the dating_site git repo"

REV="$(git rev-parse --short HEAD)"

if [[ -n "$(git status --porcelain)" ]]; then
  if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
    log "working tree is dirty; deploying committed HEAD ($REV) anyway (--allow-dirty)"
  else
    die "working tree has uncommitted changes. Commit them, or pass --allow-dirty to deploy HEAD ($REV) regardless."
  fi
fi

ssh "$SSH_HOST" "test -f $REMOTE_DIR/.env" \
  || die "$REMOTE_DIR/.env missing on the droplet; see README, 'Deploying'"

# --- Ship ------------------------------------------------------------------
log "shipping $REV to $SSH_HOST:$REMOTE_DIR"
ssh "$SSH_HOST" "mkdir -p $REMOTE_DIR $REMOTE_DIR/pages"
# tar over ssh rather than git-push: no checkout or remote on the droplet.
# Extraction overwrites tracked files and leaves pages/ and .env alone.
git archive --format=tar HEAD | ssh "$SSH_HOST" "tar -x -C $REMOTE_DIR"
ok "code shipped"

# --- Build and start -------------------------------------------------------
log "building and starting $CONTAINER"
ssh "$SSH_HOST" "cd $REMOTE_DIR/deploy && docker compose up -d --build"
ok "container started"

# --- Migrate ---------------------------------------------------------------
log "applying migrations"
ssh "$SSH_HOST" "cd $REMOTE_DIR/deploy && docker compose exec -T dates python scripts/migrate.py"
ok "migrations applied"

# --- Verify ----------------------------------------------------------------
log "verifying"
ssh "$SSH_HOST" "docker ps --filter name=$CONTAINER --format '{{.Status}}'" | grep -q "Up" \
  || die "container is not running; check: ssh $SSH_HOST docker logs $CONTAINER"
ok "container is up"

STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUBLIC_URL" || true)"
if [[ "$STATUS" == "200" ]]; then
  ok "$PUBLIC_URL responded 200"
else
  die "$PUBLIC_URL responded $STATUS; check the nginx server block and the DNS record"
fi

log "deployed $REV"
