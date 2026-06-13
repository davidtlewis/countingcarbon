"""
T15 — Catalogue parity tests.

Verifies that every formula + factor combination in catalogue_seed.json produces
the expected result from the reference spreadsheet. Fails if factor values or
formula expressions drift.

Running these tests requires the full catalogue to be loaded via load_catalogue.
A session-scoped fixture does this automatically before any test in this module.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command

from catalogue.models import resolve_factors
from engine.dsl import collect_factor_keys, eval_expression, parse

# ── Seed data ─────────────────────────────────────────────────────────────────

_SEED = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "catalogue_seed.json").read_text()
)

# Date used for factor resolution — any date within DESNZ 2024 validity window.
_AS_OF = date(2025, 1, 1)

# Tolerance: seed expected values are given to ≤2 decimal places; 0.01 covers rounding.
_TOLERANCE = Decimal("0.01")


# ── Parametrize all 46 test cases ─────────────────────────────────────────────


def _build_cases():
    cases = []
    for sl in _SEED["slices"]:
        for li in sl["line_items"]:
            expr = li.get("formula")
            if not expr:
                continue
            for tc in li.get("test_cases", []):
                label = tc.get("note") or f"{sl['key']}.{li['key']}"
                cases.append(
                    pytest.param(
                        expr,
                        tc["inputs"],
                        tc["expected"],
                        id=label,
                    )
                )
    return cases


_CASES = _build_cases()


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def _full_catalogue(django_db_setup, django_db_blocker):
    """Load the complete catalogue once per test session (idempotent)."""
    with django_db_blocker.unblock():
        call_command("load_catalogue", verbosity=0)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("formula_expr,inputs,expected", _CASES)
def test_formula_parity(_full_catalogue, formula_expr, inputs, expected):
    """Each seed test case must evaluate to within 0.01 kg of the expected value."""
    ast = parse(formula_expr)
    factor_keys = list(collect_factor_keys(ast))
    factors = resolve_factors(factor_keys, _AS_OF) if factor_keys else {}

    # Text fields (str values) are excluded from the numeric evaluation context.
    context = {k: Decimal(str(v)) for k, v in inputs.items() if not isinstance(v, str)}

    result = eval_expression(formula_expr, context, dict(factors))
    expected_d = Decimal(str(expected))

    assert abs(result - expected_d) <= _TOLERANCE, (
        f"formula: {formula_expr!r}\n"
        f"inputs:  {inputs}\n"
        f"got:     {result}\n"
        f"expected:{expected_d} (±{_TOLERANCE})"
    )
