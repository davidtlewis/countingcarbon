# CountingCarbon — Phase 1 Tickets: Walking Skeleton

**Goal:** prove the entry → calculate → pin → display loop end to end with one hard-coded slice (Home Energy), real auth and a real household model. Everything Phase 2 builds (catalogue, formula engine) replaces the hard-coded parts without changing the loop.

**Reference docs:** `docs/spec.md` (the full spec). Seed data for Phase 2 lives in `fixtures/catalogue_seed.json` — not used in Phase 1, but its shape informed the models.

Suggested order: T1 → T2 → T3 → (T4+T5 together) → T6 → T7 throughout, T8 from T1 onwards.

---

## T1 — Project scaffold

Set up the repository and deployable skeleton.

- Django 6.x project managed with `uv`; apps created empty: `accounts`, `catalogue`, `entries`, `engine`, `dashboard`
- PostgreSQL via `DATABASE_URL` (dj-database-url); SQLite fallback for quick local hacking is acceptable but Postgres is the dev default (JSONB is load-bearing later)
- Settings split (base/dev/prod), `.env` handling, `SECRET_KEY` from env
- HTMX vendored or CDN-pinned in the base template; Chart.js pinned (used from T6)
- Gunicorn + Railway deploy config; deploys green with a "hello" page
- Pre-commit: ruff (lint + format)

**Acceptance**
- [ ] `uv run python manage.py runserver` works from a fresh clone with documented steps in README
- [ ] CI (T8) green on main
- [ ] Railway deployment serves the placeholder page over HTTPS at countingcarbon.dtlewis.com (or a temporary Railway URL until DNS is pointed)

## T2 — Accounts

Registration and authentication. Recommend `django-allauth` (email-only, no social providers).

- Email + password registration with email verification
- Login, logout, password reset
- UK GDPR groundwork: privacy policy page (placeholder text fine), account deletion view that hard-deletes the user (household handling refined in T3)

**Acceptance**
- [ ] New user can register, receives verification email (console backend in dev), verifies, logs in
- [ ] Password reset round-trips
- [ ] Unverified users cannot log in
- [ ] Deleting an account removes the User row

## T3 — Households & invitations

The ownership model for all data. Decisions from spec: one household per user, equal rights, fully pooled.

Models:
- `Household(name, created_at)`
- `HouseholdMembership(user FK, household FK, joined_at)` — unique on user (one household per user in v1)
- `HouseholdInvitation(household FK, email, token, invited_by FK, created_at, accepted_at nullable)`

Flows:
- On first login with no household: onboarding page → create household (just a name, e.g. "The Lewis household")
- Invite by email from a household settings page; invitee with no account registers then lands in the household; invitee with an account joins on accepting
- Leaving a household: membership deleted, household and its data persist; last member leaving prompts household deletion confirmation
- Account deletion (from T2) now also handles membership: data stays with the household unless it's the last member

**Acceptance**
- [ ] Two users (e.g. David and Henrietta) can share one household via email invite
- [ ] A user cannot belong to two households
- [ ] Invitation tokens are single-use and expire (7 days)
- [ ] Last-member deletion cascades the household and all its entries

## T4 — Hard-coded Home Energy slice: periodic entry

The first slice, hard-coded in Python (no catalogue yet), exercising the periodic entry mode.

Model (designed to survive Phase 2 unchanged):
- `PeriodicEntry(household FK, slice_key CharField, period_start DateField, cadence CharField[monthly|quarterly|annual], inputs JSONB, pinned_factors JSONB, result_kg Decimal, formula_version CharField, logged_by FK, created_at, updated_at)`
- Unique together: (household, slice_key, period_start)

Hard-coded slice definition (a plain Python structure in `entries/slices.py`):
- Items: natural gas (kWh), grid electricity import (kWh), heating oil (litres), LPG (litres), solar export credit (kWh, negative contribution)
- Factors as constants with source strings (values from the spreadsheet: gas 0.18286, electricity 0.20707, oil 2.5202, LPG 1.5534)

UX (HTMX):
- Household chooses cadence for the slice (stored as a household preference; default monthly)
- Entry form for a period; list of past periods with edit; HTMX partial swap on save showing the computed kg CO₂e immediately

**Acceptance**
- [ ] Entering 1000 kWh gas for a month stores result_kg = 182.86 with pinned_factors recording the factor used
- [ ] Solar export entry produces a negative result_kg
- [ ] Editing a past entry recomputes from its pinned factors, not from constants (prove by changing a constant in code and editing an old entry — result must not change)
- [ ] Duplicate period for same slice rejected with a friendly message

## T5 — Engine seed: calculate & pin

A tiny `engine` service that T4 calls — the seam where Phase 2's formula engine slots in.

- `engine.calculate(slice_def, inputs) -> CalculationResult(result_kg, pinned_factors, formula_version)`
- Pure function, no DB access; entries app persists the result
- Input validation against the slice's declared fields (types, non-negative where appropriate; export kWh is positive input, negativity comes from the calculation)
- `formula_version` is a hash of the slice definition, so Phase 2 recalculation can detect staleness

**Acceptance**
- [ ] Unit tested independently of views: given inputs, returns expected kg and a complete pinned_factors dict
- [ ] Rejects unknown input keys and wrong types with structured errors the form layer can render
- [ ] T4 contains no calculation arithmetic — only calls to the engine

## T6 — Dashboard v0

First sight of value. One number, one chart.

- Annualised current footprint: monthly ×12 / quarterly ×4 / annual as-is, from the most recent complete period per item (annualisation logic lives in `engine`, unit tested — this function outlives Phase 1)
- Chart.js line chart of monthly household total over time, fed by a JSON endpoint
- Honest gaps: missing periods render as gaps, never interpolated
- Placeholder benchmark strip: UK average couple scaled by member count (hard-coded values from the spreadsheet's summary; proper benchmark model arrives Phase 3)

**Acceptance**
- [ ] Dashboard reflects a new entry immediately after save
- [ ] A household with 3 members sees benchmarks scaled ×3
- [ ] A skipped month shows as a gap in the chart

## T7 — Base UI & responsive layout

Runs alongside everything; budget it explicitly so it doesn't get squeezed.

- Base template: nav (dashboard / enter data / household / account), flash messages, mobile-first layout
- A small design pass: this is a public product, it should feel like one. Green-led palette consistent with the spreadsheet's identity is a fine start
- Form components styled once, reused (Django form rendering + a CSS framework of your choice — suggest plain CSS or Pico/Tailwind-lite; decision is yours)

**Acceptance**
- [ ] All Phase 1 flows usable one-handed on a phone
- [ ] No layout breakage at 360px width

## T8 — Tests & CI

- pytest + pytest-django; factory_boy for models
- GitHub Actions: lint + tests on PR, Postgres service container
- Coverage gate is informational, not blocking (avoid ritual coverage chasing)

**Acceptance**
- [ ] Engine functions (T5, T6 annualisation) at near-100% branch coverage — these are the correctness core
- [ ] One end-to-end test: register → create household → enter gas reading → dashboard shows correct annualised figure

---

## Out of scope for Phase 1 (resist the temptation)

- Anything catalogue/admin-defined — Phase 2
- Flights / event entries — Phase 2 (proves event mode there)
- Food, Purchases slices — Phase 3
- Recalculation opt-in — Phase 3
- Onboarding wizard with defaults — Phase 4

## Definition of done for the phase

A fresh user can register at the deployed site, form a household with a second user, enter three months of real meter readings including solar export, and see a correct annualised footprint with a trend chart — and the stored entries carry pinned factors that survive any code change.
