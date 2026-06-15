#!/usr/bin/env bash
# redeploy.sh — pull latest code and restart CountingCarbon.
# Run on the server as the app user or root:
#   sudo -u countingcarbon bash /home/countingcarbon/app/deploy/redeploy.sh
#
# Safe to run at any time; gunicorn reloads gracefully after restart.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
SERVICE="countingcarbon"

info()  { echo -e "\n\033[1;32m▶ $*\033[0m"; }
ok()    { echo -e "  \033[32m✓\033[0m $*"; }
fail()  { echo -e "  \033[31m✗\033[0m $*"; exit 1; }

# ── Preflight ─────────────────────────────────────────────────────────────────

[[ -f "${ENV_FILE}" ]] || fail ".env not found at ${ENV_FILE}"
[[ -d "${APP_DIR}/.git" ]] || fail "Not a git repo: ${APP_DIR}"

# ── Pull ──────────────────────────────────────────────────────────────────────

info "Pulling latest code"
git -C "${APP_DIR}" fetch --quiet origin
BEFORE=$(git -C "${APP_DIR}" rev-parse HEAD)
git -C "${APP_DIR}" pull --quiet --ff-only
AFTER=$(git -C "${APP_DIR}" rev-parse HEAD)

if [[ "${BEFORE}" == "${AFTER}" ]]; then
  echo "  Already up to date (${AFTER:0:8}). Restarting anyway."
else
  ok "Updated ${BEFORE:0:8} → ${AFTER:0:8}"
  git -C "${APP_DIR}" log --oneline "${BEFORE}..${AFTER}"
fi

# ── Dependencies ──────────────────────────────────────────────────────────────

info "Syncing Python dependencies"
uv sync --no-dev --project "${APP_DIR}"
ok "Dependencies synced"

# ── Django management ─────────────────────────────────────────────────────────

run_manage() {
  set -a; source "${ENV_FILE}"; set +a
  uv run --project "${APP_DIR}" python "${APP_DIR}/manage.py" "$@"
}

info "Running migrations"
run_manage migrate --no-input
ok "Migrations done"

info "Collecting static files"
run_manage collectstatic --no-input --clear
ok "Static files collected"

# Reload catalogue only if the seed fixture has changed
if git -C "${APP_DIR}" diff --name-only "${BEFORE}" "${AFTER}" \
     | grep -q "fixtures/catalogue_seed.json"; then
  info "catalogue_seed.json changed — reloading catalogue"
  run_manage load_catalogue
  ok "Catalogue reloaded"
fi

# ── Restart service ───────────────────────────────────────────────────────────

info "Restarting ${SERVICE} service"
if systemctl is-active --quiet "${SERVICE}"; then
  sudo systemctl restart "${SERVICE}"
else
  sudo systemctl start "${SERVICE}"
fi

# Wait briefly and confirm it's up
sleep 2
systemctl is-active --quiet "${SERVICE}" \
  && ok "Service is running" \
  || fail "Service failed to start — check: sudo journalctl -u ${SERVICE} -n 50"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "  Deployed:  ${AFTER:0:8}"
echo "  Logs:      sudo journalctl -u ${SERVICE} -f"
echo ""
