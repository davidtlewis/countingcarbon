# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies and create .venv
uv sync

# Run dev server (uses countingcarbon.settings.dev)
uv run python manage.py runserver

# Migrations
uv run python manage.py makemigrations
uv run python manage.py migrate

# Django system check
uv run python manage.py check

# Lint (auto-fix)
uv run ruff check . --exclude .venv --fix

# Format
uv run ruff format . --exclude .venv

# Run tests (pytest not yet installed — T8 ticket)
uv run pytest

# Run a single test
uv run pytest accounts/tests.py::TestClassName::test_method -v

# Install pre-commit hooks (one-time)
uv run pre-commit install
```

## Architecture

### Settings split

- `countingcarbon/settings/base.py` — shared config; never import directly
- `countingcarbon/settings/dev.py` — `manage.py` default; loads `.env`, `DEBUG=True`, console email
- `countingcarbon/settings/prod.py` — `wsgi.py` default; reads all secrets from env, enforces HTTPS

Override with `DJANGO_SETTINGS_MODULE` env var. Copy `.env.example` to `.env` for local dev.

### App responsibilities

| App | Purpose |
|---|---|
| `accounts` | Auth (via allauth), Household/Membership/Invitation models, onboarding middleware |
| `catalogue` | Phase 2 — admin-defined slices, line items, factor sets (empty for now) |
| `entries` | PeriodicEntry + HouseholdSlicePreference; HTMX-driven data entry for Home Energy slice |
| `engine` | Pure-function calculation layer: `calculate.py` (pin factors), `annualise.py` (annualise + chart series) |
| `dashboard` | Annualised footprint, monthly trend chart, benchmark comparison strip |

### Data ownership model

Every piece of carbon data belongs to a **Household**, not a user. Users are members of households via `HouseholdMembership` (OneToOneField — one household per user, enforced at DB level). The `logged_by` field on entries is audit-only.

`User ──< HouseholdMembership >── Household ──< [entries] `

### Auth flow (allauth)

- Email-only login (`ACCOUNT_LOGIN_METHODS = {"email"}`), mandatory email verification
- `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` — unverified users cannot log in
- After login: `LOGIN_REDIRECT_URL = "/"`, no post-login redirect view

### Household onboarding

`accounts.middleware.HouseholdOnboardingMiddleware` intercepts every request from an authenticated user with no household and redirects to `/onboarding/`. Exempt prefixes: `/accounts/`, `/admin/`, `/onboarding/`, `/privacy/`, `/static/`.

### Invitation flow

1. Member sends invite → `HouseholdInvitation` created with `secrets.token_urlsafe(32)` token, 7-day expiry
2. Invitee clicks link → token stored in session under `accounts.views.SESSION_INVITE_KEY`
3. Invitee directed to `/accounts/login/` (has account) or `/accounts/signup/` (new user)
4. On `user_logged_in` signal (`accounts.signals.accept_pending_invite`) the session token is consumed and the invitation is accepted

### Templates

Project-wide templates live in `templates/` (not inside app directories). Per-app template subdirectories: `templates/account/` (allauth overrides), `templates/accounts/` (local views). The base template is `templates/base.html` — all pages extend it.

HTMX 2.0.4 and Chart.js 4.4.9 are loaded from CDN in `base.html`. Static CSS lives in `static/css/main.css`.

### Deployment (Railway)

`railway.toml` uses Nixpacks. `Procfile` `release` phase runs `migrate` + `collectstatic` on every deploy. `wsgi.py` defaults to `countingcarbon.settings.prod`. Required env vars: `SECRET_KEY`, `DATABASE_URL` (auto-injected by Railway Postgres plugin), optional `ALLOWED_HOSTS`.

### Phase 1 implementation status

- T1 ✅ Scaffold (Django 6, uv, settings split, HTMX/Chart.js, Railway config, ruff)
- T2 ✅ Accounts (allauth, registration, email verify, password reset, account deletion)
- T3 ✅ Households & invitations
- T4 ✅ Hard-coded Home Energy slice (HTMX entry form, inline edit, cadence preference)
- T5 ✅ Engine: `calculate()` + `recalculate()`, factor pinning, `ValidationError`
- T6 ✅ Dashboard v0: annualised headline, Chart.js trend line (`spanGaps: false`), benchmark strip
- T7, T8 pending (UI polish, tests/CI)
