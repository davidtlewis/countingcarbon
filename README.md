# CountingCarbon

Track your household carbon footprint over time.

**Domain:** countingcarbon.dtlewis.com  
**Stack:** Django 6 · HTMX · Chart.js · PostgreSQL · Railway

---

## Local development (fresh clone)

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (`pip install uv` or see the uv docs)
- Python 3.12+ (uv will manage this automatically)
- PostgreSQL — optional; SQLite is the default for quick local hacking

### Setup

```sh
# 1. Clone and enter the project
git clone <repo-url>
cd countingcarbon

# 2. Install dependencies (creates .venv automatically)
uv sync

# 3. Copy the example env file and edit as needed
cp .env.example .env
# Edit SECRET_KEY and optionally DATABASE_URL if using Postgres

# 4. Run migrations
uv run python manage.py migrate

# 5. Start the dev server
uv run python manage.py runserver
```

Browse to http://127.0.0.1:8000/

### Using PostgreSQL locally

Set `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgres://user:pass@localhost:5432/countingcarbon
```

### Install pre-commit hooks (one-time)

```sh
uv run pre-commit install
```

Hooks run `ruff` (lint + format) on every commit.

---

## Project structure

```
countingcarbon/        # Django project package (settings/, urls.py, wsgi.py)
  settings/
    base.py            # shared settings
    dev.py             # local development (DEBUG=True, console email)
    prod.py            # Railway/production (reads from env vars)
accounts/              # auth, household membership, invitations (T2/T3)
catalogue/             # slices, line items, factor sets (Phase 2)
entries/               # PeriodicEntry, EventEntry, AnnualEstimate (T4+)
engine/                # formula evaluator, pinning, annualisation (T5+)
dashboard/             # aggregate views, trend chart (T6)
templates/             # project-wide templates (base.html, hello.html)
static/css/main.css    # mobile-first stylesheet
fixtures/              # seed data (catalogue — Phase 2)
```

---

## Deployment (Railway)

1. Create a Railway project and link this repo.
2. Add a Postgres plugin — Railway injects `DATABASE_URL` automatically.
3. Set environment variables: `SECRET_KEY`, `ALLOWED_HOSTS`, and any SMTP settings.
4. Railway uses `railway.toml` to build with Nixpacks and start Gunicorn.
5. The `release` phase in `Procfile` runs `migrate` and `collectstatic` on each deploy.

---

## Settings module

`DJANGO_SETTINGS_MODULE` defaults:

| Context | Module |
|---|---|
| `manage.py` / local dev | `countingcarbon.settings.dev` |
| Gunicorn / wsgi.py | `countingcarbon.settings.prod` |

Override by setting the env var explicitly before running any command.
