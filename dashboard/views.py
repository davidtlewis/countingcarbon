from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from catalogue.models import Benchmark
from engine.annualise import annualise_latest, build_chart_series
from entries.models import AnnualEstimate, EventEntry, PeriodicEntry

SLICE_LABELS = {
    "home_energy": "Home Energy",
    "transport": "Transport",
    "flights": "Flights",
    "food": "Food",
    "purchases": "Purchases & Services",
}

SLICE_URLS = {
    "home_energy": "/entries/home-energy/",
    "transport": "/entries/transport/",
    "flights": "/entries/flights/",
    "food": "/entries/food/",
    "purchases": "/entries/purchases/",
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


def _prev_month(d: date, n: int) -> date:
    """Return the date n calendar months before d (first of that month)."""
    total = d.year * 12 + d.month - 1 - n
    return date(total // 12, total % 12 + 1, 1)


def _build_flights_chart_series(household, today=None) -> dict | None:
    """Trailing 12-month rolling average of flight emissions, plotted monthly.

    For each month M, sums all flights in the 12 months ending at M and
    divides by 12. This smooths per-flight spikes and stays consistent with
    the headline _flights_trailing_12m figure on the dashboard.
    """
    if today is None:
        today = date.today()
    events = list(EventEntry.objects.filter(household=household, slice_key="flights"))
    if not events:
        return None

    monthly: dict[date, Decimal] = defaultdict(Decimal)
    for e in events:
        monthly[date(e.event_date.year, e.event_date.month, 1)] += e.result_kg

    current_month = date(today.year, today.month, 1)
    earliest = min(monthly)
    labels, data = [], []
    m = earliest
    while m <= current_month:
        window_start = _prev_month(m, 11)
        total = sum(v for k, v in monthly.items() if window_start <= k <= m)
        labels.append(m.strftime("%b %Y"))
        data.append(float(round(total / 12, 2)))
        next_m = m.month + 1
        m = date(m.year + (next_m > 12), (next_m - 1) % 12 + 1, 1)
    return {"labels": labels, "data": data}


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

        slice_benchmarks_pre = {}
        for sb in Benchmark.objects.filter(active=True).exclude(slice_key=""):
            slice_benchmarks_pre.setdefault(sb.slice_key, []).append(sb)

        slices_display = [
            {
                "key": k,
                "label": SLICE_LABELS.get(k, k),
                "url": SLICE_URLS.get(k, f"/entries/{k}/"),
                "kg": v,
                "color": SLICE_COLORS.get(k, "#888"),
                "benchmarks": [
                    {
                        "label": sb.label,
                        "kg_per_person": float(sb.kg_per_person),
                        "source": sb.source,
                        "source_url": sb.source_url,
                    }
                    for sb in slice_benchmarks_pre.get(k, [])
                ],
            }
            for k, v in annualised.items()
        ]

        tracked_labels = [s["label"] for s in slices_display]

        whole_benchmarks = list(
            Benchmark.objects.filter(active=True, slice_key="").order_by(
                "display_order"
            )
        )
        benchmark_kg_values = [
            float(b.kg_per_person) * members for b in whole_benchmarks
        ]
        max_value = max([float(total_kg)] + benchmark_kg_values) or 1

        for b in whole_benchmarks:
            kg_total = float(b.kg_per_person) * members
            benchmarks_display.append(
                {
                    "key": b.key,
                    "label": b.label,
                    "kg_total": kg_total,
                    "bar_pct": int(kg_total / max_value * 100),
                    "source": b.source,
                    "source_url": b.source_url,
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
    today = date.today()

    all_periodic = PeriodicEntry.objects.filter(household=household)
    periodic_slice_keys = list(
        all_periodic.values_list("slice_key", flat=True).distinct()
    )

    per_slice = {
        sk: build_chart_series(all_periodic.filter(slice_key=sk), today=today)
        for sk in periodic_slice_keys
    }

    flights_series = _build_flights_chart_series(household, today=today)
    if flights_series:
        per_slice["flights"] = flights_series

    all_slice_keys = list(per_slice.keys())

    if len(all_slice_keys) <= 1:
        series = (
            per_slice[all_slice_keys[0]]
            if all_slice_keys
            else {"labels": [], "data": []}
        )
        slice_series = None
    else:
        # Align all series to the longest label set
        all_labels = max((per_slice[sk]["labels"] for sk in all_slice_keys), key=len)
        label_index = {lbl: i for i, lbl in enumerate(all_labels)}
        for sk in all_slice_keys:
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
                for sk in all_slice_keys
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
            for sk in all_slice_keys
        }

    whole_benchmarks = Benchmark.objects.filter(active=True, slice_key="").order_by(
        "display_order"
    )
    benchmarks_monthly = [
        {
            "key": b.key,
            "label": b.label,
            "monthly_kg": round(float(b.kg_per_person) * members / 12, 1),
            "color": "#888",
        }
        for b in whole_benchmarks
    ]

    return JsonResponse(
        {
            "labels": series["labels"],
            "household": series["data"],
            "slice_series": slice_series,
            "benchmarks": benchmarks_monthly,
        }
    )
