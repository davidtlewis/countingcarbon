"""
Tests for engine.calculate — the correctness core.
Near-100% branch coverage is the goal (T8 acceptance criterion).
"""

from decimal import Decimal

import pytest

from engine.calculate import CalculationResult, ValidationError, calculate, recalculate

SLICE = {
    "key": "home_energy",
    "label": "Home Energy",
    "items": [
        {
            "key": "gas_kwh",
            "factor": 0.18286,
            "negative": False,
            "unit": "kWh",
            "label": "Gas",
        },
        {
            "key": "solar_export_kwh",
            "factor": 0.20707,
            "negative": True,
            "unit": "kWh",
            "label": "Solar export",
        },
    ],
}


# ── calculate() ───────────────────────────────────────────────────────────────


class TestCalculate:
    def test_single_positive_item(self):
        result = calculate(SLICE, {"gas_kwh": 1000})
        assert result.result_kg == Decimal("182.8600")

    def test_single_negative_item(self):
        result = calculate(SLICE, {"solar_export_kwh": 500})
        assert result.result_kg == Decimal("-103.5350")

    def test_positive_and_negative_combined(self):
        result = calculate(SLICE, {"gas_kwh": 1000, "solar_export_kwh": 500})
        assert result.result_kg == Decimal("79.3250")

    def test_empty_inputs_treated_as_zero(self):
        assert calculate(SLICE, {}).result_kg == Decimal("0.0000")

    def test_none_value_treated_as_zero(self):
        assert calculate(SLICE, {"gas_kwh": None}).result_kg == Decimal("0.0000")

    def test_empty_string_treated_as_zero(self):
        assert calculate(SLICE, {"gas_kwh": ""}).result_kg == Decimal("0.0000")

    def test_pinned_factors_contains_all_slice_items(self):
        result = calculate(SLICE, {"gas_kwh": 100})
        assert set(result.pinned_factors.keys()) == {"gas_kwh", "solar_export_kwh"}

    def test_pinned_factor_values_match_slice(self):
        result = calculate(SLICE, {})
        assert result.pinned_factors["gas_kwh"] == str(Decimal("0.18286"))

    def test_formula_version_is_stable_across_runs(self):
        v1 = calculate(SLICE, {}).formula_version
        v2 = calculate(SLICE, {"gas_kwh": 999}).formula_version
        assert v1 == v2

    def test_formula_version_is_16_chars(self):
        assert len(calculate(SLICE, {}).formula_version) == 16

    def test_formula_version_changes_when_factor_changes(self):
        v1 = calculate(SLICE, {}).formula_version
        modified = {
            **SLICE,
            "items": [
                {
                    "key": "gas_kwh",
                    "factor": 0.99,
                    "negative": False,
                    "unit": "kWh",
                    "label": "Gas",
                },
            ],
        }
        v2 = calculate(modified, {}).formula_version
        assert v1 != v2

    def test_returns_calculation_result_dataclass(self):
        result = calculate(SLICE, {})
        assert isinstance(result, CalculationResult)
        assert isinstance(result.result_kg, Decimal)
        assert isinstance(result.pinned_factors, dict)
        assert isinstance(result.formula_version, str)

    def test_result_quantised_to_4dp(self):
        result = calculate(SLICE, {"gas_kwh": 1})
        assert result.result_kg == result.result_kg.quantize(Decimal("0.0001"))

    # ── Validation ──────────────────────────────────────────────────────────

    def test_unknown_key_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc:
            calculate(SLICE, {"unknown_field": 10})
        assert "unknown_field" in exc.value.errors

    def test_negative_value_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc:
            calculate(SLICE, {"gas_kwh": -1})
        assert "gas_kwh" in exc.value.errors

    def test_non_numeric_value_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc:
            calculate(SLICE, {"gas_kwh": "lots"})
        assert "gas_kwh" in exc.value.errors

    def test_multiple_errors_collected(self):
        with pytest.raises(ValidationError) as exc:
            calculate(SLICE, {"gas_kwh": "bad", "solar_export_kwh": -5})
        assert len(exc.value.errors) == 2

    def test_validation_error_has_errors_dict(self):
        with pytest.raises(ValidationError) as exc:
            calculate(SLICE, {"gas_kwh": "x"})
        assert isinstance(exc.value.errors, dict)


# ── recalculate() ─────────────────────────────────────────────────────────────


class TestRecalculate:
    def setup_method(self):
        self.original = calculate(SLICE, {"gas_kwh": 1000})
        self.pinned = self.original.pinned_factors

    def test_matches_calculate_with_same_factors(self):
        result = recalculate(SLICE, {"gas_kwh": 1000}, self.pinned)
        assert result == Decimal("182.8600")

    def test_ignores_changed_slice_factor(self):
        modified = {
            **SLICE,
            "items": [
                {
                    "key": "gas_kwh",
                    "factor": 0.99,
                    "negative": False,
                    "unit": "kWh",
                    "label": "Gas",
                },
                {
                    "key": "solar_export_kwh",
                    "factor": 0.20707,
                    "negative": True,
                    "unit": "kWh",
                    "label": "Solar export",
                },
            ],
        }
        # Should still use the pinned factor 0.18286, not 0.99
        result = recalculate(modified, {"gas_kwh": 1000}, self.pinned)
        assert result == Decimal("182.8600")

    def test_returns_decimal(self):
        result = recalculate(SLICE, {}, self.pinned)
        assert isinstance(result, Decimal)

    def test_negative_value_raises(self):
        with pytest.raises(ValidationError):
            recalculate(SLICE, {"gas_kwh": -1}, self.pinned)

    def test_non_numeric_raises(self):
        with pytest.raises(ValidationError):
            recalculate(SLICE, {"gas_kwh": "bad"}, self.pinned)

    def test_empty_inputs_give_zero(self):
        assert recalculate(SLICE, {}, self.pinned) == Decimal("0.0000")
