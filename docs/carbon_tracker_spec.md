# CountingCarbon — Scope, Requirements & Outline Design

**Product:** CountingCarbon  •  **Domain:** countingcarbon.dtlewis.com

**Version:** 0.2
**Date:** June 2026
**Status:** Decisions captured from scoping interview; open questions flagged at end

---

## 1. Problem Statement

People who want to understand and reduce their carbon footprint have no good way to track it over time. Existing calculators (WWF, carbonfootprint.com) are one-shot quizzes with opaque assumptions; spreadsheets (the precursor to this project) work but don't scale beyond one motivated household, can't track trends, and require manual factor maintenance. Without ongoing tracking, people can't see whether their changes — solar panels, diet shifts, fewer flights — are actually working.

## 2. Vision

A public web application where households track their carbon footprint over time through periodic data entry, see clear trends and benchmarks, and benefit from up-to-date, transparent emission factors — with a data-driven architecture that lets administrators add new carbon categories and update factors without code changes.

## 3. Decisions Made (from scoping interview)

| Decision | Choice | Implication |
|---|---|---|
| Audience | Public product, anyone can sign up | Real auth, onboarding UX, data protection (UK GDPR) |
| Tracking model | Ongoing time-series, not snapshot | Period-based data model; trends are a core feature |
| Stack | Django + HTMX | Server-rendered, minimal JS, consistent with PRM platform |
| Pluggability | Data-driven: slices, items and formulas defined in DB by admins | Constrained formula DSL needed; no code deploy for new categories |
| Account model | Household — members share one footprint | Household entity owns data; users are members |
| Data entry | Manual forms only (v1) | No API integrations; keeps scope tight |
| Entry modes | Three: periodic readings / event log / annual estimate | Each slice configured with a mode |
| Period granularity | User chooses per periodic slice (monthly / quarterly / annual) | All data normalised to annual for display |
| Factor updates | Pinned to entry date; opt-in recalculation | Factors are versioned with validity dates |
| Custom definitions | Admins only; users consume what's defined | Single shared catalogue; simpler permissions |
| Social features | Solo for v1; design so social can come later | Benchmarks yes; user comparison no |
| Attribution | Fully pooled — no per-member attribution | All entries belong to the household; any member can log anything; carbon is shared equally |

## 4. Goals

1. A new user can sign up, create a household, and see a meaningful first footprint estimate within **10 minutes** using quick-estimate defaults.
2. A returning user can complete a monthly data entry session in **under 5 minutes**.
3. An administrator can add a new carbon slice (e.g. "Pets" or "Water use") — including line items, factors and formulas — entirely through the admin UI, **with zero code deployment**.
4. Annual DESNZ factor updates can be loaded without disturbing historical calculations.
5. Users can see their trend over time and how they compare to UK and global benchmarks.

## 5. Non-Goals (v1)

- **API integrations** (Octopus, smart meters, Home Assistant) — manual entry only. *Why:* scope control; the data model should not preclude them later.
- **Social comparison / leaderboards / groups** — solo experience only. *Why:* community features are a product in themselves; benchmarks give 80% of the motivational value.
- **User-defined slices or line items** — admin-curated catalogue only. *Why:* avoids moderation, data-quality and support burden.
- **Carbon offset purchasing or recommendations engine** — informational tips only. *Why:* commercial/regulatory complexity; potential greenwashing risk.
- **Native mobile apps** — responsive web only. *Why:* HTMX serves mobile web well; apps are a later distribution decision.
- **Non-UK localisation** — UK factors and benchmarks only. *Why:* factor curation per country is significant ongoing work; architecture should keep factors region-taggable for the future.

## 6. User Stories

### Visitor / new user
- As a visitor, I want to understand what the site does and see an example footprint before signing up, so that I can judge whether it's worth my time.
- As a new user, I want to create an account with email + password and set up my household in one flow, so that I'm not bounced between settings pages.
- As a new user, I want sensible UK-average defaults pre-filled, so that I get an immediate rough footprint I can then refine.

### Household member (regular use)
- As a household member, I want to invite my partner to our household, so that we maintain one shared footprint together.
- As a household member, I want to enter my electricity and gas readings monthly, so that our footprint reflects actual usage.
- As a household member, I want to log each flight as an event (route, passengers, distance, class), so that flights are itemised rather than lumped.
- As a household member, I want to set our diet type once as an annual estimate, so that I don't re-enter unchanging things every month.
- As a household member, I want to record solar export so that our footprint reflects the credit for clean energy we feed to the grid.
- As a household member, I want to see our footprint trend over months and years, so that I know whether our changes are working.
- As a household member, I want to see how we compare to UK average, CCC 2030 target and 1.5 °C fair-share benchmarks (scaled to our household size), so that I have context for the numbers.
- As a household member, I want to see which slices contribute most to our total, so that I know where to focus.

### Administrator
- As an admin, I want to create a new slice with line items, units, factors and an entry mode through the admin UI, so that the catalogue grows without code.
- As an admin, I want to define a calculation formula per line item using a spreadsheet-like expression language, so that non-linear cases (e.g. flight class/distance bands) are expressible.
- As an admin, I want to test a formula against sample inputs before publishing, so that broken formulas never reach users.
- As an admin, I want to load a new factor set (e.g. DESNZ 2027) with a validity start date, so that new entries use new factors while history stays pinned.
- As an admin, I want to trigger an optional recalculation of a household's history at their request, so that users who want consistency can opt in.

### Edge cases
- As a user who skips three months, I want gaps shown honestly (not interpolated silently), so that my data remains trustworthy.
- As a user who made a typo (entered 120,000 kWh), I want to edit past entries, with the calculation re-run using the factors pinned to that period.
- As a user leaving a household, I want my account to detach without destroying the household's shared history.

## 7. Requirements

### Must-Have (P0)

**Accounts & households**
- Email/password registration with verification; password reset. *(Django allauth or built-in auth.)*
- Household creation at onboarding; invite by email; members have equal rights (no roles in v1).
- A user belongs to exactly one household in v1.
- ✓ Given a user accepts an invite, when they log in, then they see the shared household dashboard.

**Catalogue (admin-defined)**
- Admin can CRUD **Slices**: name, icon, description, display order, entry mode (periodic / event / annual estimate), active flag.
- Admin can CRUD **Line Items** within a slice: label, help text, input fields (name, type, unit), formula, display order.
- Admin can CRUD **Factor Sets**: a named, dated collection of factor values (e.g. "DESNZ 2026"), each factor with a key, value, source citation and validity date range.
- ✓ Given an admin publishes a new slice, when a user opens data entry, then the slice appears with no deployment.

**Formula engine**
- Spreadsheet-like expression DSL: arithmetic, comparison, `IF()`, `MIN()`, `MAX()`, `ROUND()`, `LOOKUP(table, value)` against admin-defined band tables, references to the item's declared input fields and to named factors (e.g. `factor("elec_grid")`).
- Sandboxed evaluation (no attribute access, no imports, no loops); execution time and recursion bounded.
- Formula validation at save time: syntax check + admin-supplied test cases (inputs → expected output) must pass before publish.
- ✓ Given a formula referencing an undefined variable, when the admin saves, then a clear error names the missing variable and the formula is not published.

**Data entry**
- *Periodic slices:* user selects cadence (monthly/quarterly/annual) per slice; entry form per period; editable history.
- *Event slices:* dated log entries (e.g. flights) with the slice's declared fields; add/edit/delete.
- *Annual-estimate slices:* persistent values with effective-from dates; changing creates a new effective record rather than overwriting.
- Negative-contribution items supported (solar export credit).
- ✓ Given a periodic entry is edited, when saved, then its emissions recalculate using the factor set valid for that period (not today's).

**Calculation & pinning**
- Every entry stores: inputs (JSON), resolved factor values used, formula version, computed kg CO₂e. The stored result is authoritative; recalculation is explicit, never implicit.
- Opt-in recalculation: a household can request recalculation of selected periods to current factors; before/after diff shown.
- ✓ Given DESNZ 2027 factors are loaded, when a user views January 2026, then January 2026 figures are unchanged.

**Dashboard**
- Current annualised footprint (total + per slice), normalising mixed cadences to annual.
- Trend chart over time; slice breakdown chart.
- Benchmarks scaled by household member count (UK average, CCC 2030 pathway, 1.5 °C fair share, global average) with sources.
- Honest gap display for missing periods.

**Non-functional**
- UK GDPR: privacy policy, data export (JSON), account + household deletion.
- Responsive (mobile-first data entry).
- All factor values traceable to a cited source, displayed to users on request ("How is this calculated?").

### Nice-to-Have (P1)
- Quick-estimate onboarding wizard producing a first footprint from ~10 questions.
- Email reminders for periodic entry (user-configurable).
- Per-slice "what if" sliders (e.g. "what if we halved our flights?").
- CSV import of the existing spreadsheet format.
- Admin analytics: factor usage, active households, entry completion rates.

### Future Considerations (P2 — design for, don't build)
- API integrations (Octopus Energy first — aligns with battery/solar users).
- Social: groups, shared challenges, anonymised community percentiles. *(Design hook: keep all aggregates computable per household so percentiles are cheap later.)*
- Multi-region factor catalogues. *(Design hook: factors carry a region tag, defaulting to GB.)*
- Multiple households per user (e.g. second home).

## 8. Outline Design

### 8.1 Stack

- **Django 5.x**, server-rendered templates + **HTMX** for partial updates (entry forms, charts panel refresh). Minimal vanilla JS; charts via **Chart.js** fed by lightweight JSON endpoints (decided — see §10 Q4).
- **PostgreSQL** (JSONB for entry inputs and formula ASTs).
- **simpleeval** (or equivalent) wrapped in a hardened evaluator for the formula DSL.
- **uv** for dependency management; deploy on Railway with Gunicorn (consistent with existing practice).
- Django admin heavily customised for catalogue management (slices, items, factor sets, formula testing) — this *is* the admin UI for v1; a bespoke admin frontend is not needed.

### 8.2 Data model (core entities)

```
User ──< HouseholdMembership >── Household
                                     │
                                     ├──< PeriodicEntry   (slice, period_start, cadence, inputs JSON,
                                     │                     pinned_factors JSON, result_kg, formula_version)
                                     ├──< EventEntry      (slice, event_date, inputs JSON,
                                     │                     pinned_factors JSON, result_kg, formula_version)
                                     └──< AnnualEstimate  (slice, effective_from, inputs JSON,
                                                           pinned_factors JSON, result_kg, formula_version)

Slice ──< LineItem ──< InputField (name, label, type, unit)
              │
              └── Formula (expression text, version, test cases)

FactorSet (name, source, valid_from, valid_to, region='GB')
    └──< Factor (key, value, unit, citation)

BandTable (name) ──< Band (lower_bound, value)        # for LOOKUP()
```

Key design points:
- **Pinning is data, not logic.** Each entry snapshots the exact factor values and formula version used. Historical correctness survives any catalogue change, including item deletion.
- **Entry tables per mode** keeps queries simple and constraints honest (a periodic entry has a period; an event has a date) rather than one polymorphic table.
- **Inputs as JSONB** validated against the slice's declared InputFields at save time — the same pattern as the PRM's JSON custom fields.
- **Annualisation** is a read-time concern: monthly ×12 from latest complete data, quarterly ×4, events summed over trailing 12 months, estimates taken as-is. One service function owns this logic.

### 8.3 Formula DSL sketch

```
# Simple linear (most items)
quantity * factor("gas_kwh")

# Flights (conditional banding)
passengers * distance_km * (1 + is_return) *
  IF(distance_km <= 3700,
     factor("flight_short_economy"),
     IF(class = 2, factor("flight_long_business"), factor("flight_long_economy")))

# Banded via lookup table
spend_gbp * LOOKUP("retail_intensity_bands", spend_gbp)
```

Grammar: numbers, identifiers (input fields), `+ - * / ( )`, comparisons, `IF/MIN/MAX/ROUND/LOOKUP/factor()`. Nothing else. Evaluated against a context dict of validated inputs + resolved factors. Hard limits: expression length, AST depth, evaluation timeout.

### 8.4 Application structure (Django apps)

- `accounts` — auth, household membership, invitations
- `catalogue` — slices, line items, formulas, factor sets, band tables; admin customisation; formula validator/test-runner
- `entries` — the three entry models, entry forms (HTMX partials), edit history
- `engine` — formula evaluator, factor resolution, pinning, annualisation, recalculation service
- `dashboard` — aggregate queries, trend/benchmark views, "how is this calculated?" transparency views

### 8.5 Suggested phasing

1. **Phase 1 — Walking skeleton:** auth + household, hard-coded "Home Energy" slice, periodic entry, total on dashboard. Proves the entry→calculate→pin→display loop end to end.
2. **Phase 2 — Catalogue & engine:** data-driven slices, formula DSL + validation, factor sets with pinning. Migrate Home Energy into the catalogue; add Transport (with flight event log) to prove the event mode and conditional formulas.
3. **Phase 3 — Full catalogue & dashboard:** Food (annual-estimate mode), Purchases, trend charts, benchmarks, gaps, recalculation opt-in.
4. **Phase 4 — Polish for public:** onboarding wizard with defaults, GDPR export/delete, reminders, transparency views, deploy.

## 9. Success Metrics

*Leading (first month after public launch):*
- ≥ 60% of sign-ups complete onboarding to a first footprint (target 10-minute median).
- ≥ 40% of activated households make a second entry within 35 days.
- Zero formula-engine errors reaching users (validation catches 100% pre-publish).

*Lagging (quarter+):*
- 3-month household retention ≥ 25%.
- Admin adds at least one new slice post-launch without developer involvement (the architecture's acid test).

## 10. Open Questions

All scoping questions are now resolved:

| # | Question | Resolution |
|---|---|---|
| 1 | Product name and domain | **CountingCarbon** at countingcarbon.dtlewis.com |
| 2 | Business model | **Free.** No billing fields needed. Possible advertising/upsell later — nothing in v1 architecture depends on it |
| 3 | Per-member attribution vs pooled | **Fully pooled.** Entries belong to the household; `logged_by` audit field only |
| 4 | Charts | **Chart.js** — richer interaction; fed by lightweight JSON endpoints from Django views |
| 5 | Catalogue admin UI | **Django admin** for v1; bespoke frontend deferred until the catalogue workflow proves painful |
| 6 | Factor licensing & citations | Citation approach confirmed. DESNZ factors are OGL (attribution required); Poore & Nemecek cited to the Science paper. Initial factor catalogue to be assembled with Claude's help — see §11 |

---

## 11. Initial Factor Catalogue (seed data task)

The existing spreadsheet is the seed: its factors, sources and formulas map directly onto the catalogue model. A one-off task (with Claude assisting) will produce:

- A **DESNZ 2024 factor set** (valid_from 2024-06) covering gas, electricity, transport modes and flights — extracted from the official conversion-factor workbook with OGL attribution.
- A **food factor set** citing Poore & Nemecek (2018), *Science* 360(6392), and Berners-Lee (2020) for diet-type aggregates.
- A **consumption factor set** citing WRAP, DEFRA spend-based intensities, and Berners-Lee.
- Formula definitions for each line item, including the flights banding formula and the solar export credit (negative contribution).
- Fixture files (JSON) loadable via Django management command, so a fresh deployment seeds a complete working catalogue.

This becomes a Phase 2 ticket: "Seed factor catalogue from spreadsheet v2".

---

*Next steps: Phase 1 can be broken into implementation tickets. The spreadsheet remains the reference implementation for calculation correctness — Phase 2 acceptance should include reproducing the spreadsheet's results exactly from the same inputs.*
