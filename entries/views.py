from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from catalogue.models import Slice
from engine.calculate import ValidationError, recalculate
from engine.catalogue_calculate import (
    CatalogueValidationError,
    catalogue_calculate,
    catalogue_recalculate,
)

from .models import EventEntry, HouseholdSlicePreference, PeriodicEntry
from .slices import HOME_ENERGY_SLICE


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
    """
    Build nested inputs dict {li_key: {field_name: value}} from POST data.
    HTML form names are '{li_key}__{field_name}'.
    """
    inputs = {}
    for li in line_items:
        item_inputs = {}
        for field in li.input_fields.all():
            key = f"{li.key}__{field.name}"
            val = post.get(key, "").strip()
            if field.field_type == "boolean":
                # checkboxes are absent from POST when unchecked
                item_inputs[field.name] = "1" if key in post else "0"
            else:
                item_inputs[field.name] = val if val else None
        inputs[li.key] = item_inputs
    return inputs


def _is_phase2_entry(entry: PeriodicEntry) -> bool:
    """Phase 2 entries store inputs as nested dicts {li_key: {field: value}}."""
    if not entry.inputs:
        return False
    first_val = next(iter(entry.inputs.values()), None)
    return isinstance(first_val, dict)


# ── Home Energy (periodic, catalogue-backed) ──────────────────────────────────


@login_required
def home_energy(request):
    household = _get_household(request)
    preference = _get_or_create_preference(household, "home_energy")
    entries = PeriodicEntry.objects.filter(household=household, slice_key="home_energy")
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="home_energy"
    )
    return render(
        request,
        "entries/home_energy.html",
        {
            "slice": slice_obj,
            "entries": entries,
            "preference": preference,
            "cadence_choices": HouseholdSlicePreference._meta.get_field(
                "cadence"
            ).choices,
        },
    )


@login_required
def update_cadence(request):
    if request.method != "POST":
        return redirect("entries:home_energy")
    household = _get_household(request)
    new_cadence = request.POST.get("cadence", "monthly")
    valid = {c[0] for c in HouseholdSlicePreference._meta.get_field("cadence").choices}
    if new_cadence in valid:
        HouseholdSlicePreference.objects.update_or_create(
            household=household,
            slice_key="home_energy",
            defaults={"cadence": new_cadence},
        )
    return redirect("entries:home_energy")


@login_required
def add_entry(request):
    household = _get_household(request)
    preference = _get_or_create_preference(household, "home_energy")
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="home_energy"
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
                entry = PeriodicEntry.objects.create(
                    household=household,
                    slice_key="home_energy",
                    period_start=period_start,
                    cadence=cadence,
                    inputs=inputs,
                    pinned_factors=result.pinned_factors,
                    result_kg=result.result_kg,
                    formula_version=result.formula_version,
                    logged_by=request.user,
                )
                all_entries = PeriodicEntry.objects.filter(
                    household=household, slice_key="home_energy"
                )
                return render(
                    request,
                    "entries/partials/entries_section.html",
                    {
                        "slice": slice_obj,
                        "entries": all_entries,
                        "preference": preference,
                        "cadence_choices": HouseholdSlicePreference._meta.get_field(
                            "cadence"
                        ).choices,
                        "saved_entry": entry,
                    },
                )
            except CatalogueValidationError as exc:
                errors.update(exc.errors)
            except Exception:
                errors["period"] = (
                    "An entry for this period already exists. "
                    "Use the edit button to update it."
                )

    all_entries = PeriodicEntry.objects.filter(
        household=household, slice_key="home_energy"
    )
    return render(
        request,
        "entries/partials/entries_section.html",
        {
            "slice": slice_obj,
            "entries": all_entries,
            "preference": preference,
            "cadence_choices": HouseholdSlicePreference._meta.get_field(
                "cadence"
            ).choices,
            "form_errors": errors,
            "form_inputs": inputs,
            "form_period_start": period_start,
        },
    )


@login_required
def entry_row(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="home_energy"
    )
    return render(
        request,
        "entries/partials/entry_row.html",
        {"slice": slice_obj, "entry": entry},
    )


@login_required
def edit_entry_form(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )
    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="home_energy"
    )
    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": slice_obj, "entry": entry},
    )


@login_required
def edit_entry(request, entry_id):
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )

    if request.method != "POST":
        return redirect("entries:home_energy")

    slice_obj = Slice.objects.prefetch_related("line_items__input_fields").get(
        key="home_energy"
    )
    errors = {}

    if _is_phase2_entry(entry):
        # Phase 2 entry: use catalogue recalculate (per-item, sum)
        line_items = list(
            slice_obj.line_items.filter(active=True).order_by("display_order", "key")
        )
        new_inputs = _extract_catalogue_inputs(request.POST, line_items)
        try:
            # Recalculate using pinned factors and current formula expressions
            from decimal import Decimal

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
            from decimal import ROUND_HALF_UP

            new_result_kg = total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            entry.inputs = new_inputs
            entry.result_kg = new_result_kg
            entry.logged_by = request.user
            entry.save(update_fields=["inputs", "result_kg", "logged_by", "updated_at"])
            return render(
                request,
                "entries/partials/entry_row.html",
                {"slice": slice_obj, "entry": entry, "saved": True},
            )
        except CatalogueValidationError as exc:
            errors = exc.errors
    else:
        # Phase 1 entry: use original recalculate() with flat inputs
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
                {"slice": slice_obj, "entry": entry, "saved": True},
            )
        except ValidationError as exc:
            errors = exc.errors

    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": slice_obj, "entry": entry, "form_errors": errors},
    )


# ── Flights (event mode) ──────────────────────────────────────────────────────


def _get_flights_slice():
    return Slice.objects.prefetch_related("line_items__input_fields").get(key="flights")


def _get_flight_line_item(slice_obj):
    return slice_obj.line_items.get(key="flight")


def _extract_flight_inputs(post: dict, input_fields) -> dict:
    """Extract flat {field_name: value} for a single-item event entry."""
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
                # catalogue_calculate expects nested {li_key: {field: value}}
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
    # Return empty string — HTMX deletes the row via hx-swap="delete"
    from django.http import HttpResponse

    return HttpResponse("")
