from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from catalogue.models import Slice
from engine.calculate import ValidationError, recalculate
from engine.catalogue_calculate import (
    CatalogueValidationError,
    catalogue_calculate,
    catalogue_recalculate,
)

from .models import AnnualEstimate, EventEntry, HouseholdSlicePreference, PeriodicEntry
from .slices import HOME_ENERGY_SLICE

# ── URL name sets for generic periodic partials ───────────────────────────────

_HOME_ENERGY_URLS = {
    "url_add": "entries:add_entry",
    "url_row": "entries:entry_row",
    "url_edit_form": "entries:edit_entry_form",
    "url_edit": "entries:edit_entry",
}

_TRANSPORT_URLS = {
    "url_add": "entries:transport_add",
    "url_row": "entries:transport_row",
    "url_edit_form": "entries:transport_edit_form",
    "url_edit": "entries:transport_edit",
}

# ── Shared helpers ────────────────────────────────────────────────────────────


def _get_household(request):
    return request.user.membership.household


def _get_or_create_preference(household, slice_key):
    pref, _ = HouseholdSlicePreference.objects.get_or_create(
        household=household,
        slice_key=slice_key,
        defaults={"cadence": "monthly"},
    )
    return pref


def _parse_period_start(cadence: str, post: dict) -> date | None:
    try:
        if cadence == "monthly":
            year, month = post.get("period_month", "").split("-")
            return date(int(year), int(month), 1)
        if cadence == "quarterly":
            quarter_to_month = {"1": 1, "2": 4, "3": 7, "4": 10}
            month = quarter_to_month.get(post.get("period_quarter", ""), None)
            if month is None:
                return None
            return date(int(post["period_year"]), month, 1)
        return date(int(post["period_year"]), 1, 1)
    except (ValueError, KeyError, TypeError):
        return None


def _extract_catalogue_inputs(post: dict, line_items) -> dict:
    inputs = {}
    for li in line_items:
        item_inputs = {}
        for field in li.input_fields.all():
            key = f"{li.key}__{field.name}"
            val = post.get(key, "").strip()
            if field.field_type == "boolean":
                item_inputs[field.name] = "1" if key in post else "0"
            else:
                item_inputs[field.name] = val if val else None
        inputs[li.key] = item_inputs
    return inputs


def _is_phase2_entry(entry: PeriodicEntry) -> bool:
    if not entry.inputs:
        return False
    first_val = next(iter(entry.inputs.values()), None)
    return isinstance(first_val, dict)


def _get_cadence_choices():
    return HouseholdSlicePreference._meta.get_field("cadence").choices


def _delete_overlapping_estimates(household, slice_key, period_start, cadence):
    """Delete is_estimate entries whose period overlaps the new entry's period.

    Returns the number of estimates deleted.
    """
    if cadence == "monthly":
        y, m = period_start.year, period_start.month
        period_end = date(y + (m // 12), m % 12 + 1, 1)
    elif cadence == "quarterly":
        m = period_start.month + 3
        period_end = date(period_start.year + (m > 12), (m - 1) % 12 + 1, 1)
    else:
        period_end = date(period_start.year + 1, 1, 1)

    candidates = PeriodicEntry.objects.filter(
        household=household, slice_key=slice_key, is_estimate=True
    )
    to_delete = [
        est.id
        for est in candidates
        if est.period_start < period_end and est.period_end > period_start
    ]
    if not to_delete:
        return 0
    return PeriodicEntry.objects.filter(id__in=to_delete).delete()[0]


# ── Generic periodic slice page ───────────────────────────────────────────────


def _periodic_page_context(household, slice_key, urls):
    preference = _get_or_create_preference(household, slice_key)
    entries = PeriodicEntry.objects.filter(household=household, slice_key=slice_key)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key=slice_key
    )
    return {
        "slice": slice_obj,
        "entries": entries,
        "preference": preference,
        "cadence_choices": _get_cadence_choices(),
        "form_period_start": date.today(),
        **urls,
    }


# ── Home Energy (periodic, catalogue-backed) ──────────────────────────────────


@login_required
def home_energy(request):
    household = _get_household(request)
    ctx = _periodic_page_context(household, "home_energy", _HOME_ENERGY_URLS)
    return render(request, "entries/home_energy.html", ctx)


@login_required
def update_cadence(request):
    return _update_cadence(request, "home_energy", "entries:home_energy")


def _update_cadence(request, slice_key, redirect_name):
    if request.method != "POST":
        return redirect(redirect_name)
    household = _get_household(request)
    new_cadence = request.POST.get("cadence", "monthly")
    valid = {c[0] for c in _get_cadence_choices()}
    if new_cadence in valid:
        HouseholdSlicePreference.objects.update_or_create(
            household=household,
            slice_key=slice_key,
            defaults={"cadence": new_cadence},
        )
    return redirect(redirect_name)


@login_required
def add_entry(request):
    return _periodic_add(request, "home_energy", _HOME_ENERGY_URLS)


@login_required
def entry_row(request, entry_id):
    return _periodic_row(request, entry_id, "home_energy", _HOME_ENERGY_URLS)


@login_required
def edit_entry_form(request, entry_id):
    return _periodic_edit_form(request, entry_id, "home_energy", _HOME_ENERGY_URLS)


@login_required
def edit_entry(request, entry_id):
    return _periodic_edit(
        request, entry_id, "home_energy", "entries:home_energy", _HOME_ENERGY_URLS
    )


# ── Generic periodic add/edit handlers ────────────────────────────────────────


def _periodic_add(request, slice_key, urls):
    household = _get_household(request)
    preference = _get_or_create_preference(household, slice_key)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key=slice_key
    )
    line_items = list(
        slice_obj.line_items.filter(active=True).order_by("display_order", "key")
    )
    cadence = preference.cadence
    errors = {}
    inputs = {}
    period_start = None

    if request.method == "POST":
        inputs = _extract_catalogue_inputs(request.POST, line_items)
        period_start = _parse_period_start(cadence, request.POST)

        if period_start is None:
            errors["period"] = "Please select a valid period."
        else:
            try:
                result = catalogue_calculate(slice_obj, inputs, period_start)
                replaced = _delete_overlapping_estimates(
                    household, slice_key, period_start, cadence
                )
                entry = PeriodicEntry.objects.create(
                    household=household,
                    slice_key=slice_key,
                    period_start=period_start,
                    cadence=cadence,
                    inputs=inputs,
                    pinned_factors=result.pinned_factors,
                    result_kg=result.result_kg,
                    formula_version=result.formula_version,
                    logged_by=request.user,
                )
                all_entries = PeriodicEntry.objects.filter(
                    household=household, slice_key=slice_key
                )
                return render(
                    request,
                    "entries/partials/entries_section.html",
                    {
                        "slice": slice_obj,
                        "entries": all_entries,
                        "preference": preference,
                        "cadence_choices": _get_cadence_choices(),
                        "saved_entry": entry,
                        "replaced_estimates": replaced,
                        **urls,
                    },
                )
            except CatalogueValidationError as exc:
                errors.update(exc.errors)
            except Exception:
                errors["period"] = (
                    "An entry for this period already exists. "
                    "Use the edit button to update it."
                )

    all_entries = PeriodicEntry.objects.filter(household=household, slice_key=slice_key)
    return render(
        request,
        "entries/partials/entries_section.html",
        {
            "slice": slice_obj,
            "entries": all_entries,
            "preference": preference,
            "cadence_choices": _get_cadence_choices(),
            "form_errors": errors,
            "form_inputs": inputs,
            "form_period_start": period_start,
            **urls,
        },
    )


def _periodic_row(request, entry_id, slice_key, urls):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key=slice_key
    )
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key=slice_key
    )
    return render(
        request,
        "entries/partials/entry_row.html",
        {"slice": slice_obj, "entry": entry, **urls},
    )


def _periodic_edit_form(request, entry_id, slice_key, urls):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key=slice_key
    )
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key=slice_key
    )
    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": slice_obj, "entry": entry, **urls},
    )


def _periodic_edit(request, entry_id, slice_key, redirect_name, urls):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key=slice_key
    )

    if request.method != "POST":
        return redirect(redirect_name)

    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key=slice_key
    )
    errors = {}

    if _is_phase2_entry(entry):
        line_items = list(
            slice_obj.line_items.filter(active=True).order_by("display_order", "key")
        )
        new_inputs = _extract_catalogue_inputs(request.POST, line_items)
        try:
            from decimal import ROUND_HALF_UP, Decimal

            total = Decimal(0)
            for li in line_items:
                formula = li.published_formula()
                if formula is None:
                    continue
                item_inputs = new_inputs.get(li.key, {})
                result = catalogue_recalculate(
                    li, item_inputs, entry.pinned_factors, formula.expression
                )
                total += result
            new_result_kg = total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            entry.inputs = new_inputs
            entry.result_kg = new_result_kg
            entry.logged_by = request.user
            entry.save(update_fields=["inputs", "result_kg", "logged_by", "updated_at"])
            return render(
                request,
                "entries/partials/entry_row.html",
                {"slice": slice_obj, "entry": entry, "saved": True, **urls},
            )
        except CatalogueValidationError as exc:
            errors = exc.errors
    else:
        old_inputs = {
            item["key"]: request.POST.get(item["key"], "").strip() or None
            for item in HOME_ENERGY_SLICE["items"]
        }
        try:
            new_result_kg = recalculate(
                HOME_ENERGY_SLICE, old_inputs, entry.pinned_factors
            )
            entry.inputs = old_inputs
            entry.result_kg = new_result_kg
            entry.logged_by = request.user
            entry.save(update_fields=["inputs", "result_kg", "logged_by", "updated_at"])
            return render(
                request,
                "entries/partials/entry_row.html",
                {"slice": slice_obj, "entry": entry, "saved": True, **urls},
            )
        except ValidationError as exc:
            errors = exc.errors

    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": slice_obj, "entry": entry, "form_errors": errors, **urls},
    )


# ── Transport (periodic, catalogue-backed) ────────────────────────────────────


@login_required
def transport(request):
    household = _get_household(request)
    ctx = _periodic_page_context(household, "transport", _TRANSPORT_URLS)
    return render(request, "entries/transport.html", ctx)


@login_required
def transport_cadence(request):
    return _update_cadence(request, "transport", "entries:transport")


@login_required
def transport_add(request):
    return _periodic_add(request, "transport", _TRANSPORT_URLS)


@login_required
def transport_row(request, entry_id):
    return _periodic_row(request, entry_id, "transport", _TRANSPORT_URLS)


@login_required
def transport_edit_form(request, entry_id):
    return _periodic_edit_form(request, entry_id, "transport", _TRANSPORT_URLS)


@login_required
def transport_edit(request, entry_id):
    return _periodic_edit(
        request, entry_id, "transport", "entries:transport", _TRANSPORT_URLS
    )


# ── Flights (event mode) ──────────────────────────────────────────────────────


def _get_flights_slice():
    return Slice.objects.prefetch_related("line_items__input_fields").get(key="flights")


def _get_flight_line_item(slice_obj):
    return slice_obj.line_items.get(key="flight")


def _extract_flight_inputs(post: dict, input_fields) -> dict:
    inputs = {}
    for field in input_fields:
        key = field.name
        if field.field_type == "boolean":
            inputs[key] = "1" if key in post else "0"
        else:
            val = post.get(key, "").strip()
            inputs[key] = val if val else None
    return inputs


@login_required
def flights(request):
    household = _get_household(request)
    entries = EventEntry.objects.filter(household=household, slice_key="flights")
    slice_obj = _get_flights_slice()
    li = _get_flight_line_item(slice_obj)
    input_fields = list(li.input_fields.order_by("display_order"))
    return render(
        request,
        "entries/flights.html",
        {
            "slice": slice_obj,
            "line_item": li,
            "input_fields": input_fields,
            "entries": entries,
        },
    )


@login_required
def add_flight(request):
    household = _get_household(request)
    slice_obj = _get_flights_slice()
    li = _get_flight_line_item(slice_obj)
    input_fields = list(li.input_fields.order_by("display_order"))

    errors = {}
    form_inputs = {}
    event_date = None

    if request.method == "POST":
        form_inputs = _extract_flight_inputs(request.POST, input_fields)
        date_str = request.POST.get("event_date", "").strip()
        try:
            event_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            errors["event_date"] = "Please enter a valid date."

        if not errors:
            try:
                result = catalogue_calculate(
                    slice_obj, {"flight": form_inputs}, event_date
                )
                entry = EventEntry.objects.create(
                    household=household,
                    slice_key="flights",
                    event_date=event_date,
                    inputs=form_inputs,
                    pinned_factors=result.pinned_factors,
                    result_kg=result.result_kg,
                    formula_version=result.formula_version,
                    logged_by=request.user,
                )
                all_entries = EventEntry.objects.filter(
                    household=household, slice_key="flights"
                )
                return render(
                    request,
                    "entries/partials/flights_section.html",
                    {
                        "slice": slice_obj,
                        "line_item": li,
                        "input_fields": input_fields,
                        "entries": all_entries,
                        "saved_entry": entry,
                    },
                )
            except CatalogueValidationError as exc:
                errors.update(exc.errors)

    all_entries = EventEntry.objects.filter(household=household, slice_key="flights")
    return render(
        request,
        "entries/partials/flights_section.html",
        {
            "slice": slice_obj,
            "line_item": li,
            "input_fields": input_fields,
            "entries": all_entries,
            "form_errors": errors,
            "form_inputs": form_inputs,
            "form_event_date": event_date,
        },
    )


@login_required
def flight_row(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        EventEntry, id=entry_id, household=household, slice_key="flights"
    )
    slice_obj = _get_flights_slice()
    li = _get_flight_line_item(slice_obj)
    input_fields = list(li.input_fields.order_by("display_order"))
    return render(
        request,
        "entries/partials/flight_row.html",
        {"entry": entry, "line_item": li, "input_fields": input_fields},
    )


@login_required
def edit_flight_form(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        EventEntry, id=entry_id, household=household, slice_key="flights"
    )
    slice_obj = _get_flights_slice()
    li = _get_flight_line_item(slice_obj)
    input_fields = list(li.input_fields.order_by("display_order"))
    return render(
        request,
        "entries/partials/flight_edit_row.html",
        {"entry": entry, "line_item": li, "input_fields": input_fields},
    )


@login_required
def edit_flight(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        EventEntry, id=entry_id, household=household, slice_key="flights"
    )

    if request.method != "POST":
        return redirect("entries:flights")

    slice_obj = _get_flights_slice()
    li = _get_flight_line_item(slice_obj)
    input_fields = list(li.input_fields.order_by("display_order"))
    errors = {}

    new_inputs = _extract_flight_inputs(request.POST, input_fields)
    try:
        new_result_kg = catalogue_recalculate(
            li, new_inputs, entry.pinned_factors, li.published_formula().expression
        )
        entry.inputs = new_inputs
        entry.result_kg = new_result_kg
        entry.logged_by = request.user
        entry.save(update_fields=["inputs", "result_kg", "logged_by", "updated_at"])
        return render(
            request,
            "entries/partials/flight_row.html",
            {
                "entry": entry,
                "line_item": li,
                "input_fields": input_fields,
                "saved": True,
            },
        )
    except CatalogueValidationError as exc:
        errors = exc.errors

    return render(
        request,
        "entries/partials/flight_edit_row.html",
        {
            "entry": entry,
            "line_item": li,
            "input_fields": input_fields,
            "form_errors": errors,
        },
    )


@login_required
def delete_flight(request, entry_id):
    if request.method != "POST":
        return redirect("entries:flights")
    household = _get_household(request)
    entry = get_object_or_404(
        EventEntry, id=entry_id, household=household, slice_key="flights"
    )
    entry.delete()
    return HttpResponse("")


# ── Food (annual estimate) ────────────────────────────────────────────────────

_FOOD_QUICK_KEYS = [
    "diet_high_meat",
    "diet_medium_meat",
    "diet_low_meat",
    "diet_vegetarian",
    "diet_vegan",
]

_FOOD_DETAILED_KEYS = [
    "beef_lamb",
    "pork",
    "poultry",
    "fish",
    "dairy",
    "eggs",
    "vegetables",
    "fruit",
    "cereals",
    "legumes",
    "nuts",
]

_DIET_LABELS = {
    "high_meat": "High meat (daily)",
    "medium_meat": "Medium meat (few times/week)",
    "low_meat": "Low meat / pescatarian",
    "vegetarian": "Vegetarian",
    "vegan": "Vegan",
}


def _current_estimate(household, slice_key):
    return AnnualEstimate.objects.filter(
        household=household, slice_key=slice_key
    ).first()


def _food_context(
    household, slice_obj, mode, form_inputs=None, form_errors=None, saved=False
):
    current = _current_estimate(household, "food")
    history = AnnualEstimate.objects.filter(household=household, slice_key="food")[:5]
    detailed_items = [
        li
        for li in slice_obj.line_items.filter(active=True).order_by("display_order")
        if li.key in _FOOD_DETAILED_KEYS
    ]
    return {
        "slice": slice_obj,
        "current_estimate": current,
        "history": history,
        "mode": mode,
        "diet_options": list(_DIET_LABELS.items()),
        "detailed_items": detailed_items,
        "form_inputs": form_inputs or {},
        "form_errors": form_errors or {},
        "saved": saved,
        "today": date.today().isoformat(),
        "household_size": household.size,
    }


@login_required
def food(request):
    household = _get_household(request)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="food"
    )
    current = _current_estimate(household, "food")
    mode = request.GET.get("mode", current.mode if current else "quick")
    ctx = _food_context(household, slice_obj, mode)
    return render(request, "entries/food.html", ctx)


@login_required
def food_save(request):
    if request.method != "POST":
        return redirect("entries:food")

    household = _get_household(request)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="food"
    )
    mode = request.POST.get("mode", "quick")
    date_str = request.POST.get("effective_from", "").strip()
    try:
        effective_from = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        effective_from = date.today()

    # Build inputs for the selected mode only; the other mode's items stay zero
    if mode == "quick":
        diet_type = request.POST.get("diet_type", "medium_meat")
        li_key = f"diet_{diet_type}"
        people = request.POST.get("people", "").strip() or "0"
        inputs = {li_key: {"people": people}}
    else:
        inputs = {}
        for li_key in _FOOD_DETAILED_KEYS:
            inputs[li_key] = {
                "kg": request.POST.get(f"{li_key}__kg", "").strip() or "0"
            }

    try:
        result = catalogue_calculate(slice_obj, inputs, effective_from)
        AnnualEstimate.objects.create(
            household=household,
            slice_key="food",
            effective_from=effective_from,
            inputs=inputs,
            pinned_factors=result.pinned_factors,
            result_kg=result.result_kg,
            formula_version=result.formula_version,
            mode=mode,
            logged_by=request.user,
        )
        ctx = _food_context(household, slice_obj, mode, saved=True)
    except CatalogueValidationError as exc:
        ctx = _food_context(
            household,
            slice_obj,
            mode,
            form_inputs=inputs,
            form_errors=exc.errors,
        )

    return render(request, "entries/partials/food_section.html", ctx)


# ── Purchases (annual estimate) ───────────────────────────────────────────────


def _purchases_context(
    household, slice_obj, form_inputs=None, form_errors=None, saved=False
):
    current = _current_estimate(household, "purchases")
    history = AnnualEstimate.objects.filter(household=household, slice_key="purchases")[
        :5
    ]
    line_items = list(
        slice_obj.line_items.filter(active=True).order_by("display_order")
    )
    return {
        "slice": slice_obj,
        "current_estimate": current,
        "history": history,
        "line_items": line_items,
        "form_inputs": form_inputs or {},
        "form_errors": form_errors or {},
        "saved": saved,
        "today": date.today().isoformat(),
    }


@login_required
def purchases(request):
    household = _get_household(request)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="purchases"
    )
    ctx = _purchases_context(household, slice_obj)
    return render(request, "entries/purchases.html", ctx)


@login_required
def purchases_save(request):
    if request.method != "POST":
        return redirect("entries:purchases")

    household = _get_household(request)
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="purchases"
    )
    date_str = request.POST.get("effective_from", "").strip()
    try:
        effective_from = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        effective_from = date.today()

    line_items = list(
        slice_obj.line_items.filter(active=True).order_by("display_order")
    )
    inputs = {}
    for li in line_items:
        for field in li.input_fields.all():
            val = request.POST.get(f"{li.key}__{field.name}", "").strip() or "0"
            inputs.setdefault(li.key, {})[field.name] = val

    try:
        result = catalogue_calculate(slice_obj, inputs, effective_from)
        AnnualEstimate.objects.create(
            household=household,
            slice_key="purchases",
            effective_from=effective_from,
            inputs=inputs,
            pinned_factors=result.pinned_factors,
            result_kg=result.result_kg,
            formula_version=result.formula_version,
            mode="",
            logged_by=request.user,
        )
        ctx = _purchases_context(household, slice_obj, saved=True)
    except CatalogueValidationError as exc:
        ctx = _purchases_context(
            household, slice_obj, form_inputs=inputs, form_errors=exc.errors
        )

    return render(request, "entries/partials/purchases_section.html", ctx)


# ── Breakdown (transparency) ──────────────────────────────────────────────────


def _parse_formula_version(formula_version: str) -> dict:
    """Parse 'li_key:v1|other:v2' → {'li_key': 1, 'other': 2}."""
    result = {}
    for part in formula_version.split("|"):
        if ":v" in part:
            key, ver = part.rsplit(":v", 1)
            try:
                result[key] = int(ver)
            except ValueError:
                pass
    return result


def _build_breakdown_items(inputs, pinned_factors, formula_version, flat_inputs=False):
    """
    Return a list of breakdown dicts, one per line item in formula_version.

    flat_inputs=True: inputs is {field_name: value} (EventEntry style, single li_key).
    flat_inputs=False: inputs is {li_key: {field_name: value}}.
    """
    from decimal import Decimal

    from catalogue.models import Factor, Formula
    from engine.dsl import (
        DSLEvalError,
        DSLSyntaxError,
        collect_factor_keys,
        eval_expression,
        parse,
    )

    version_map = _parse_formula_version(formula_version)

    # Bulk fetch formulas and factors
    formulas = {}
    for li_key, ver in version_map.items():
        try:
            formulas[li_key] = Formula.objects.select_related("line_item__slice").get(
                line_item__key=li_key, version=ver
            )
        except Formula.DoesNotExist:
            pass

    factor_qs = Factor.objects.filter(key__in=pinned_factors.keys()).select_related(
        "factor_set"
    )
    factor_meta = {}
    for f in factor_qs:
        if f.key not in factor_meta:
            factor_meta[f.key] = {
                "citation": f.citation,
                "factor_set": f.factor_set.name,
                "source": f.factor_set.source,
                "licence": f.factor_set.licence,
            }

    items = []
    for li_key, ver in version_map.items():
        formula = formulas.get(li_key)
        if flat_inputs:
            li_inputs = inputs
        else:
            li_inputs = inputs.get(li_key, {}) if isinstance(inputs, dict) else {}

        # Determine which factor keys this formula uses
        used_factor_keys = set()
        if formula:
            try:
                ast = parse(formula.expression)
                used_factor_keys = collect_factor_keys(ast)
            except (DSLSyntaxError, Exception):
                pass

        used_factors = [
            {
                "key": k,
                "value": pinned_factors.get(k, "?"),
                **factor_meta.get(
                    k, {"citation": "", "factor_set": "", "source": "", "licence": ""}
                ),
            }
            for k in sorted(used_factor_keys)
            if k in pinned_factors
        ]

        # Re-evaluate per line item so we can show the arithmetic result
        line_result = None
        if formula and pinned_factors:
            try:
                numeric_inputs = {
                    k: Decimal(str(v))
                    for k, v in li_inputs.items()
                    if v not in (None, "", "None")
                    and not isinstance(v, str)
                    or (
                        isinstance(v, str)
                        and v.lstrip("-").replace(".", "", 1).isdigit()
                    )
                }
                # Re-parse as Decimal properly
                numeric_inputs = {}
                for k, v in li_inputs.items():
                    if v is None or v == "":
                        numeric_inputs[k] = Decimal(0)
                    else:
                        try:
                            numeric_inputs[k] = Decimal(str(v))
                        except Exception:
                            pass
                factors_dec = {k: Decimal(str(v)) for k, v in pinned_factors.items()}
                line_result = eval_expression(
                    formula.expression, numeric_inputs, factors_dec
                )
            except (DSLSyntaxError, DSLEvalError, Exception):
                pass

        items.append(
            {
                "li_key": li_key,
                "formula_version": ver,
                "formula_expression": formula.expression if formula else None,
                "inputs": li_inputs,
                "used_factors": used_factors,
                "line_result": line_result,
            }
        )

    return items


@login_required
def breakdown_periodic(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(PeriodicEntry, id=entry_id, household=household)
    items = _build_breakdown_items(
        entry.inputs, entry.pinned_factors, entry.formula_version
    )
    return render(
        request,
        "entries/breakdown.html",
        {
            "entry": entry,
            "entry_type": "periodic",
            "items": items,
            "back_url": f"/entries/{entry.slice_key.replace('_', '-')}/",
        },
    )


@login_required
def breakdown_event(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(EventEntry, id=entry_id, household=household)
    items = _build_breakdown_items(
        entry.inputs, entry.pinned_factors, entry.formula_version, flat_inputs=True
    )
    return render(
        request,
        "entries/breakdown.html",
        {
            "entry": entry,
            "entry_type": "event",
            "items": items,
            "back_url": f"/entries/{entry.slice_key}/",
        },
    )


@login_required
def breakdown_estimate(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(AnnualEstimate, id=entry_id, household=household)
    items = _build_breakdown_items(
        entry.inputs, entry.pinned_factors, entry.formula_version
    )
    return render(
        request,
        "entries/breakdown.html",
        {
            "entry": entry,
            "entry_type": "estimate",
            "items": items,
            "back_url": f"/entries/{entry.slice_key}/",
        },
    )
