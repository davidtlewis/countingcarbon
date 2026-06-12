from datetime import date
from decimal import Decimal

ANNUALISATION_FACTOR = {"monthly": 12, "quarterly": 4, "annual": 1}
# Number of calendar months each cadence covers
PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}


def annualise(result_kg: Decimal, cadence: str) -> Decimal:
    """Multiply a single periodic result up to an annual figure."""
    return Decimal(str(result_kg)) * Decimal(ANNUALISATION_FACTOR.get(cadence, 1))


def annualise_latest(entry_list) -> dict:
    """
    Return {slice_key: annualised_kg} using the most-recent entry per slice.
    entry_list must be ordered most-recent-first (i.e. order_by('-period_start')).
    """
    seen: set = set()
    result: dict = {}
    for entry in entry_list:
        if entry.slice_key not in seen:
            seen.add(entry.slice_key)
            result[entry.slice_key] = annualise(entry.result_kg, entry.cadence)
    return result


def build_chart_series(entry_list, today: date | None = None) -> dict:
    """
    Build month-by-month chart data from a list of PeriodicEntry-like objects.

    Each entry must expose: period_start (date), period_end (date),
    cadence (str), result_kg (Decimal).

    Returns {"labels": [str], "data": [float | None]}.
    None = no entry covers that month (rendered as a gap with spanGaps: false).
    Each entry contributes its per-month equivalent (result_kg / period_months).
    """
    entries = list(entry_list)
    if not entries:
        return {"labels": [], "data": []}

    if today is None:
        today = date.today()

    current_month = date(today.year, today.month, 1)

    spans = []
    for e in entries:
        months_in_period = PERIOD_MONTHS.get(e.cadence, 1)
        monthly_kg = Decimal(str(e.result_kg)) / Decimal(months_in_period)
        spans.append(
            {
                "start": e.period_start,
                "end": e.period_end,
                "monthly_kg": monthly_kg,
            }
        )

    earliest = min(s["start"] for s in spans)

    labels = []
    data = []
    m = date(earliest.year, earliest.month, 1)
    while m <= current_month:
        labels.append(m.strftime("%b %Y"))

        total: Decimal | None = None
        for span in spans:
            if span["start"] <= m < span["end"]:
                total = (total or Decimal("0")) + span["monthly_kg"]

        data.append(float(round(total, 2)) if total is not None else None)

        # Advance to next calendar month
        next_m = m.month + 1
        m = date(m.year + (next_m > 12), (next_m - 1) % 12 + 1, 1)

    return {"labels": labels, "data": data}
