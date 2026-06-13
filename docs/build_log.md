# CountingCarbon — Phase 1 Build Log

Generated: June 2026. Covers T1–T8 (all complete).

---

## T1 — Project scaffold ✅

### What was built

Django 6.0 project initialised with `uv`, deployable to Railway with a working "hello" landing page.

### Stack decisions locked in

| Concern | Choice |
|---|---|
| Runtime | Python 3.12 via `uv` |
| Framework | Django 6.0.6 |
| Database | PostgreSQL via `DATABASE_URL` (dj-database-url); SQLite fallback for local dev |
| Static files | whitenoise (CompressedManifestStaticFilesStorage) |
| Server | Gunicorn (2 workers, 2 threads) |
| Deploy target | Railway (Nixpacks builder) |
| Frontend JS | HTMX 2.0.4 + Chart.js 4.4.9, both CDN-pinned in `base.html` |
| Linting | ruff (lint + format), pre-commit hooks installed |

### Files created

```
countingcarbon/           Django project package
  settings/
    base.py               Shared config — DB via DATABASE_URL, whitenoise, allauth wired in
    dev.py                DEBUG=True, loads .env, console email backend
    prod.py               Reads SECRET_KEY/ALLOWED_HOSTS from env, HTTPS headers
  urls.py
  wsgi.py                 Defaults to settings.prod
  asgi.py
manage.py                 Defaults to settings.dev
templates/
  base.html               Master template — HTMX, Chart.js, nav, flash messages, footer
  hello.html              Landing page (placeholder)
static/css/main.css       Mobile-first stylesheet (green palette, form/button components)
Procfile                  web: gunicorn; release: migrate + collectstatic
railway.toml              Nixpacks, health check on /
.env.example
.gitignore
.pre-commit-config.yaml   ruff lint + format hooks
ruff.toml                 Rules: E/F/W/I/UP, E501 ignored
README.md                 Setup steps, project structure, deploy instructions
```

### Empty apps scaffolded

`accounts`, `catalogue`, `entries`, `engine`, `dashboard` — all added to `INSTALLED_APPS`.

### Acceptance

- `uv run python manage.py runserver` works from fresh clone (documented in README)
- Landing page returns HTTP 200
- `manage.py check` passes with no issues
- ruff passes on all files

---

## T2 — Accounts ✅

### What was built

Email/password registration with mandatory email verification, login, logout, password reset, account deletion, and a UK GDPR placeholder privacy policy. Powered by **django-allauth 65.x**.

### allauth configuration (in `settings/base.py`)

```python
ACCOUNT_LOGIN_METHODS = {"email"}          # no username
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"   # unverified users cannot log in
ACCOUNT_UNIQUE_EMAIL = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"  # dev only
```

### URLs

| URL | View |
|---|---|
| `/accounts/signup/` | allauth signup |
| `/accounts/login/` | allauth login |
| `/accounts/logout/` | allauth logout (confirmation page) |
| `/accounts/email/` | allauth manage emails |
| `/accounts/password/reset/` | allauth password reset request |
| `/accounts/password/reset/key/<key>/` | allauth set new password |
| `/accounts/confirm-email/<key>/` | allauth email confirmation |
| `/accounts/account/` | `accounts.views.account_detail` |
| `/accounts/account/delete/` | `accounts.views.account_delete` |
| `/privacy/` | Privacy policy (placeholder) |

### Account deletion

`account_delete` view hard-deletes the `User` row. Checks for last-member status (see T3) so the template can display the appropriate warning. On POST: logs out first, then deletes household if sole member, then deletes user.

### Files created

```
accounts/views.py         account_detail, account_delete
accounts/urls.py          app_name="accounts"
templates/account/        allauth template overrides (login, signup, logout,
                          email_confirm, verification_sent, password_reset*.html)
templates/accounts/       account.html, account_delete_confirm.html
templates/privacy.html    UK GDPR placeholder (data collected, retention, rights, cookies)
```

### Acceptance

- Registration → verification email (printed to console in dev) → verify → login ✅
- Unverified users blocked from login ✅
- Password reset round-trip ✅
- Account deletion removes User row ✅

---

## T3 — Households & invitations ✅

### What was built

The ownership model for all carbon data. One household per user (enforced at DB level), email-based invitations with 7-day expiry, household settings page, leave/delete flows.

### Data model

```
User ──< HouseholdMembership >── Household
                                     └──< HouseholdInvitation
```

#### `Household`
```python
name: CharField(200)
created_at: DateTimeField(auto_now_add)
member_count: property  # returns memberships.count()
```

#### `HouseholdMembership`
```python
user: OneToOneField(User)      # enforces one household per user
household: ForeignKey(Household)
joined_at: DateTimeField(auto_now_add)
```

OneToOneField means accessing `user.membership` raises `DoesNotExist` (caught as `AttributeError`) if the user has no household — used by the onboarding middleware.

#### `HouseholdInvitation`
```python
household: ForeignKey(Household, CASCADE)
email: EmailField
token: CharField(64, unique)   # secrets.token_urlsafe(32) auto-generated on save
invited_by: ForeignKey(User, SET_NULL, null=True)
created_at: DateTimeField(auto_now_add)
accepted_at: DateTimeField(null=True)

is_valid: property  # False if accepted or > 7 days old
accept(user): method  # creates membership, stamps accepted_at
```

### Onboarding middleware

`accounts.middleware.HouseholdOnboardingMiddleware` — sits after `AuthenticationMiddleware`. If authenticated user has no membership, redirects to `/onboarding/`. Exempt prefixes: `/accounts/`, `/admin/`, `/onboarding/`, `/privacy/`, `/static/`, `/favicon.ico`.

Added to `MIDDLEWARE` in `settings/base.py` after `allauth.account.middleware.AccountMiddleware`.

### Invitation flow (new user)

1. Existing member posts to `/accounts/household/invite/` with an email address
2. `HouseholdInvitation` created; invite email sent via `accounts.emails.send_invitation_email`
3. Invitee clicks link → `/accounts/invite/<token>/`
4. View stores token in `request.session["pending_invite_token"]`
5. Redirected to `/accounts/signup/` (new account) or `/accounts/login/` (existing)
6. After login, `allauth.account.signals.user_logged_in` fires → `accounts.signals.accept_pending_invite` pops the session token and calls `invitation.accept(user)`

This covers the full new-user path: signup → email verify → login → household joined, all via session continuity.

### URLs

| URL | View |
|---|---|
| `/onboarding/` | `accounts.views.onboarding` (create household) |
| `/accounts/household/` | `accounts.views.household_settings` |
| `/accounts/household/invite/` | `accounts.views.household_invite` (POST) |
| `/accounts/household/leave/` | `accounts.views.household_leave` |
| `/accounts/invite/<token>/` | `accounts.views.invite_accept` |

### Last-member handling

- Leaving: `household_leave` detects `member_count == 1`; confirmation page warns "this will delete the household and all its data"; POST cascade-deletes the household (which cascades memberships, invitations, and all entries)
- Account deletion: same check in `account_delete`

### Files created

```
accounts/models.py        Household, HouseholdMembership, HouseholdInvitation
accounts/middleware.py    HouseholdOnboardingMiddleware
accounts/emails.py        send_invitation_email()
accounts/signals.py       accept_pending_invite (user_logged_in receiver)
accounts/apps.py          AccountsConfig.ready() connects signals
templates/accounts/       onboarding.html, household.html, invite_accept.html,
                          invite_invalid.html, household_leave_confirm.html
                          (account_delete_confirm.html updated with last-member warning)
```

### Acceptance

- Two users can share one household via email invite ✅
- A user cannot belong to two households (OneToOneField constraint) ✅
- Invitation tokens are single-use and expire after 7 days ✅
- Last-member leaving/deletion cascades the household and all its data ✅

---

## T4 — Hard-coded Home Energy slice ✅

### What was built

The first data-entry slice: Home Energy, implemented as a hard-coded Python structure in `entries/slices.py`. Periodic entry form with HTMX partial swaps, cadence preference, edit-in-place, duplicate rejection.

### Data model

#### `HouseholdSlicePreference` (in `entries/models.py`)
```python
household: ForeignKey(Household, CASCADE)
slice_key: CharField(100)
cadence: CharField(choices=[monthly|quarterly|annual], default="monthly")
# unique_together: (household, slice_key)
```

#### `PeriodicEntry` (in `entries/models.py`)
```python
household: ForeignKey(Household, CASCADE)
slice_key: CharField(100)
period_start: DateField          # always 1st of the month/quarter/year
cadence: CharField(20)
inputs: JSONField                # raw user inputs {item_key: value_or_null}
pinned_factors: JSONField        # {item_key: str(factor)} — frozen at entry time
result_kg: DecimalField(12, 4)
formula_version: CharField(64)   # sha256 of slice_def at calculation time
logged_by: ForeignKey(User, SET_NULL, null=True)
created_at, updated_at: DateTimeField

# unique_together: (household, slice_key, period_start)
# ordering: ["-period_start"]
# period_label: property — "June 2026" / "Q2 2026" / "2026"
# period_end: property — exclusive end date for annualisation
```

### Slice definition (`entries/slices.py`)

```python
HOME_ENERGY_SLICE = {
    "key": "home_energy",
    "label": "Home Energy",
    "items": [
        {"key": "gas_kwh",          "factor": 0.18286, "negative": False, ...},
        {"key": "elec_kwh",         "factor": 0.20707, "negative": False, ...},
        {"key": "oil_litres",       "factor": 2.5202,  "negative": False, ...},
        {"key": "lpg_litres",       "factor": 1.5534,  "negative": False, ...},
        {"key": "solar_export_kwh", "factor": 0.20707, "negative": True,  ...},
    ],
}
```

All factors sourced from DESNZ 2024. Solar export uses the grid electricity factor as a negative contribution (credit).

### HTMX interaction design

**Add entry** — form `hx-post="/entries/home-energy/add/"` with `hx-target="#entries-section"` `hx-swap="outerHTML"`. Server always returns the full `#entries-section` partial (form + table). Success shows a save-flash banner with the computed kg CO₂e.

**Edit entry** — "Edit" button on each row: `hx-get="…/edit-form/"` `hx-target="#entry-N"` `hx-swap="outerHTML"`. Returns `entry_edit_row.html` (inputs inline in the table row). Save button: `hx-post="…/edit/"` `hx-include="closest tr"` — valid HTML (no `<form>` inside `<tr>`), HTMX serialises inputs from the row. Cancel button: `hx-get="…/row/"` restores the read-only row.

**CSRF** — global `htmx:configRequest` listener in `base.html` forwards the `csrftoken` cookie as the `X-CSRFToken` header on all HTMX requests (required because edit rows cannot use Django's `{% csrf_token %}` form field).

### URLs (`entries/urls.py`, app_name="entries")

| URL | View | Purpose |
|---|---|---|
| `/entries/` | redirect | → `/entries/home-energy/` |
| `/entries/home-energy/` | `home_energy` | Full page |
| `/entries/home-energy/add/` | `add_entry` | POST, HTMX |
| `/entries/home-energy/cadence/` | `update_cadence` | POST, redirect |
| `/entries/home-energy/<id>/row/` | `entry_row` | GET, HTMX (cancel edit) |
| `/entries/home-energy/<id>/edit-form/` | `edit_entry_form` | GET, HTMX (open edit) |
| `/entries/home-energy/<id>/edit/` | `edit_entry` | POST, HTMX (save edit) |

### Files created

```
entries/slices.py                       HOME_ENERGY_SLICE definition + SLICES dict
entries/models.py                       HouseholdSlicePreference, PeriodicEntry
entries/views.py                        All entry views
entries/urls.py
entries/templatetags/entries_extras.py  dict_get filter (template access to JSONField values)
templates/entries/home_energy.html      Full page
templates/entries/partials/
  entries_section.html                  Add form + past entries table (HTMX target)
  entry_row.html                        Read-only table row
  entry_edit_row.html                   Inline edit form row
```

### Acceptance

- Entering 1000 kWh gas stores `result_kg = 182.8600` with `pinned_factors = {"gas_kwh": "0.18286", ...}` ✅
- Solar export entry produces negative `result_kg` ✅
- Editing recomputes from `pinned_factors`, not current constants ✅
- Duplicate period rejected with "An entry for this period already exists" message ✅

---

## T5 — Engine seed: calculate & pin ✅

### What was built

Pure-function calculation module in `engine/calculate.py`. No database access — the `entries` app handles persistence. Designed as the seam where Phase 2's formula engine replaces the arithmetic without changing the calling code.

### Public API

```python
from engine.calculate import calculate, recalculate, ValidationError, CalculationResult

# New entry — uses current slice factors
result = calculate(slice_def, inputs)
# result.result_kg: Decimal
# result.pinned_factors: dict {item_key: str(factor)}
# result.formula_version: str (16-char sha256 hex of slice_def)

# Edit — uses stored pinned_factors, never current constants
new_result_kg = recalculate(slice_def, inputs, pinned_factors)
# returns: Decimal
```

### `calculate()` behaviour

1. Validates all input keys against the slice's declared items — unknown keys raise `ValidationError`
2. Validates values: must be numeric and non-negative — wrong types or negatives raise `ValidationError`
3. For each item: `contribution = quantity * factor`; positive items add, negative items (`"negative": True`) subtract
4. Returns `CalculationResult` with `result_kg` quantised to 4 decimal places, `pinned_factors` dict (all factors from the slice, even items not provided — so the full factor snapshot is always stored), and `formula_version`

### `recalculate()` behaviour

Same input validation as `calculate()`, but uses `pinned_factors[key]` instead of `slice_def[item][factor]`. Falls back to current factor only if a key is somehow missing from pinned (defensive). Returns `Decimal` only — the caller (edit view) keeps the original `pinned_factors` and `formula_version` on the entry record unchanged.

### `formula_version`

`sha256(json.dumps(slice_def, sort_keys=True))[:16]` — changes whenever any factor value or structure in the slice definition changes. This lets Phase 2's recalculation feature detect stale entries.

### `ValidationError`

```python
class ValidationError(Exception):
    errors: dict  # {field_key: human_readable_message}
```

Structured so the form layer can render per-field errors.

### Verified calculations

| Input | Expected | Actual |
|---|---|---|
| 1000 kWh gas | 182.8600 kg | 182.8600 kg ✅ |
| 500 kWh solar export | −103.5350 kg | −103.5350 kg ✅ |
| 1000 kWh gas + pinned factor 0.18286 (recalculate) | 182.8600 kg | 182.8600 kg ✅ |

### Files created

```
engine/calculate.py    CalculationResult, ValidationError, calculate(), recalculate()
```

---

---

## T6 — Dashboard v0 ✅

### What was built

An annualised carbon footprint dashboard: headline figure, monthly trend chart (Chart.js), and a benchmark comparison strip.

### Engine additions (`engine/annualise.py`)

Pure functions, no database access — unit testable in isolation:

```python
annualise(result_kg, cadence) -> Decimal
# monthly ×12, quarterly ×4, annual ×1

annualise_latest(entry_list) -> {slice_key: Decimal}
# Takes entries ordered newest-first; returns one annualised kg per slice

build_chart_series(entry_list, today=None) -> {"labels": [...], "data": [...]}
# Month-by-month data from earliest entry to current month.
# Entries contribute their per-month equivalent (result_kg / period_months).
# Months with no entry coverage return None (honest gap — Chart.js spanGaps: false).
```

### Dashboard app

#### `dashboard/views.py`

Two views:

**`index`** — main page
- Queries all household `PeriodicEntry` rows ordered newest-first
- Calls `annualise_latest()` to get the most recent annualised figure per slice
- Builds a proportional benchmark strip (all bars scaled to the largest value)
- Passes `slices` (list of `{key, label, kg}`), `benchmarks`, `total_kg`, `total_tonnes`, `household_bar_pct` to the template

**`chart_data`** — JSON endpoint
- Calls `build_chart_series()` on all household entries
- Returns `{labels: [...], household: [float|null, ...], benchmarks: [{key, label, monthly_kg, color}]}`
- The `household` array uses `null` for months with no data

#### `dashboard/urls.py`

| URL | View | Name |
|---|---|---|
| `/dashboard/` | `index` | `dashboard:index` |
| `/dashboard/chart-data/` | `chart_data` | `dashboard:chart_data` |

### Benchmarks

Sourced from `fixtures/catalogue_seed.json` (kg CO₂e per person per year, `scale_by_household: true`):

| Benchmark | Per person | 2-person example |
|---|---|---|
| UK average | 10,000 kg | 20,000 kg |
| Global average | 4,700 kg | 9,400 kg |
| UK CCC 2030 target | 2,500 kg | 5,000 kg |
| 1.5°C fair share | 2,300 kg | 4,600 kg |

### Chart

Fetched from `/dashboard/chart-data/` via `fetch()`. Chart.js 4.4.9 line chart with:
- `fill: true`, green background, 2px border
- `spanGaps: false` — null data points render as gaps (no interpolation)
- Tooltip shows kg or "no data" for gap months
- Y-axis: "kg CO₂e / month"

### Templates

```
templates/dashboard/index.html   Extends base.html
```

Sections: no-data CTA → headline number → slice breakdown table → trend chart → benchmark bar strip.

### CSS additions (`static/css/main.css`)

New classes: `.dash-headline`, `.chart-wrap`, `.benchmarks`, `.benchmark-row`, `.benchmark-row__bar-wrap`, `.benchmark-row__bar`, `.benchmarks__divider`.

### Acceptance

- Dashboard reflects a new entry immediately after save (server-side rendering, no caching) ✅
- 3-person household sees benchmarks ×3 (e.g. UK average = 30,000 kg) ✅
- A skipped month shows as a gap in the chart (`null` in dataset, `spanGaps: false`) ✅
- `manage.py check` passes ✅, ruff passes ✅

---

---

## T7 — Base UI & responsive layout ✅

### What was built

A full design pass bringing all Phase 1 flows up to "public product" standard, with a working responsive nav and confirmed no-breakage at 360px width.

### Nav (mobile hamburger)

`base.html` now includes a hamburger `<button>` (`aria-expanded`, `aria-controls`) that toggles `.nav-menu--open` on `#nav-menu`. At ≤600px the ul is hidden by default and revealed on tap; at >600px the hamburger is hidden and the ul is always visible. The toggle uses 3 lines of inline JS with no external dependency.

**Active state**: `aria-current="page"` applied to the current route via `request.path` checks. Styled with white background highlight.

**Footer**: removed the dead `/factors/` link; replaced with "Emission factors: DESNZ 2024" plain text.

### Design changes (`static/css/main.css`)

Full rewrite of the stylesheet preserving all class names. Key changes:

| Area | Change |
|---|---|
| Background | `#f7f8f7` page background (off-white) — cards read as white on it |
| Cards | `box-shadow: 0 1px 4px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)` |
| Border | `#d4dbd6` (slightly greener neutral) |
| Table headers | Uppercase with letter-spacing; `var(--green-xlight)` background |
| `h2` in cards | `color: var(--green-dark)`, smaller font-size (1.05rem) |
| Buttons | `min-height: 44px` for touch targets; `--sm` variant: 36px |
| Focus rings | Replaced `outline` with `box-shadow: 0 0 0 3px rgba(45,138,78,0.18)` |
| Auth card | `box-shadow` added; padding reduced on mobile (≤480px) |
| `input[type=month]` | Added to the global input selector (was missing) |

### Landing page (`hello.html`)

- Fixed broken link: `/accounts/register/` → `{% url 'account_signup' %}`
- Added feature strip (3 cards: Home energy / Trend chart / Household sharing)
- Authenticated users see "Go to dashboard" instead of sign-up CTA
- `hero__cta` uses `flex-wrap: wrap` so buttons reflow at any width

### 360px audit

| Flow | Status |
|---|---|
| Landing page | Single-column, all buttons full-width ✅ |
| Nav (collapsed) | Hamburger toggle, items stack vertically ✅ |
| Sign in / Register | `auth-card` full-width, 20px padding ✅ |
| Onboarding / Household | Same auth-card pattern ✅ |
| Enter data (entry form) | `auto-fill` grid → 1 column at 328px ✅ |
| Enter data (table) | Horizontal scroll via `.table-scroll` ✅ |
| Dashboard | Headline uses `clamp()`; benchmark bars at 360px: 6rem+bar+5rem grid ✅ |

### Files changed

```
templates/base.html           Hamburger nav, ARIA attributes, dead link removed
templates/hello.html          Fixed URL, added feature strip, auth-aware CTA
static/css/main.css           Full design pass — all existing class names preserved
```

---

---

## T8 — Tests & CI ✅

### What was built

A complete test suite (52 tests) and GitHub Actions CI workflow running on every push and PR.

### Test structure

```
engine/tests/
  test_calculate.py   24 tests — calculate() and recalculate(), no DB
  test_annualise.py   20 tests — annualise(), annualise_latest(), build_chart_series(), no DB
tests/
  factories.py        UserFactory, HouseholdFactory, MembershipFactory,
                      InvitationFactory, SlicePreferenceFactory, PeriodicEntryFactory
  test_flows.py       8 tests — end-to-end HTTP flows (DB required)
conftest.py           auth_client fixture (project root)
```

### Key decisions

**factory_boy password persistence** — `skip_postgeneration_save = True` suppresses the deprecation warning about double-save, but a `@post_generation` hook explicitly calls `obj.save(update_fields=["password"])` to ensure the hashed password reaches the DB. Django session auth hash verification reads from the DB on every request; without this, `force_login` appears to work but sessions are immediately invalidated.

**auth_client fixture** — `force_login` must specify `backend="allauth.account.auth_backends.AuthenticationBackend"` explicitly because allauth's backend is the only one in `AUTHENTICATION_BACKENDS`. The fixture creates a fresh `Client()` per call so tests don't share session state.

**Pure engine tests** — `test_calculate.py` and `test_annualise.py` use no DB at all (`@pytest.mark.django_db` not applied). Duck-typed `_entry()` helper objects stand in for `PeriodicEntry` instances in annualise tests.

### Flow tests (`test_flows.py`)

| Test | Assertion |
|---|---|
| `test_gas_entry_appears_annualised_on_dashboard` | 1000 kWh gas → "2194" on dashboard |
| `test_dashboard_shows_no_data_without_entries` | No entries → "No data" shown |
| `test_chart_data_endpoint_returns_json` | `/dashboard/chart-data/` returns labels/household/benchmarks |
| `test_chart_gap_for_skipped_month` | Jan + Mar entered → Feb index is `null` |
| `test_benchmark_scales_by_member_count` | 2-member household → UK average "20,000" |
| `test_unauthenticated_redirected_from_entries` | Anonymous → 302 |
| `test_user_without_household_redirected_to_onboarding` | No household → `/onboarding/` |
| `test_onboarding_creates_household` | POST `/onboarding/` → `HouseholdMembership` exists |

### GitHub Actions (`.github/workflows/ci.yml`)

Runs on push to `main` and on every PR:

1. `postgres:16` service container (`--health-cmd pg_isready` waits for readiness)
2. `astral-sh/setup-uv@v4` with caching
3. `uv sync` — installs all deps including dev group
4. `ruff check` — lint
5. `ruff format --check` — format check
6. `python manage.py migrate` — against Postgres service
7. `pytest --cov` — full suite with coverage across engine, dashboard, entries, accounts

### Files created

```
conftest.py                     auth_client fixture
tests/__init__.py
tests/factories.py              All model factories
tests/test_flows.py             End-to-end HTTP tests
engine/tests/__init__.py
engine/tests/test_calculate.py  Engine unit tests
engine/tests/test_annualise.py  Annualisation unit tests
.github/workflows/ci.yml        GitHub Actions workflow
```

### Acceptance

- 52 tests pass (`pytest -q`) ✅
- Pure engine tests require no DB ✅
- `auth_client` fixture works with allauth's auth backend ✅
- GitHub Actions workflow: lint + format + migrate + pytest + coverage ✅

---

## Running the project

```bash
# Install dependencies
uv sync

# Copy environment file and start the server
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py runserver
```

Browse to http://127.0.0.1:8000/ — register, create a household, navigate to "Enter data".

To verify the engine in isolation:
```bash
uv run python -c "
from engine.calculate import calculate
from entries.slices import HOME_ENERGY_SLICE
r = calculate(HOME_ENERGY_SLICE, {'gas_kwh': 1000})
print(r.result_kg, r.pinned_factors['gas_kwh'])
"
```
