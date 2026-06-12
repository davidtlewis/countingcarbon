# CountingCarbon — Phase 2–4 Tickets

**Reference docs:** `carbon_tracker_spec.md` • `phase1_tickets.md` • `fixtures/catalogue_seed.json`

These phases assume Phase 1's walking skeleton is live: auth, households, hard-coded Home Energy slice with periodic entries, engine seam (T5), dashboard v0.

---

# Phase 2 — Catalogue & Formula Engine

**Goal:** replace Phase 1's hard-coded slice with the data-driven catalogue, prove the formula DSL on the hardest real case (flights), and seed the full factor catalogue. **Phase acceptance: given the same inputs, CountingCarbon reproduces the spreadsheet's results exactly** — the 46 test cases in `catalogue_seed.json` are the executable form of that promise.

Suggested order: T9 → T10 → T11 → T12 → T13 → T14 → T15.

## T9 — Catalogue models

The data-driven definitions, per spec §8.2.

- `Slice(key, name, icon, description, entry_mode[periodic|event|annual_estimate], display_order, active)`
- `LineItem(slice FK, key, label, help_text, group nullable, display_order, active)`
- `InputField(line_item FK, name, label, type[decimal|integer|boolean|choice|text], unit, min nullable, choices JSONB nullable, display_order)`
- `Formula(line_item FK, expression Text, version Integer, test_cases JSONB, published_at nullable)` — new versions append, never overwrite; the latest published version is live
- `FactorSet(name, source, licence, valid_from, valid_to nullable, region default 'GB')`
- `Factor(factor_set FK, key, value Decimal, unit, citation)` — unique (factor_set, key)
- `BandTable(name)` / `Band(band_table FK, lower_bound, value)` — for `LOOKUP()`

**Acceptance**
- [ ] Migrations clean from zero; admin list/detail registered for every model (customisation comes in T13)
- [ ] Factor resolution helper: `resolve_factors(keys, as_of_date, region)` returns the factor values from the set valid on that date; ambiguity (overlapping sets) raises loudly
- [ ] Unique constraints enforced: slice keys, item keys within slice, factor keys within set

## T10 — Formula DSL & evaluator

The correctness core of the whole product. Per spec §8.3.

- Grammar: numbers, identifiers, `+ - * /`, unary minus, parentheses, comparisons (`= != < <= > >=`), `IF(cond, a, b)`, `MIN`, `MAX`, `ROUND(x, places)`, `LOOKUP(table_name, value)`, `factor("key")`
- Parse to AST at save time (recommend a small hand-rolled parser or `lark`; if wrapping `simpleeval`, constrain it hard — no attribute access, no names beyond the context, no comprehensions)
- Hard limits enforced: expression length (e.g. 1,000 chars), AST depth (e.g. 20), evaluation step budget; division by zero and missing identifiers produce structured errors, never exceptions to the user
- Static validation at save: every identifier must be a declared InputField of the item; every `factor()` key must exist in at least one factor set; every `LOOKUP` table must exist
- Boolean inputs coerce to 0/1 in arithmetic (the flights formula depends on `(1 + is_return)`)

**Acceptance**
- [ ] All 46 test cases from `catalogue_seed.json` pass through the real evaluator
- [ ] Property/fuzz tests: random malformed expressions never crash the process; injection attempts (`__class__`, `import`, attribute chains) are rejected at parse
- [ ] Evaluator is pure and deterministic: same AST + context → same Decimal result (use Decimal, not float, end to end; test the flights example to 2 dp)
- [ ] A formula cannot be published unless all its test cases pass

## T11 — Engine v2: factor pinning & versioned calculation

Upgrade Phase 1's engine seam to the real thing.

- `engine.calculate(line_item, inputs, as_of_date)` → resolves factors valid on `as_of_date`, evaluates the published formula, returns `(result_kg, pinned_factors, formula_version)`
- `pinned_factors` records key → value *and* the factor set name, so provenance is auditable
- Recalculation service: `recalculate(entry, to_date=today)` recomputes with current factors/formula, returns a before/after diff without saving; explicit `apply()` commits — UI for this lands in Phase 3 (T20)
- Migrate Phase 1's hard-coded Home Energy into catalogue records via data migration; existing entries keep their pinned values untouched

**Acceptance**
- [ ] Entry created in a period covered by FactorSet A pins A's values even if FactorSet B (later valid_from) exists
- [ ] After the data migration, editing a pre-migration entry recomputes identically (pinned factors, not catalogue)
- [ ] Loading a hypothetical "DESNZ 2027" fixture changes no existing entry's result_kg

## T12 — Dynamic entry forms

Forms generated from catalogue definitions instead of hard-coded.

- Form builder: InputFields → Django form fields (decimal/integer with min, boolean checkbox, choice select, text) with unit suffixes and help text
- Periodic flow generalised to any periodic slice; cadence preference per household per slice
- **Event mode (new):** `EventEntry(household, slice_key, event_date, inputs JSONB, pinned_factors, result_kg, formula_version, logged_by, timestamps)`; list view per slice ordered by date; add/edit/delete with HTMX partials
- Flights slice live end to end: the LHR→ATH example from the spreadsheet enterable and matching 2,453 kg

**Acceptance**
- [ ] Adding an InputField to a line item in admin changes the rendered form with no deploy
- [ ] Event entries pin factors by event_date (a 2025 flight uses 2025-valid factors)
- [ ] Server-side validation mirrors field constraints; invalid input re-renders the partial with errors, never a full-page error

## T13 — Catalogue admin experience

Django admin customised so slices can genuinely be managed without code (spec goal #3).

- Inlines: LineItems on Slice; InputFields and Formulas on LineItem; Factors on FactorSet
- Formula editing UX: monospace textarea, live "validate & run test cases" button (HTMX or admin action), publish action gated on green tests
- Factor set import: upload JSON in the seed-file format → staged preview → commit
- Read-only audit: which entries used which formula version (count + sample)

**Acceptance**
- [ ] An admin can create a new slice with one item, a formula and test cases, publish it, and see it appear in user data entry — demonstrated without touching code (the architecture's acid test, do it for real)
- [ ] Publishing a formula with a failing test case is impossible through the UI
- [ ] Factor import is idempotent: re-importing the same file changes nothing

## T14 — Seed factor catalogue from spreadsheet v2

The data task specced in spec §11.

- Management command `load_catalogue <path>` consuming `fixtures/catalogue_seed.json`: factor sets, slices, items, fields, formulas (published iff tests pass), band tables, benchmarks
- Idempotent: keyed upserts, never duplicates; `--dry-run` prints the diff
- DESNZ OGL attribution string stored and rendered wherever factors are displayed

**Acceptance**
- [ ] Fresh database + `load_catalogue` → all five slices live, all 46 formula tests green
- [ ] Running twice produces zero changes on the second run
- [ ] Every factor displays its citation in admin

## T15 — Phase 2 regression: spreadsheet parity

A single high-value test suite asserting the product equals the reference implementation.

- Fixture of the spreadsheet's worked inputs (12,000 kWh gas; 2,000 import / 5,000 export; 10,000 petrol km; LHR→ATH ×2 pax return; medium-meat ×2; etc.)
- Asserts each computed result and the household total to 2 dp against the spreadsheet's outputs

**Acceptance**
- [ ] Suite green; wired into CI; any factor or formula drift fails the build

---

# Phase 3 — Full Catalogue & Dashboard

**Goal:** all entry modes live, the dashboard becomes genuinely motivating, recalculation reaches users.

Suggested order: T16 → T17 → T18 → T19 → T20.

## T16 — Annual-estimate entry mode

The third and final mode (Food, Purchases).

- `AnnualEstimate(household, slice_key, line_item_key, effective_from DateField, inputs JSONB, pinned_factors, result_kg, formula_version, logged_by, timestamps)` — changing a value creates a new record with a new effective_from; history preserved
- Food UX: quick-estimate group rendered as a single "diet type + number of people" chooser (the five quick items are mutually exclusive — enforce in the form, not the user's discipline); detailed group behind a disclosure, mutually exclusive with quick at the slice level
- Purchases: straightforward annual estimate form across its items

**Acceptance**
- [ ] Setting medium-meat ×2 then switching to low-meat ×2 in March yields two records; the dashboard uses the latest effective values; history shows both
- [ ] Quick and detailed food entries cannot both be active (clear inline explanation when blocked)
- [ ] Estimates pin factors by effective_from date

## T17 — Dashboard v1: trends & composition

- Annualisation service finalised across all three modes: periodic (latest complete cadence × multiplier), events (trailing 12 months summed), estimates (current effective values) — one unit-tested function per spec §8.2
- Chart.js: household total over time (line), slice composition (stacked bar or doughnut), per-slice drill-down trend
- Gaps rendered honestly (null points, not interpolation); partial periods labelled

**Acceptance**
- [ ] A household with monthly energy, two logged flights and a diet estimate sees one coherent annualised total decomposed by slice
- [ ] Deleting a flight updates trailing-12-month figures immediately
- [ ] Charts usable at 360 px width

## T18 — Benchmarks & comparison strip

- `Benchmark` model seeded from `catalogue_seed.json` (UK average, CCC 2030, 1.5 °C fair share, global average), each scaled by household member count
- Dashboard strip: your total vs each benchmark, with sources on tap
- Per-slice context lines (e.g. "average UK home energy: ~2,200 kg") as admin-editable benchmark rows tagged to slices

**Acceptance**
- [ ] Member count change rescales benchmarks instantly
- [ ] Every benchmark shows its source citation

## T19 — Transparency: "How is this calculated?"

The trust feature (spec P0 non-functional: traceability).

- Every displayed result links to a breakdown: inputs entered, factor values used (with set name + citation), formula (rendered readably), arithmetic result
- Catalogue browse page: public read-only view of slices, items, factors and sources — the anti-black-box statement

**Acceptance**
- [ ] A user can trace any number on their dashboard to inputs + cited factors in ≤ 2 taps
- [ ] DESNZ OGL attribution appears on the catalogue page

## T20 — Recalculation opt-in

The "pinned, but allow opt-in recalculation" decision, surfaced.

- Household settings: "Update past periods to current factors" → period selector → before/after diff table (per entry and total delta) → confirm applies, audit-logged
- Partial selection supported (e.g. recalc 2026 but not 2025)

**Acceptance**
- [ ] Diff preview matches applied results exactly; cancel changes nothing
- [ ] Audit record stores who, when, which entries, old/new values
- [ ] Recalculated entries pin the *new* factors (re-pinning, not un-pinning)

---

# Phase 4 — Polish for Public Launch

**Goal:** a stranger can arrive, get value in ten minutes, trust the product with their data, and come back next month.

Suggested order: T21 → T22 → T23 → T24 → T25 → T26.

## T21 — Onboarding wizard with quick-estimate defaults

Spec goal #1: meaningful first footprint inside 10 minutes.

- ~10-question flow after household creation: home size/heating proxy → energy defaults; car type + rough mileage; flights last year (count, short/long); diet type + people; consumption level (low/typical/high)
- Answers create real entries flagged `is_estimate=true`, visually distinct, individually replaceable with real data later
- Skippable entirely; resumable

**Acceptance**
- [ ] Completing the wizard lands on a populated dashboard with a sensible UK-typical total
- [ ] Replacing an estimated entry with real data clears its estimate flag; dashboard distinguishes estimated vs entered proportions
- [ ] Median completion < 10 min (instrument it)

## T22 — GDPR & account lifecycle

- Data export: full household JSON (entries, pinned factors, audit) self-serve
- Deletion flows hardened: account vs household, grace messaging, hard delete verified to leave no orphan rows
- Privacy policy and ToS pages (real text); cookie stance documented (aim: essential-only, no banner needed)

**Acceptance**
- [ ] Export round-trip: exported JSON re-loadable in dev to an equivalent household
- [ ] Post-deletion DB sweep finds zero rows referencing the deleted user/household
- [ ] No third-party trackers; essential cookies only

## T23 — Entry reminders

- Per-household opt-in email reminder aligned to each periodic slice's cadence ("time for your March readings"), with one-click snooze/disable
- Scheduling via cron-style management command or lightweight scheduler (avoid Celery unless something else needs it)

**Acceptance**
- [ ] Reminder sends only when the period lacks an entry; never for completed periods
- [ ] Unsubscribe link works without login

## T24 — Public front door

- Landing page: what it is, an example dashboard (static or demo data), transparency pitch (cited factors), sign-up CTA
- SEO basics, OpenGraph, favicon; legal links in footer

**Acceptance**
- [ ] Lighthouse: performance and accessibility ≥ 90 on the landing page
- [ ] A visitor understands the product without signing up

## T25 — Production hardening

- Error tracking (e.g. Sentry free tier), uptime check, daily Postgres backups with a tested restore
- Security pass: HSTS, CSP, rate-limiting auth endpoints, dependency audit in CI
- Email deliverability for countingcarbon.dtlewis.com (SPF/DKIM) via a transactional provider

**Acceptance**
- [ ] A staged restore from last night's backup boots and serves
- [ ] Verification + reminder emails land in Gmail/Outlook inboxes, not spam

## T26 — Launch checklist & soft launch

- Seed production via T14's command; create admin account; smoke-test the full journey on production
- Soft launch to friends/family (you and Henrietta as household #1 — eat the dog food with the real 2026 data from the spreadsheet)
- Feedback capture: a simple in-app feedback link is enough

**Acceptance**
- [ ] Five real households through onboarding without developer hand-holding
- [ ] Your spreadsheet's annual figures and CountingCarbon's dashboard agree for the same data — the final parity check, in production

---

## Parking lot (P2 — explicitly not ticketed)

Octopus Energy API import • social groups & percentiles • multi-region factor catalogues • multiple households per user • "what-if" sliders • CSV spreadsheet import. Each gets specced only when it's next.
