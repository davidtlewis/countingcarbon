"""
Onboarding wizard: creates is_estimate=True entries from proxy questions.

Steps:
  1 — Home energy (heating type + home size)
  2 — Car (fuel type + annual mileage, or no car)
  3 — Flights (short-haul + long-haul count last year)
  4 — Diet (diet type + number of people)
  5 — Purchases (spending level)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from catalogue.models import Slice
from engine.catalogue_calculate import catalogue_calculate
from entries.models import AnnualEstimate, EventEntry, PeriodicEntry

WIZARD_SESSION_KEY = "onboarding_wizard"
TOTAL_STEPS = 5

# ── Proxy mappings ────────────────────────────────────────────────────────────

# Annual kWh by home size index (0=1bed, 1=2bed, 2=3bed, 3=4+bed)
_GAS_KWH = [8_000, 12_000, 18_000, 25_000]
_ELEC_KWH = [1_800, 2_700, 3_100, 4_100]
_ELEC_ONLY_KWH = [4_000, 6_000, 8_500, 12_000]  # electric storage heaters
_HEAT_PUMP_KWH = [3_000, 4_500, 6_000, 8_000]
_OIL_LITRES = [1_200, 1_800, 2_500, 3_500]  # litres per year
_LPG_LITRES = [900, 1_400, 2_000, 2_800]

# Annual km by mileage bracket index (0=<5k, 1=5-10k, 2=10-20k, 3=20k+)
_CAR_KM = [3_000, 7_500, 15_000, 27_000]

# Typical short-haul (one-way ~1,100 km) and long-haul (one-way ~8,000 km)
_SHORT_HAUL_KM = Decimal("1100")
_LONG_HAUL_KM = Decimal("8000")

# Annual purchases inputs by spending level
_PURCHASES_INPUTS = {
    "low": {
        "clothing": {"kg": "8"},
        "clothing_returns": {"parcels": "2"},
        "smartphones": {"units": "0"},
        "laptops": {"units": "0"},
        "tvs": {"units": "0"},
        "appliances": {"units": "1"},
        "furniture": {"gbp": "200"},
        "garden_diy": {"gbp": "100"},
        "restaurants": {"meals": "26"},
        "hotels": {"nights": "2"},
        "streaming": {"hours_per_week": "4"},
        "online_shopping": {"gbp": "500"},
    },
    "typical": {
        "clothing": {"kg": "16"},
        "clothing_returns": {"parcels": "6"},
        "smartphones": {"units": "0"},
        "laptops": {"units": "0"},
        "tvs": {"units": "0"},
        "appliances": {"units": "2"},
        "furniture": {"gbp": "500"},
        "garden_diy": {"gbp": "300"},
        "restaurants": {"meals": "52"},
        "hotels": {"nights": "5"},
        "streaming": {"hours_per_week": "8"},
        "online_shopping": {"gbp": "1500"},
    },
    "high": {
        "clothing": {"kg": "30"},
        "clothing_returns": {"parcels": "12"},
        "smartphones": {"units": "1"},
        "laptops": {"units": "0"},
        "tvs": {"units": "1"},
        "appliances": {"units": "3"},
        "furniture": {"gbp": "1200"},
        "garden_diy": {"gbp": "600"},
        "restaurants": {"meals": "104"},
        "hotels": {"nights": "10"},
        "streaming": {"hours_per_week": "15"},
        "online_shopping": {"gbp": "3000"},
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_slice(key: str) -> Slice:
    return Slice.objects.prefetch_related(
        "line_items__input_fields", "line_items__formulas"
    ).get(key=key)


def _current_month() -> date:
    today = date.today()
    return date(today.year, today.month, 1)


def _wizard_state(request) -> dict:
    return request.session.get(WIZARD_SESSION_KEY, {})


def _save_wizard_state(request, state: dict):
    request.session[WIZARD_SESSION_KEY] = state
    request.session.modified = True


# ── Step processors ───────────────────────────────────────────────────────────


def _process_step1(request, household) -> str | None:
    """Home energy. Returns error message or None on success."""
    heating = request.POST.get("heating", "")
    size_idx = int(request.POST.get("size", "1"))
    size_idx = max(0, min(3, size_idx))

    try:
        household_people = max(1, int(request.POST.get("household_people", "1")))
    except (ValueError, TypeError):
        household_people = 1
    household.size = household_people
    household.save(update_fields=["size"])

    inputs: dict = {
        "gas": {"kwh": "0"},
        "electricity_import": {"kwh": "0"},
        "heating_oil": {"litres": "0"},
        "lpg": {"litres": "0"},
        "solar_export": {"kwh": "0"},
    }

    elec_base = _ELEC_KWH[size_idx]

    if heating == "gas":
        inputs["gas"] = {"kwh": str(_GAS_KWH[size_idx] // 12)}
        inputs["electricity_import"] = {"kwh": str(elec_base // 12)}
    elif heating == "electric":
        inputs["electricity_import"] = {"kwh": str(_ELEC_ONLY_KWH[size_idx] // 12)}
    elif heating == "heat_pump":
        inputs["electricity_import"] = {"kwh": str(_HEAT_PUMP_KWH[size_idx] // 12)}
    elif heating == "oil":
        inputs["heating_oil"] = {"litres": str(_OIL_LITRES[size_idx] // 12)}
        inputs["electricity_import"] = {"kwh": str(elec_base // 12)}
    elif heating == "lpg":
        inputs["lpg"] = {"litres": str(_LPG_LITRES[size_idx] // 12)}
        inputs["electricity_import"] = {"kwh": str(elec_base // 12)}
    elif heating == "none":
        inputs["electricity_import"] = {"kwh": str(elec_base // 12)}
    else:
        return "Please select a heating type."

    today = _current_month()
    slice_obj = _get_slice("home_energy")
    try:
        result = catalogue_calculate(slice_obj, inputs, today)
    except Exception:
        return None  # skip silently if calc fails

    PeriodicEntry.objects.update_or_create(
        household=household,
        slice_key="home_energy",
        period_start=today,
        defaults={
            "cadence": "monthly",
            "inputs": inputs,
            "pinned_factors": result.pinned_factors,
            "result_kg": result.result_kg,
            "formula_version": result.formula_version,
            "is_estimate": True,
            "logged_by": request.user,
        },
    )
    return None


def _process_step2(request, household) -> str | None:
    """Car transport. Returns error message or None on success."""
    has_car = request.POST.get("has_car", "no")
    if has_car != "yes":
        return None  # no car → nothing to create

    fuel = request.POST.get("fuel", "")
    mileage_idx = int(request.POST.get("mileage", "1"))
    mileage_idx = max(0, min(3, mileage_idx))

    fuel_to_key = {
        "petrol": "car_petrol",
        "diesel": "car_diesel",
        "electric": "car_ev",
        "hybrid": "car_hybrid",
    }
    if fuel not in fuel_to_key:
        return "Please select a fuel type."

    monthly_km = _CAR_KM[mileage_idx] // 12
    line_item_key = fuel_to_key[fuel]

    inputs: dict = {
        "car_petrol": {"km": "0"},
        "car_diesel": {"km": "0"},
        "car_ev": {"km": "0"},
        "car_hybrid": {"km": "0"},
        "rail": {"km": "0"},
        "underground": {"km": "0"},
        "bus": {"km": "0"},
        "coach": {"km": "0"},
        "ferry": {"km": "0"},
        "motorbike": {"km": "0"},
    }
    inputs[line_item_key] = {"km": str(monthly_km)}

    today = _current_month()
    slice_obj = _get_slice("transport")
    try:
        result = catalogue_calculate(slice_obj, inputs, today)
    except Exception:
        return None

    PeriodicEntry.objects.update_or_create(
        household=household,
        slice_key="transport",
        period_start=today,
        defaults={
            "cadence": "monthly",
            "inputs": inputs,
            "pinned_factors": result.pinned_factors,
            "result_kg": result.result_kg,
            "formula_version": result.formula_version,
            "is_estimate": True,
            "logged_by": request.user,
        },
    )
    return None


def _process_step3(request, household) -> str | None:
    """Flights. Creates EventEntry records for short and long-haul."""
    short_bracket = request.POST.get("short_haul", "0")
    long_bracket = request.POST.get("long_haul", "0")

    short_counts = {"0": 0, "1-2": 1, "3-5": 4, "6+": 6}
    long_counts = {"0": 0, "1-2": 1, "3+": 3}

    n_short = short_counts.get(short_bracket, 0)
    n_long = long_counts.get(long_bracket, 0)

    if n_short == 0 and n_long == 0:
        return None

    today = date.today()
    slice_obj = _get_slice("flights")

    # Delete existing estimate flights for this household to avoid duplicates
    EventEntry.objects.filter(
        household=household, slice_key="flights", is_estimate=True
    ).delete()

    def _create_flight(distance_km: Decimal, label: str):
        inputs = {
            "flight": {
                "route": label,
                "passengers": "1",
                "distance_km": str(distance_km),
                "is_return": "1",
                "cabin_class": "1",
            }
        }
        try:
            result = catalogue_calculate(slice_obj, inputs, today)
        except Exception:
            return
        EventEntry.objects.create(
            household=household,
            slice_key="flights",
            event_date=today,
            inputs=inputs,
            pinned_factors=result.pinned_factors,
            result_kg=result.result_kg,
            formula_version=result.formula_version,
            is_estimate=True,
            logged_by=request.user,
        )

    for _ in range(n_short):
        _create_flight(_SHORT_HAUL_KM, "Short-haul (estimate)")
    for _ in range(n_long):
        _create_flight(_LONG_HAUL_KM, "Long-haul (estimate)")

    return None


def _process_step4(request, household) -> str | None:
    """Diet. Creates AnnualEstimate for the selected diet type."""
    diet = request.POST.get("diet", "")
    try:
        people = max(1, int(request.POST.get("people", str(household.size))))
    except (ValueError, TypeError):
        people = household.size

    diet_keys = {
        "high_meat": "diet_high_meat",
        "medium_meat": "diet_medium_meat",
        "low_meat": "diet_low_meat",
        "vegetarian": "diet_vegetarian",
        "vegan": "diet_vegan",
    }
    if diet not in diet_keys:
        return "Please select a diet type."

    line_item_key = diet_keys[diet]

    # All line items zeroed out except the chosen diet
    slice_obj = _get_slice("food")
    inputs: dict = {}
    for li in slice_obj.line_items.filter(active=True):
        if li.key in diet_keys.values():
            inputs[li.key] = {"people": "0"}
        else:
            for field in li.input_fields.all():
                inputs[li.key] = {field.name: "0"}
    inputs[line_item_key] = {"people": str(people)}

    today = date.today()
    try:
        result = catalogue_calculate(slice_obj, inputs, today)
    except Exception:
        return None

    AnnualEstimate.objects.create(
        household=household,
        slice_key="food",
        effective_from=today,
        inputs=inputs,
        pinned_factors=result.pinned_factors,
        result_kg=result.result_kg,
        formula_version=result.formula_version,
        mode="quick",
        is_estimate=True,
        logged_by=request.user,
    )
    return None


def _process_step5(request, household) -> str | None:
    """Purchases. Creates AnnualEstimate for the selected spending level."""
    level = request.POST.get("level", "")
    if level not in _PURCHASES_INPUTS:
        return "Please select a spending level."

    inputs = _PURCHASES_INPUTS[level]
    today = date.today()
    slice_obj = _get_slice("purchases")
    try:
        result = catalogue_calculate(slice_obj, inputs, today)
    except Exception:
        return None

    AnnualEstimate.objects.create(
        household=household,
        slice_key="purchases",
        effective_from=today,
        inputs=inputs,
        pinned_factors=result.pinned_factors,
        result_kg=result.result_kg,
        formula_version=result.formula_version,
        is_estimate=True,
        logged_by=request.user,
    )
    return None


_STEP_PROCESSORS = {
    1: _process_step1,
    2: _process_step2,
    3: _process_step3,
    4: _process_step4,
    5: _process_step5,
}

_STEP_TITLES = {
    1: "Home energy",
    2: "Car & transport",
    3: "Flights",
    4: "Diet",
    5: "Purchases",
}

# ── View ──────────────────────────────────────────────────────────────────────


@login_required
def wizard_view(request, step: int = 1):
    try:
        household = request.user.membership.household
    except Exception:
        return redirect("onboarding")

    if step < 1 or step > TOTAL_STEPS:
        return redirect("onboarding_wizard", step=1)

    error = None

    if request.method == "POST":
        if "skip" in request.POST:
            # Skip this step — advance without creating entries
            pass
        elif "skip_all" in request.POST:
            messages.success(request, "You can add your data any time from the menu.")
            return redirect("dashboard:index")
        else:
            processor = _STEP_PROCESSORS.get(step)
            if processor:
                error = processor(request, household)

        if error is None:
            if step < TOTAL_STEPS:
                return redirect("onboarding_wizard", step=step + 1)
            else:
                messages.success(
                    request,
                    "Your estimated footprint is ready — replace estimates with real "
                    "data whenever you like.",
                )
                return redirect("dashboard:index")

    context = {
        "step": step,
        "total_steps": TOTAL_STEPS,
        "step_title": _STEP_TITLES.get(step, ""),
        "error": error,
        "progress_pct": int((step - 1) / TOTAL_STEPS * 100),
        "household": household,
    }
    return render(request, "accounts/onboarding_wizard.html", context)
