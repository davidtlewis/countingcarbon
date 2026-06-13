"""
Tests for engine.annualise — pure functions, no DB required.
Near-100% branch coverage is the goal (T8 acceptance criterion).
"""

from datetime import date
from decimal import Decimal

from engine.annualise import annualise, annualise_latest, build_chart_series


def _entry(slice_key, cadence, year, month, kg, period_end=None):
    """Build a minimal PeriodicEntry-like object via duck typing."""

    class _E:
        pass

    e = _E()
    e.slice_key = slice_key
    e.cadence = cadence
    e.period_start = date(year, month, 1)
    e.result_kg = Decimal(str(kg))

    if period_end is not None:
        e.period_end = period_end
    elif cadence == "monthly":
        m = month + 1
        e.period_end = date(year + (m > 12), (m - 1) % 12 + 1, 1)
    elif cadence == "quarterly":
        m = month + 3
        e.period_end = date(year + (m > 12), (m - 1) % 12 + 1, 1)
    else:  # annual
        e.period_end = date(year + 1, 1, 1)

    return e


# ── annualise() ───────────────────────────────────────────────────────────────


class TestAnnualise:
    def test_monthly_multiplies_by_12(self):
        assert annualise(Decimal("100"), "monthly") == Decimal("1200")

    def test_quarterly_multiplies_by_4(self):
        assert annualise(Decimal("100"), "quarterly") == Decimal("400")

    def test_annual_unchanged(self):
        assert annualise(Decimal("100"), "annual") == Decimal("100")

    def test_unknown_cadence_defaults_to_1(self):
        assert annualise(Decimal("100"), "weekly") == Decimal("100")

    def test_preserves_decimal_precision(self):
        result = annualise(Decimal("182.8600"), "monthly")
        assert result == Decimal("2194.3200")


# ── annualise_latest() ────────────────────────────────────────────────────────


class TestAnnualiseLatest:
    def test_empty_list_returns_empty_dict(self):
        assert annualise_latest([]) == {}

    def test_single_monthly_entry(self):
        e = _entry("home_energy", "monthly", 2025, 1, 100)
        assert annualise_latest([e]) == {"home_energy": Decimal("1200")}

    def test_single_quarterly_entry(self):
        e = _entry("home_energy", "quarterly", 2025, 1, 100)
        assert annualise_latest([e]) == {"home_energy": Decimal("400")}

    def test_picks_first_entry_per_slice(self):
        # annualise_latest expects newest-first order (as DB returns with -period_start)
        newer = _entry("home_energy", "monthly", 2025, 3, 200)
        older = _entry("home_energy", "monthly", 2025, 1, 100)
        result = annualise_latest([newer, older])
        assert result["home_energy"] == Decimal("2400")  # 200 × 12, not 100 × 12

    def test_multiple_slices_each_annualised(self):
        e1 = _entry("home_energy", "monthly", 2025, 1, 100)
        e2 = _entry("transport", "monthly", 2025, 1, 50)
        result = annualise_latest([e1, e2])
        assert result["home_energy"] == Decimal("1200")
        assert result["transport"] == Decimal("600")

    def test_only_latest_per_slice_counted(self):
        # Two entries for same slice — only the first (newest) should appear
        e1 = _entry("home_energy", "monthly", 2025, 3, 300)
        e2 = _entry("home_energy", "monthly", 2025, 1, 100)
        result = annualise_latest([e1, e2])
        assert len(result) == 1
        assert result["home_energy"] == Decimal("3600")


# ── build_chart_series() ──────────────────────────────────────────────────────


class TestBuildChartSeries:
    def test_empty_list_returns_empty(self):
        assert build_chart_series([]) == {"labels": [], "data": []}

    def test_single_monthly_entry(self):
        e = _entry("home_energy", "monthly", 2025, 1, 300)
        result = build_chart_series([e], today=date(2025, 1, 31))
        assert result["labels"] == ["Jan 2025"]
        assert result["data"] == [300.0]

    def test_gap_in_middle_is_none(self):
        jan = _entry("home_energy", "monthly", 2025, 1, 300)
        mar = _entry("home_energy", "monthly", 2025, 3, 250)
        result = build_chart_series([jan, mar], today=date(2025, 3, 31))
        assert result["labels"] == ["Jan 2025", "Feb 2025", "Mar 2025"]
        assert result["data"] == [300.0, None, 250.0]

    def test_no_data_for_current_month_is_none(self):
        jan = _entry("home_energy", "monthly", 2025, 1, 100)
        result = build_chart_series([jan], today=date(2025, 2, 28))
        assert result["data"][-1] is None

    def test_quarterly_split_per_month(self):
        q = _entry("home_energy", "quarterly", 2025, 1, 600)
        result = build_chart_series([q], today=date(2025, 3, 31))
        assert result["labels"] == ["Jan 2025", "Feb 2025", "Mar 2025"]
        assert result["data"] == [200.0, 200.0, 200.0]

    def test_annual_split_per_month(self):
        a = _entry("home_energy", "annual", 2025, 1, 2400)
        result = build_chart_series([a], today=date(2025, 3, 31))
        assert result["data"] == [200.0, 200.0, 200.0]

    def test_multiple_entries_same_month_summed(self):
        # Two slices both cover January
        e1 = _entry("home_energy", "monthly", 2025, 1, 200)
        e2 = _entry("transport", "monthly", 2025, 1, 100)
        result = build_chart_series([e1, e2], today=date(2025, 1, 31))
        assert result["data"] == [300.0]

    def test_labels_use_short_month_year_format(self):
        e = _entry("home_energy", "monthly", 2025, 6, 100)
        result = build_chart_series([e], today=date(2025, 6, 30))
        assert result["labels"] == ["Jun 2025"]

    def test_year_boundary_handled(self):
        dec = _entry("home_energy", "monthly", 2024, 12, 100)
        result = build_chart_series([dec], today=date(2025, 1, 31))
        assert result["labels"] == ["Dec 2024", "Jan 2025"]
        assert result["data"] == [100.0, None]
