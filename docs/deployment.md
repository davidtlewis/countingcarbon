# CountingCarbon — EC2 Deployment Guide

This guide covers deploying CountingCarbon to a single Ubuntu 24.04 EC2 instance using nginx + gunicorn + systemd + PostgreSQL.

---

## Prerequisites

**EC2 instance:**
- Ubuntu 24.04 LTS
- At least `t3.small` (2 GB RAM recommended)
- Security group inbound rules: **22** (SSH), **80** (HTTP), **443** (HTTPS)

**DNS:**
- An A record pointing your domain (e.g. `countingcarbon.dtlewis.com`) at the EC2 public IP — set this up before running certbot

**Email:**
- SMTP credentials from a transactional provider (Mailgun, Resend, AWS SES, etc.) — needed for allauth email verification

---

## First-time deploy

The app runs as the `ubuntu` user — the default EC2 login. No separate app user is needed.

### 1. Before you start — update the repo URL

Open `deploy/deploy.sh` and set `REPO_URL` at the top to your GitHub repository:

```bash
REPO_URL="https://github.com/you/countingcarbon.git"
```

### 2. Copy the script to the server and run it

```bash
# From your local machine
scp -i your-key.pem deploy/deploy.sh ubuntu@<EC2-IP>:~/

# SSH in and run as root
ssh -i your-key.pem ubuntu@<EC2-IP>
sudo bash deploy.sh
```

The script is interactive — it will prompt you for:

| Prompt | Example |
|---|---|
| Database password | (choose something strong) |
| Git repository URL | `https://github.com/you/countingcarbon.git` |
| Domain name | `countingcarbon.dtlewis.com` |
| SMTP host | `smtp.mailgun.org` |
| SMTP port | `587` |
| SMTP username | `postmaster@mg.countingcarbon.dtlewis.com` |
| SMTP password | (from your email provider) |
| Default from address | `noreply@countingcarbon.dtlewis.com` |
| Run certbot now? | `Y` (requires DNS to be pointing at the server) |

### 3. What the script does

1. Updates system packages and installs nginx, PostgreSQL, certbot, uv
2. Creates the PostgreSQL database and `countingcarbon` DB user
3. Clones the repository to `/home/ubuntu/app`
4. Installs Python dependencies via `uv sync --no-dev`
5. Writes `/home/ubuntu/app/.env` (mode 600)
6. Runs `migrate`, `load_catalogue`, `collectstatic`
7. Prompts you to create a Django superuser (`createsuperuser`)
8. Installs and starts the `countingcarbon` systemd service (runs as `ubuntu`)
9. Configures nginx as a reverse proxy
10. Optionally runs certbot to obtain a Let's Encrypt TLS certificate

### 4. Verify the deployment

```bash
# Service running?
sudo systemctl status countingcarbon

# Live logs
sudo journalctl -u countingcarbon -f

# nginx config valid?
sudo nginx -t

# HTTP response
curl -I https://countingcarbon.dtlewis.com/
```

You should see a `200 OK` with a `Strict-Transport-Security` header.

---

## Redeploying (pushing updates)

After merging changes to `main`, SSH to the server and run:

```bash
bash ~/app/deploy/redeploy.sh
```

### What redeploy does

1. `git pull --ff-only` — prints the commits being deployed
2. `uv sync --no-dev` — installs any new/updated dependencies
3. `migrate --no-input` — applies any new migrations
4. `collectstatic --no-input --clear` — rebuilds the static file manifest
5. `load_catalogue` — only if `fixtures/catalogue_seed.json` changed in the pull
6. `sudo systemctl restart countingcarbon` — graceful restart

The script exits non-zero on any failure so you know immediately if something went wrong.

---

## Environment file

The `.env` file lives at `/home/ubuntu/app/.env` and is sourced by systemd. It is mode 600. To update a value:

```bash
nano ~/app/.env
sudo systemctl restart countingcarbon
```

All required variables:

```bash
DJANGO_SETTINGS_MODULE=countingcarbon.settings.prod
SECRET_KEY=<50-char random string>
DATABASE_URL=postgres://countingcarbon:<password>@localhost/countingcarbon
ALLOWED_HOSTS=countingcarbon.dtlewis.com

EMAIL_HOST=smtp.mailgun.org
EMAIL_PORT=587
EMAIL_HOST_USER=postmaster@mg.countingcarbon.dtlewis.com
EMAIL_HOST_PASSWORD=<smtp password>
DEFAULT_FROM_EMAIL=noreply@countingcarbon.dtlewis.com
```

To generate a new secret key:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## Useful commands on the server

```bash
# View live application logs
sudo journalctl -u countingcarbon -f

# View last 100 lines of logs
sudo journalctl -u countingcarbon -n 100

# Restart the app (e.g. after editing .env)
sudo systemctl restart countingcarbon

# Stop / start
sudo systemctl stop countingcarbon
sudo systemctl start countingcarbon

# Open a Django shell
cd ~/app
set -a; source .env; set +a
uv run python manage.py shell

# Run a management command
cd ~/app
set -a; source .env; set +a
uv run python manage.py <command>

# Check certbot auto-renewal
sudo certbot renew --dry-run
```

---

## Architecture overview

```
Internet
   │  HTTPS :443
   ▼
nginx  ──── /static/ ──► /home/ubuntu/app/staticfiles/
   │
   │  Unix socket  /run/countingcarbon.sock
   ▼
gunicorn  (2 workers × 2 threads)
   │
   ▼
Django (countingcarbon.settings.prod)
   │
   ▼
PostgreSQL (localhost)
```

- **nginx** terminates TLS and serves static files directly (bypassing Python entirely)
- **whitenoise** also serves static files as a fallback (belt-and-braces) and handles cache headers
- **gunicorn** communicates with nginx via a Unix socket (faster than TCP for local traffic)
- **systemd** restarts gunicorn automatically on failure

---

## Troubleshooting

**502 Bad Gateway**
The gunicorn process isn't running or the socket path is wrong.
```bash
sudo systemctl status countingcarbon
sudo journalctl -u countingcarbon -n 50
```

**Static files returning 404**
Run `collectstatic` again and check the nginx `alias` path matches `STATIC_ROOT`.
```bash
sudo -u countingcarbon bash -c "
  set -a; source /home/countingcarbon/app/.env; set +a
  cd /home/countingcarbon/app && uv run python manage.py collectstatic --no-input
"

**Email not arriving**
Check SMTP credentials in `.env`. Test from the Django shell:
```python
from django.core.mail import send_mail
send_mail('Test', 'Body', 'from@example.com', ['to@example.com'])
```

**`ALLOWED_HOSTS` error**
Add the server's IP or domain to `ALLOWED_HOSTS` in `.env`, then restart.

**Certbot renewal fails**
Port 80 must be open and nginx must be running. Check:
```bash
sudo certbot renew --dry-run
sudo systemctl status nginx
```
