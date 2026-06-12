from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from engine.annualise import annualise_latest, build_chart_series
from entries.models import PeriodicEntry

# kg CO₂e per person per year — sourced from fixtures/catalogue_seed.json
BENCHMARKS = [
    {
        "key": "uk_average",
        "label": "UK average",
        "kg_per_person": 10_000,
        "color": "#e74c3c",
    },
    {
        "key": "global_average",
        "label": "Global average",
        "kg_per_person": 4_700,
        "color": "#e67e22",
    },
    {
        "key": "ccc_2030",
        "label": "UK CCC 2030 target",
        "kg_per_person": 2_500,
        "color": "#3498db",
    },
    {
        "key": "fair_share_15c",
        "label": "1.5°C fair share",
        "kg_per_person": 2_300,
        "color": "#9b59b6",
    },
]

SLICE_LABELS = {
    "home_energy": "Home Energy",
}


def _get_household(request):
    return request.user.membership.household


@login_required
def index(request):
    household = _get_household(request)
    members = household.member_count

    entries = PeriodicEntry.objects.filter(household=household).order_by(
        "-period_start"
    )
    has_data = entries.exists()

    total_kg = None
    total_tonnes = None
    annualised = {}
    benchmarks_display = []
    household_bar_pct = 0

    slices_display = []
    if has_data:
        annualised = annualise_latest(entries)
        total_kg = sum(annualised.values(), Decimal("0"))
        total_tonnes = round(float(total_kg) / 1000, 2)

        slices_display = [
            {"key": k, "label": SLICE_LABELS.get(k, k), "kg": v}
            for k, v in annualised.items()
        ]

        benchmark_kg_values = [b["kg_per_person"] * members for b in BENCHMARKS]
        max_value = max([float(total_kg)] + benchmark_kg_values) or 1

        for b in BENCHMARKS:
            kg_total = b["kg_per_person"] * members
            benchmarks_display.append(
                {
                    **b,
                    "kg_total": kg_total,
                    "bar_pct": int(kg_total / max_value * 100),
                }
            )

        household_bar_pct = int(float(total_kg) / max_value * 100)

    return render(
        request,
        "dashboard/index.html",
        {
            "total_kg": total_kg,
            "total_tonnes": total_tonnes,
            "slices": slices_display,
            "benchmarks": benchmarks_display,
            "members": members,
            "household_bar_pct": household_bar_pct,
            "has_data": has_data,
        },
    )


@login_required
def chart_data(request):
    household = _get_household(request)
    members = household.member_count

    entries = PeriodicEntry.objects.filter(household=household)
    series = build_chart_series(entries)

    benchmarks_monthly = [
        {
            "key": b["key"],
            "label": b["label"],
            "monthly_kg": round(b["kg_per_person"] * members / 12, 1),
            "color": b["color"],
        }
        for b in BENCHMARKS
    ]

    return JsonResponse(
        {
            "labels": series["labels"],
            "household": series["data"],
            "benchmarks": benchmarks_monthly,
        }
    )
