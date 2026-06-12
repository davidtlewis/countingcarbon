from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from engine.calculate import ValidationError, calculate, recalculate

from .models import HouseholdSlicePreference, PeriodicEntry
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
    """Return the normalised period_start date, or None if parsing fails."""
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
        # annual
        return date(int(post["period_year"]), 1, 1)
    except (ValueError, KeyError, TypeError):
        return None


def _extract_inputs(post: dict, slice_def: dict) -> dict:
    """Pull numeric input values for each slice item from POST data."""
    result = {}
    for item in slice_def["items"]:
        key = item["key"]
        val = post.get(key, "").strip()
        result[key] = val if val else None
    return result


# ── Home Energy ───────────────────────────────────────────────────────────────


@login_required
def home_energy(request):
    household = _get_household(request)
    preference = _get_or_create_preference(household, "home_energy")
    entries = PeriodicEntry.objects.filter(household=household, slice_key="home_energy")
    return render(
        request,
        "entries/home_energy.html",
        {
            "slice": HOME_ENERGY_SLICE,
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
    """Create a new PeriodicEntry. Returns HTMX partial on success or error."""
    household = _get_household(request)
    preference = _get_or_create_preference(household, "home_energy")
    cadence = preference.cadence

    errors = {}
    inputs = {}
    period_start = None

    if request.method == "POST":
        inputs = _extract_inputs(request.POST, HOME_ENERGY_SLICE)
        period_start = _parse_period_start(cadence, request.POST)

        if period_start is None:
            errors["period"] = "Please select a valid period."
        else:
            try:
                result = calculate(HOME_ENERGY_SLICE, inputs)
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
                        "slice": HOME_ENERGY_SLICE,
                        "entries": all_entries,
                        "preference": preference,
                        "cadence_choices": HouseholdSlicePreference._meta.get_field(
                            "cadence"
                        ).choices,
                        "saved_entry": entry,
                    },
                )
            except ValidationError as exc:
                errors.update(exc.errors)
            except Exception:
                # Unique constraint violation (duplicate period)
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
            "slice": HOME_ENERGY_SLICE,
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
    """GET: return the read-only row partial (used by Cancel in the edit form)."""
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )
    return render(
        request,
        "entries/partials/entry_row.html",
        {"slice": HOME_ENERGY_SLICE, "entry": entry},
    )


@login_required
def edit_entry_form(request, entry_id):
    """GET: return the edit form for a single row (HTMX swap)."""
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )
    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": HOME_ENERGY_SLICE, "entry": entry},
    )


@login_required
def edit_entry(request, entry_id):
    """POST: update an existing entry using its pinned_factors. Returns updated row (HTMX)."""
    household = _get_household(request)
    entry = get_object_or_404(
        PeriodicEntry, id=entry_id, household=household, slice_key="home_energy"
    )

    if request.method != "POST":
        return redirect("entries:home_energy")

    inputs = _extract_inputs(request.POST, HOME_ENERGY_SLICE)
    errors = {}

    try:
        new_result_kg = recalculate(HOME_ENERGY_SLICE, inputs, entry.pinned_factors)
        entry.inputs = inputs
        entry.result_kg = new_result_kg
        entry.logged_by = request.user
        entry.save(update_fields=["inputs", "result_kg", "logged_by", "updated_at"])
        return render(
            request,
            "entries/partials/entry_row.html",
            {"slice": HOME_ENERGY_SLICE, "entry": entry, "saved": True},
        )
    except ValidationError as exc:
        errors = exc.errors

    return render(
        request,
        "entries/partials/entry_edit_row.html",
        {"slice": HOME_ENERGY_SLICE, "entry": entry, "form_errors": errors},
    )
