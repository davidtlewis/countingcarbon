from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from engine.annualise import annualise_latest, build_chart_series
from entries.models import AnnualEstimate, EventEntry, PeriodicEntry

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
    "transport": "Transport",
    "flights": "Flights",
    "food": "Food",
    "purchases": "Purchases & Services",
}

# Colours for per-slice chart series
SLICE_COLORS = {
    "home_energy": "#2d8a4e",
    "transport": "#1a6bb5",
    "flights": "#e67e22",
    "food": "#9b59b6",
    "purchases": "#c0392b",
}


def _get_household(request):
    return request.user.membership.household


def _flights_trailing_12m(household) -> Decimal:
    cutoff = date.today() - timedelta(days=365)
    qs = EventEntry.objects.filter(
        household=household,
        slice_key="flights",
        event_date__gte=cutoff,
    )
    return sum((e.result_kg for e in qs), Decimal(0))


def _latest_annual_estimate(household, slice_key) -> Decimal | None:
    est = (
        AnnualEstimate.objects.filter(household=household, slice_key=slice_key)
        .only("result_kg")
        .first()
    )
    return est.result_kg if est else None


@login_required
def index(request):
    household = _get_household(request)
    members = household.member_count

    periodic_entries = PeriodicEntry.objects.filter(household=household).order_by(
        "-period_start"
    )

    # Build annualised dict from all sources
    annualised: dict[str, Decimal] = {}

    if periodic_entries.exists():
        annualised.update(annualise_latest(periodic_entries))

    flights_kg = _flights_trailing_12m(household)
    if flights_kg:
        annualised["flights"] = flights_kg

    for slice_key in ("food", "purchases"):
        kg = _latest_annual_estimate(household, slice_key)
        if kg is not None:
            annualised[slice_key] = kg

    has_data = bool(annualised)

    total_kg = None
    total_tonnes = None
    benchmarks_display = []
    household_bar_pct = 0
    slices_display = []
    tracked_labels = []

    if has_data:
        total_kg = sum(annualised.values(), Decimal("0"))
        total_tonnes = round(float(total_kg) / 1000, 2)

        slices_display = [
            {
                "key": k,
                "label": SLICE_LABELS.get(k, k),
                "kg": v,
                "color": SLICE_COLORS.get(k, "#888"),
            }
            for k, v in annualised.items()
        ]

        tracked_labels = [s["label"] for s in slices_display]

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
            "tracked_labels": tracked_labels,
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

    all_periodic = PeriodicEntry.objects.filter(household=household)

    # Determine which periodic slice keys exist
    periodic_slice_keys = list(
        all_periodic.values_list("slice_key", flat=True).distinct()
    )

    if len(periodic_slice_keys) <= 1:
        # Single slice — return a single household total series
        series = build_chart_series(all_periodic)
        slice_series = None
    else:
        # Multiple slices — build per-slice series and align labels
        per_slice = {}
        all_labels = None
        for sk in periodic_slice_keys:
            s = build_chart_series(all_periodic.filter(slice_key=sk))
            per_slice[sk] = s
            if all_labels is None or len(s["labels"]) > len(all_labels):
                all_labels = s["labels"]

        # Align all series to the same label set (pad shorter ones with None)
        label_index = {lbl: i for i, lbl in enumerate(all_labels)}
        for sk in periodic_slice_keys:
            s = per_slice[sk]
            if s["labels"] == all_labels:
                continue
            aligned = [None] * len(all_labels)
            for lbl, val in zip(s["labels"], s["data"]):
                if lbl in label_index:
                    aligned[label_index[lbl]] = val
            per_slice[sk]["data"] = aligned
            per_slice[sk]["labels"] = all_labels

        # Compute total series by summing non-None values per month
        total_data = []
        for i in range(len(all_labels)):
            vals = [
                per_slice[sk]["data"][i]
                for sk in periodic_slice_keys
                if per_slice[sk]["data"][i] is not None
            ]
            total_data.append(round(sum(vals), 2) if vals else None)

        series = {"labels": all_labels, "data": total_data}
        slice_series = {
            sk: {
                "data": per_slice[sk]["data"],
                "label": SLICE_LABELS.get(sk, sk),
                "color": SLICE_COLORS.get(sk, "#888"),
            }
            for sk in periodic_slice_keys
        }

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
            "slice_series": slice_series,
            "benchmarks": benchmarks_monthly,
        }
    )
