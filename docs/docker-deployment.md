# CountingCarbon — Docker deployment

Runs as a Docker Compose stack (Gunicorn/Django + Postgres 18) on the Proxmox app VM. TLS terminates on the edge nginx host, which proxies to `WEB_BIND_IP:WEB_PORT` on the app VM. This replaces the EC2/systemd setup in `deployment.md` once cutover is done.

```
Internet ─► edge nginx (TLS, certbot) ─► app VM :8001 ─► web (gunicorn :8000) ─► db (postgres:18)
```

## First deploy

```bash
git clone https://github.com/davidtlewis/countingcarbon.git && cd countingcarbon
cp .env.example .env && chmod 600 .env   # fill in values; WEB_BIND_IP = app VM LAN IP
docker compose up -d --build
docker compose exec web python manage.py load_catalogue
docker compose exec web python manage.py createsuperuser   # skip if restoring data
```

Migrations run automatically when the `web` container starts (`docker/entrypoint.sh`). Static files are collected at build time and served by WhiteNoise.

## Restore from a pg_dump

Start the database alone so the app doesn't migrate an empty schema first:

```bash
docker compose up -d db
docker compose exec -T db pg_restore --no-owner --role=countingcarbon \
  -U countingcarbon -d countingcarbon --exit-on-error < countingcarbon.dump
docker compose up -d --build web
```

## Updating

```bash
git pull
docker compose up -d --build
# if fixtures/catalogue_seed.json changed:
docker compose exec web python manage.py load_catalogue
```

## Backups

```bash
docker compose exec -T db pg_dump -Fc -U countingcarbon countingcarbon > countingcarbon_$(date +%F).dump
```

## Testing without the edge proxy

Production settings redirect plain HTTP and check the Host header, so send what nginx would:

```bash
curl -H "Host: countingcarbon.dtlewis.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8001/
```

## Edge nginx

The edge server block must set `Host`, `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto`. allauth's rate limiter reads the client IP from `X-Real-IP` (`accounts/adapters.py`), so the app port must only be reachable from the nginx host.
