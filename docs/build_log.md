# CountingCarbon — Build Log

Generated: June 2026. Covers T1–T17 (Phase 1 and Phase 2 complete, Phase 3 in progress).

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

---

## T9 — Catalogue models ✅

### What was built

A `catalogue` Django app with 8 models forming the admin-editable data layer that replaces the Phase 1 hard-coded slice definitions.

### Data model

```
Slice ──< LineItem ──< InputField
                  └──< Formula
FactorSet ──< Factor
BandTable ──< Band
```

#### `Slice`
```python
key: CharField(100, unique)
name, icon, description: text fields
entry_mode: CharField(choices=[periodic|event|annual_estimate])
display_order: PositiveIntegerField
active: BooleanField
```

#### `LineItem`
```python
slice: ForeignKey(Slice, CASCADE)
key: CharField(100)           # unique within slice
label, help_text, group: text
display_order: PositiveIntegerField
active: BooleanField
published_formula(): method   # latest published Formula or None
# unique_together: (slice, key)
```

#### `InputField`
```python
line_item: ForeignKey(LineItem, CASCADE)
name: CharField(100)          # unique within line_item
label: CharField
field_type: CharField(choices=[decimal|integer|boolean|choice|text])
unit: CharField
min_value: DecimalField(nullable)
choices: JSONField(nullable)  # [{value, label}, ...] for choice fields
display_order: PositiveIntegerField
# unique_together: (line_item, name)
```

#### `Formula`
```python
line_item: ForeignKey(LineItem, CASCADE)
expression: TextField          # DSL expression string
version: PositiveIntegerField  # auto-incremented on publish
test_cases: JSONField          # [{inputs: {...}, expected: float}, ...]
published_at: DateTimeField(nullable)
is_published: property
# unique_together: (line_item, version)
```

#### `FactorSet` / `Factor`
```python
FactorSet: name, source, licence, valid_from, valid_to(nullable), region
Factor: factor_set FK, key, value(Decimal 14,6), unit, citation
# unique_together Factor: (factor_set, key)
```

#### `BandTable` / `Band`
Step-function lookup tables for future non-linear factors.
```python
BandTable.lookup(value) -> Decimal  # highest lower_bound ≤ value wins
```

#### `resolve_factors(keys, as_of_date, region='GB') -> dict`
Module-level function. Returns `{key: Decimal}` from factor sets valid on `as_of_date`. Raises `ValueError` on missing keys or ambiguous overlapping sets.

### Data migrations

- `0002_seed_home_energy.py` — seeds DESNZ 2024 factor set (home energy factors), home_energy slice with 5 line items and published v1 formulas
- `0003_seed_flights.py` — seeds flight factors and flights slice (event mode) with 1 line item and 3 test cases

### Files created

```
catalogue/models.py
catalogue/admin.py        (see T13 for final admin UX)
catalogue/migrations/0001_initial.py
catalogue/migrations/0002_seed_home_energy.py
catalogue/migrations/0003_seed_flights.py
```

---

## T10 — Formula DSL & catalogue engine ✅

### What was built

A hand-rolled formula DSL (lexer → AST → evaluator) and a catalogue-backed calculation engine that replaces Phase 1's hard-coded arithmetic.

### `engine/dsl.py`

**Grammar:**
```
expr        := comparison
comparison  := addition (('=' | '!=' | '<' | '<=' | '>' | '>=') addition)?
addition    := term (('+' | '-') term)*
term        := unary (('*' | '/') unary)*
unary       := '-' unary | primary
primary     := NUMBER | IDENT | call | '(' expr ')'
call        := IF(cond, then, else)
             | MIN(a, b, ...) | MAX(a, b, ...)
             | ROUND(x, places)
             | LOOKUP("table", value)
             | factor("key")
```

Boolean comparisons return `Decimal(1)` (true) or `Decimal(0)` (false) — composable with arithmetic.

**Safety limits:** `MAX_EXPRESSION_LENGTH=1000`, `MAX_AST_DEPTH=20`, `MAX_EVAL_STEPS=500`.

**Errors:** `DSLSyntaxError` (parse-time), `DSLEvalError` (eval-time).

**Helper functions:**
- `parse(expression) -> AST`
- `eval_expression(expression, context, factors, lookup_fn) -> Decimal`
- `collect_factor_keys(node) -> set` — static analysis of factor() references
- `collect_identifiers(node) -> set` — static analysis of identifier references

### `engine/catalogue_calculate.py`

```python
class CatalogueValidationError(Exception):
    errors: dict  # {field_path: message}  field_path = "{li_key}__{field_name}"

@dataclass
class CatalogueResult:
    result_kg: Decimal
    pinned_factors: dict   # {factor_key: str(value)}
    formula_version: str   # "gas:v1|electricity_import:v2|..." joined by "|"

def catalogue_calculate(slice_obj, inputs, as_of_date) -> CatalogueResult
    # inputs: {line_item_key: {field_name: raw_value}}
    # Validates all inputs, resolves factors in one DB query, evaluates formulas, sums total.

def catalogue_recalculate(line_item, item_inputs, pinned_factors, formula_expression) -> Decimal
    # For edits — uses stored pinned_factors, never re-resolves from DB.
```

**Text field handling:** `field_type="text"` values are stored in inputs but excluded from the numeric formula evaluation context. The DSL evaluator only receives `Decimal` values.

### Files created

```
engine/dsl.py
engine/catalogue_calculate.py
```

---

## T11 — Catalogue seed migrations ✅

Covered within T9 above (`0002_seed_home_energy.py`, `0003_seed_flights.py`). The Phase 1 `PeriodicEntry` records are left untouched — their `pinned_factors` remain valid. Phase 1 vs Phase 2 entry detection: `isinstance(next(iter(entry.inputs.values())), dict)`.

---

## T12 — Phase 2 entry views (home energy + flights) ✅

### What was built

Rewrote the home energy entry views to use `catalogue_calculate()`, and added a complete flights event-entry system.

### `EventEntry` model

```python
household: ForeignKey(Household, CASCADE, related_name="event_entries")
slice_key: CharField(100)
event_date: DateField
inputs: JSONField        # flat {field_name: value} (single line item per event)
pinned_factors: JSONField
result_kg: DecimalField(12, 4)
formula_version: CharField(200)
logged_by: ForeignKey(User, SET_NULL, null=True)
created_at, updated_at: DateTimeField
# ordering: ["-event_date", "-created_at"]
```

### Form field naming convention

HTML input names use `{line_item_key}__{field_name}` (double underscore). `_extract_catalogue_inputs()` in views.py parses these into the nested `{li_key: {field_name: value}}` dict that `catalogue_calculate()` expects.

EventEntry inputs are stored flat (no nesting) since each event covers exactly one line item.

### Backwards compatibility

Phase 1 entry edits use the original `recalculate(HOME_ENERGY_SLICE, flat_inputs, pinned_factors)`. Detection: `_is_phase2_entry(entry)` checks if `first_value` is a `dict`.

### Flights URLs

```
/entries/flights/                     flights (list + add form)
/entries/flights/add/                 add_flight (POST, HTMX)
/entries/flights/<id>/row/            flight_row (HTMX cancel)
/entries/flights/<id>/edit-form/      edit_flight_form (HTMX open edit)
/entries/flights/<id>/edit/           edit_flight (POST, HTMX save)
/entries/flights/<id>/delete/         delete_flight (POST, HTMX delete)
```

### Templates added

```
templates/entries/flights.html
templates/entries/partials/flights_section.html
templates/entries/partials/flight_row.html
templates/entries/partials/flight_edit_row.html
```

### Files changed

```
entries/models.py          Added EventEntry
entries/views.py           Rewrote home energy views; added all flight views
entries/urls.py            Added flights URLs
entries/migrations/0002_evententry.py
templates/entries/partials/entries_section.html   Updated for catalogue fields
templates/entries/partials/entry_row.html
templates/entries/partials/entry_edit_row.html
templates/base.html        Nav split: "Home Energy" + "Flights" links
static/css/main.css        Appended: .page-subtitle, .help-text, .checkbox-label
```

---

## T13 — Catalogue admin UX ✅

### What was built

Enhanced admin for formula lifecycle management and factor set import.

### Formula editor

`FormulaForm` uses a custom `MonospaceTextarea` widget (font-family: monospace, spellcheck off) for the `expression` field. Applied in both `FormulaAdmin` and `FormulaInline`.

### Admin actions on `FormulaAdmin`

**"Validate & run test cases"** — for each selected formula: parses the expression, resolves current factors from the DB, evaluates every test case, reports pass/fail with expected vs actual values as Django messages.

**"Publish (blocked if any test case fails)"** — for each selected draft formula: runs all test cases first; if any fail, blocks publish and reports the failure. If all pass (or no test cases), sets `published_at = timezone.now()`.

### FactorSet JSON import

Custom admin view at `/admin/catalogue/factorset/import-json/` (linked from the FactorSet changelist via a custom template). Two-step flow:

1. **Upload** — file parsed, JSON validated, `load_catalogue --dry-run` run to produce a diff
2. **Confirm** — diff shown in a `<pre>` block with a "Confirm import" button; file content held in session between steps
3. **Apply** — `load_catalogue` runs for real; success message shown

### Entry audit admin (`entries/admin.py`)

`PeriodicEntryAdmin` and `EventEntryAdmin` registered with all fields read-only. `formula_version` and `pinned_factors` visible in a collapsed "Audit trail" fieldset — allows support staff to see exactly which formula version and factor values produced each entry's `result_kg`.

### Auth fix

Added `"django.contrib.auth.backends.ModelBackend"` to `AUTHENTICATION_BACKENDS` (before the allauth backend). Required for Django admin login — the original config had only the allauth backend, which does not authenticate superusers created via `createsuperuser`.

### Files changed

```
catalogue/admin.py                                   Full rewrite with actions + import view
entries/admin.py                                     New: PeriodicEntryAdmin, EventEntryAdmin
templates/admin/catalogue/factorset_import.html      New: import upload/preview/confirm template
templates/admin/catalogue/factorset/change_list.html New: adds "Import from JSON" button
countingcarbon/settings/base.py                      Added ModelBackend to AUTHENTICATION_BACKENDS
```

---

## T14 — `load_catalogue` management command ✅

### What was built

`catalogue/management/commands/load_catalogue.py` — idempotent upsert of all catalogue data from a JSON seed file.

### Usage

```bash
uv run python manage.py load_catalogue [path] [--dry-run]
# Default path: fixtures/catalogue_seed.json
```

### Behaviour

| Object | Match key | On mismatch |
|---|---|---|
| `FactorSet` | (name, region) | Created if missing |
| `Factor` | (factor_set, key) | Created if missing; value/unit/citation updated if changed |
| `Slice` | key | Created if missing; name/icon/description/display_order updated if changed |
| `LineItem` | (slice, key) | Created if missing; label/help_text/group/display_order updated |
| `InputField` | (line_item, name) | Created if missing; label/min_value/choices updated |
| `Formula` | (line_item, expression) | If latest published formula matches expression → no-op (test_cases updated in-place if different). If expression differs → new version created and published. Old versions preserved for audit. |

`--dry-run` wraps the entire operation in `transaction.atomic()` then rolls back, printing `[CREATED]`/`[UPDATED]` lines without writing to the DB.

### Factor key reconciliation

The Phase 1 migrations seeded the DESNZ 2024 factor set with old key names (`elec_kwh`, `oil_litres`, `lpg_litres`). The seed file uses canonical names (`elec_grid_kwh`, `heating_oil_litre`, `lpg_litre`). `load_catalogue` adds the new keys alongside the old ones and publishes new formula versions (v2) for the affected home energy line items. Old v1 formulas and factor keys are preserved.

### CI integration

A "Seed catalogue" step (`python manage.py load_catalogue`) was added to `.github/workflows/ci.yml` after the migrate step, making the full catalogue available during every CI run.

### Files created

```
catalogue/management/__init__.py
catalogue/management/commands/__init__.py
catalogue/management/commands/load_catalogue.py
```

---

## T15 — Catalogue parity tests ✅

### What was built

`tests/test_catalogue_parity.py` — 46 parametrised tests verifying every formula and test case in `fixtures/catalogue_seed.json` produces the expected result from the reference spreadsheet.

### Test design

All 46 test cases are collected at import time from the seed file using `_build_cases()`. Each test:
1. Parses the formula expression to find `factor()` key references
2. Calls `resolve_factors(keys, as_of=2025-01-01)` against the live test DB
3. Evaluates the expression with numeric inputs as `Decimal`; text fields excluded
4. Asserts `abs(result - expected) <= Decimal("0.01")` — the ±0.01 tolerance covers the 2 decimal place rounding used in the reference spreadsheet

A session-scoped `_full_catalogue` fixture calls `call_command("load_catalogue", verbosity=0)` once before any test in the module, using `django_db_blocker.unblock()` to commit the data outside test transactions.

### Coverage

| Slice | Line items | Test cases |
|---|---|---|
| home_energy | 5 | 5 |
| transport | 10 | 10 |
| flights | 1 | 3 |
| food | 16 | 16 |
| purchases | 12 | 12 |
| **Total** | **44** | **46** |

### Bug found by CI

`PeriodicEntry.formula_version` was `max_length=64`. After `load_catalogue` promotes home energy formulas to v2, the version string `gas:v1|electricity_import:v2|heating_oil:v2|lpg:v2|solar_export:v2` is 66 characters. CI caught this; field raised to `max_length=500` with migration `entries/0003_formula_version_max_length.py`.

### Files created

```
tests/test_catalogue_parity.py
entries/migrations/0003_formula_version_max_length.py
```

### Final test count

98 tests pass: 24 engine unit, 20 annualise unit, 8 flow tests, 46 parity tests.

---

## T16 — Annual-estimate entry mode ✅

### What was built

Three new entry slices wired end-to-end, covering all major footprint categories beyond home energy.

**Transport (periodic)** — catalogue-backed periodic entry at `/entries/transport/`. Uses the same `entries_section.html` / `entry_row.html` / `entry_edit_row.html` partials as home energy. The partials were refactored to accept URL names as template context variables (`url_add`, `url_row`, `url_edit_form`, `url_edit`) so the same HTML can serve any periodic slice without duplication.

**Flights (event mode)** — already implemented in T12; wired into the nav in this ticket.

**Food (annual estimate)** — `/entries/food/`. Two modes selectable via a tab bar:
- *Quick*: choose a diet type (high meat / medium meat / low meat / vegetarian / vegan) and number of people. Builds inputs for a single `diet_*` line item.
- *Detailed*: enter annual kg per food group (beef/lamb, pork, poultry, fish, dairy, eggs, vegetables, fruit, cereals, legumes, nuts). All 11 line items summed.
Saves an `AnnualEstimate` record; history table shows the last 5 estimates.

**Purchases & Services (annual estimate)** — `/entries/purchases/`. Single form covering 12 line items: clothing (kg), clothing returns (parcels), smartphones, laptops/tablets, TVs, appliances, furniture (£), garden/DIY (£), restaurant meals, hotel nights, streaming hours/week, general online shopping (£). Saves an `AnnualEstimate`.

### Key design decisions

- **`AnnualEstimate` model** — new model in `entries/models.py`. Stores `slice_key`, `effective_from`, `inputs`, `pinned_factors`, `result_kg`, `formula_version`, `mode` (quick/detailed for food), `logged_by`. Ordered by `-effective_from`, `-created_at`; latest record is the current estimate. Preserves history; no in-place edit.
- **Generic periodic partials** — URL names passed as context vars rather than hardcoded, enabling transport to reuse the home energy HTMX partials unchanged.
- **Food mode selection** — tab links use `?mode=quick` / `?mode=detailed` GET params; the mode is also passed as a hidden field in the POST so the HTMX swap returns the correct form variant.
- **Catalogue calculation for food** — `catalogue_calculate` is called with only the relevant line items in `inputs`; absent items default to zero, so passing a single `diet_medium_meat` key sums correctly without touching the other 15 food line items.

### Files created / modified

```
entries/models.py                           AnnualEstimate model added
entries/migrations/0004_annual_estimate.py  Migration
entries/views.py                            Rewritten: _TRANSPORT_URLS, _HOME_ENERGY_URLS dicts;
                                            transport_*, food*, purchases* views; generic
                                            _periodic_add/row/edit_form/edit helpers
entries/urls.py                             transport, food, purchases URL patterns added
templates/entries/transport.html            New periodic page (mirrors home_energy.html)
templates/entries/food.html                 New page with tab-bar include
templates/entries/purchases.html            New page
templates/entries/partials/food_section.html       HTMX partial (quick/detailed modes)
templates/entries/partials/purchases_section.html  HTMX partial
templates/entries/partials/entries_section.html    url_add context var (was hardcoded)
templates/entries/partials/entry_row.html          url_edit_form context var
templates/entries/partials/entry_edit_row.html     url_edit, url_row context vars
templates/base.html                         Transport, Food, Purchases nav links added
```

### Dashboard impact

`dashboard/views.py` updated to aggregate all three entry modes:
- Periodic (home energy, transport) → `annualise_latest(entries)` as before
- Flights → trailing-12-month `EventEntry` sum
- Food / Purchases → `AnnualEstimate.objects.filter(...).first().result_kg`

---

## T17 — Dashboard v1: trends & composition ✅

### What was built

Three dashboard improvements: a composition doughnut chart, per-slice trend lines, and removal of all Phase-1 placeholder copy.

**Composition doughnut chart** — new canvas `composition-chart` beside the breakdown table. Data passed via Django's `json_script` tag (XSS-safe, handles Decimal serialisation). Chart.js doughnut with `cutout: '60%'`, colour-coded per slice, tooltip shows kg and %. Side-by-side layout with the breakdown table on screens ≥640px; stacked on mobile.

**Trend chart upgrade** — `chart_data` endpoint now returns `slice_series` when multiple periodic slices exist. Frontend detects this and renders one stacked-area series per slice (each in its slice colour) plus a dashed grey total line on top. Single-slice households keep the existing single-line view unchanged.

**Per-slice chart_data** — `build_chart_series` is called once per periodic slice key, then labels are aligned to the longest series (shorter series padded with `None`). A `total` series is computed by summing non-`None` values per month.

**Copy cleanup** — "Tracking: home energy (Phase 1)" replaced with a dynamic list of tracked category labels. "Your home energy" in the benchmark strip replaced with "Your total". No-data empty state links to the new slices.

### Key design decisions

- `json_script` tag used instead of a custom `safe_json` filter — built-in, handles `Decimal` → string via `DjangoJSONEncoder`, and prevents XSS.
- Label alignment via a dict (`{label: index}`) rather than date arithmetic — simpler and handles any cadence combination.
- `slice_series` is `null` (not present) for single-slice households so the JS can fall through to the existing single-line path without branching on slice count.

### Files created / modified

```
dashboard/views.py          SLICE_COLORS dict; chart_data returns slice_series;
                            tracked_labels added to index context
templates/dashboard/index.html   Doughnut canvas + json_script data; per-slice trend JS;
                                 dynamic tracked labels; "Your total" label
static/css/main.css         .tab-bar / .tab / .tab--active; .headline-number; p.meta;
                            .slice-dot; .composition-layout; .chart-wrap--doughnut;
                            .chart-note
```

---

## Running the project

```bash
# Install dependencies
uv sync

# Copy environment file, migrate, seed catalogue, start the server
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py load_catalogue
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
