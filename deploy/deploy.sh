#!/usr/bin/env bash
# deploy.sh — first-time setup of CountingCarbon on a fresh Ubuntu 24.04 EC2 instance.
#
# Run as the ubuntu user (the default EC2 login) using sudo:
#   sudo bash deploy.sh
#
# The app runs as 'ubuntu' — no separate app user is created.
#
# What it does:
#   1. Installs system packages (nginx, postgresql, certbot, uv)
#   2. Clones the repo to /home/ubuntu/app
#   3. Installs Python deps
#   4. Creates the .env file interactively
#   5. Runs migrations, seeds the catalogue, collects static files
#   6. Installs the systemd service (runs as ubuntu)
#   7. Configures nginx
#   8. Optionally obtains a Let's Encrypt TLS certificate

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

APP_USER="ubuntu"
APP_DIR="/home/ubuntu/app"
REPO_URL="https://github.com/davidlewis/countingcarbon.git"   # ← update this
DOMAIN=""          # set below interactively

# ── Helpers ───────────────────────────────────────────────────────────────────

info()  { echo -e "\n\033[1;32m▶ $*\033[0m"; }
warn()  { echo -e "\033[1;33m⚠  $*\033[0m"; }
prompt(){ read -rp "  $1: " "$2"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run this script as root: sudo bash deploy.sh"
  exit 1
fi

# ── 1. System packages ────────────────────────────────────────────────────────

info "Updating system packages"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  nginx postgresql postgresql-contrib \
  python3-pip python3-venv \
  certbot python3-certbot-nginx \
  git curl

info "Installing uv"
if ! sudo -u "${APP_USER}" bash -c 'command -v uv &>/dev/null'; then
  sudo -u "${APP_USER}" bash -c \
    'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
# Symlink so uv is on PATH when running via sudo
UV_BIN="$(sudo -u "${APP_USER}" bash -c 'echo $HOME')/.local/bin/uv"
ln -sf "${UV_BIN}" /usr/local/bin/uv

# ── 2. PostgreSQL ─────────────────────────────────────────────────────────────

info "Setting up PostgreSQL database"
prompt "Database password for the 'countingcarbon' DB user" DB_PASS

sudo -u postgres psql -tc \
  "SELECT 1 FROM pg_roles WHERE rolname='countingcarbon'" | grep -q 1 || \
  sudo -u postgres psql -c \
    "CREATE USER countingcarbon WITH PASSWORD '${DB_PASS}';"

sudo -u postgres psql -tc \
  "SELECT 1 FROM pg_database WHERE datname='countingcarbon'" | grep -q 1 || \
  sudo -u postgres psql -c \
    "CREATE DATABASE countingcarbon OWNER countingcarbon;"

DATABASE_URL="postgres://countingcarbon:${DB_PASS}@localhost/countingcarbon"

# ── 3. Clone repo ─────────────────────────────────────────────────────────────

info "Cloning repository to ${APP_DIR}"
prompt "Git repository URL (press Enter for ${REPO_URL})" USER_REPO
REPO_URL="${USER_REPO:-$REPO_URL}"

if [[ -d "${APP_DIR}/.git" ]]; then
  warn "Repo already exists at ${APP_DIR} — pulling latest instead"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" pull
else
  sudo -u "${APP_USER}" git clone "${REPO_URL}" "${APP_DIR}"
fi

# ── 4. Python deps ────────────────────────────────────────────────────────────

info "Installing Python dependencies"
sudo -u "${APP_USER}" bash -c "cd ${APP_DIR} && uv sync --no-dev"

# ── 5. Environment file ───────────────────────────────────────────────────────

info "Configuring environment"
prompt "Domain name (e.g. countingcarbon.dtlewis.com)" DOMAIN

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")

prompt "Email SMTP host (e.g. smtp.mailgun.org)" EMAIL_HOST
prompt "Email SMTP port (default 587)" EMAIL_PORT_IN
EMAIL_PORT="${EMAIL_PORT_IN:-587}"
prompt "Email SMTP username" EMAIL_USER
prompt "Email SMTP password" EMAIL_PASS
prompt "Default from address (e.g. noreply@${DOMAIN})" DEFAULT_FROM

ENV_FILE="${APP_DIR}/.env"
cat > "${ENV_FILE}" <<EOF
DJANGO_SETTINGS_MODULE=countingcarbon.settings.prod
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=${DATABASE_URL}
ALLOWED_HOSTS=${DOMAIN}

EMAIL_HOST=${EMAIL_HOST}
EMAIL_PORT=${EMAIL_PORT}
EMAIL_HOST_USER=${EMAIL_USER}
EMAIL_HOST_PASSWORD=${EMAIL_PASS}
DEFAULT_FROM_EMAIL=${DEFAULT_FROM}
EOF
chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

# ── 6. Django setup ───────────────────────────────────────────────────────────

info "Running migrations"
sudo -u "${APP_USER}" bash -c "
  set -a; source ${ENV_FILE}; set +a
  cd ${APP_DIR}
  uv run python manage.py migrate --no-input
  uv run python manage.py load_catalogue
  uv run python manage.py collectstatic --no-input
"

info "Creating superuser"
sudo -u "${APP_USER}" bash -c "
  set -a; source ${ENV_FILE}; set +a
  cd ${APP_DIR}
  uv run python manage.py createsuperuser
"

# ── 7. Systemd service ────────────────────────────────────────────────────────

info "Installing systemd service"
cat > /etc/systemd/system/countingcarbon.service <<EOF
[Unit]
Description=CountingCarbon gunicorn
After=network.target postgresql.service

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/gunicorn \\
    countingcarbon.wsgi \\
    --workers 2 \\
    --threads 2 \\
    --bind unix:/run/countingcarbon.sock \\
    --access-logfile - \\
    --error-logfile -
RuntimeDirectory=countingcarbon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable countingcarbon
systemctl restart countingcarbon

# ── 8. Nginx ──────────────────────────────────────────────────────────────────

info "Configuring nginx"
cat > /etc/nginx/sites-available/countingcarbon <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        gzip_static on;
    }

    location / {
        proxy_pass http://unix:/run/countingcarbon.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
        client_max_body_size 5M;
    }
}
EOF

ln -sf /etc/nginx/sites-available/countingcarbon /etc/nginx/sites-enabled/countingcarbon
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ── 9. TLS ────────────────────────────────────────────────────────────────────

read -rp "  Obtain a Let's Encrypt certificate for ${DOMAIN} now? [Y/n]: " TLS_ANSWER
if [[ "${TLS_ANSWER,,}" != "n" ]]; then
  info "Obtaining TLS certificate"
  certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos \
    --email "admin@${DOMAIN}" --redirect
  systemctl reload nginx
  info "TLS certificate installed. Auto-renewal is active via certbot.timer."
else
  warn "Skipped TLS. Run: sudo certbot --nginx -d ${DOMAIN}"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

info "Deployment complete!"
echo ""
echo "  App:      https://${DOMAIN}"
echo "  Admin:    https://${DOMAIN}/admin/"
echo "  Logs:     sudo journalctl -u countingcarbon -f"
echo "  Redeploy: bash ${APP_DIR}/deploy/redeploy.sh"
echo ""
