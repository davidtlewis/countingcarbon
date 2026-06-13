"""
Engine v2: catalogue-driven calculation.

Uses LineItem → published Formula + resolved FactorSet to compute result_kg.
Inputs are per-line-item nested dicts: {line_item_key: {field_name: value}}.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from catalogue.models import BandTable, LineItem, Slice, resolve_factors
from engine.dsl import (
    DSLEvalError,
    DSLSyntaxError,
    eval_expression,
)

_QUANTISE = Decimal("0.0001")


class CatalogueValidationError(Exception):
    """Raised when user inputs fail validation. errors is {field_path: message}."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(str(errors))


@dataclass
class CatalogueResult:
    result_kg: Decimal
    pinned_factors: dict  # {factor_key: str(value)}
    formula_version: str  # "{line_item_key}:v{version}" joined by "|"


def _coerce_input(value, field_type: str):
    """
    Convert a raw input value for formula evaluation.
    Text fields return the raw string (not Decimal).
    Numeric/boolean/choice fields return Decimal or None (blank).
    Boolean inputs become Decimal 0 or 1.
    """
    if field_type == "text":
        return str(value) if value is not None else ""
    if value is None or value == "":
        return None
    if field_type == "boolean":
        return Decimal(1) if str(value) in ("1", "true", "True", "yes") else Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        raise ValueError(f"Not a valid number: {value!r}")


def _validate_item_inputs(item_inputs: dict, input_fields) -> tuple[dict, dict]:
    """
    Validate and coerce inputs for one line item.
    Returns (coerced_context, errors).
    Numeric/boolean/choice values are Decimal; text values are strings.
    Text fields are included in coerced_context for storage but excluded from
    formula evaluation (the DSL only works with numbers).
    """
    coerced = {}
    errors = {}
    declared = {f.name: f for f in input_fields}

    for key, field_obj in declared.items():
        raw = item_inputs.get(key)
        try:
            val = _coerce_input(raw, field_obj.field_type)
        except ValueError as exc:
            errors[key] = str(exc)
            continue

        if field_obj.field_type == "text":
            coerced[key] = val
            continue

        if val is None:
            val = Decimal(0)

        if field_obj.min_value is not None and val < field_obj.min_value:
            errors[key] = f"Must be at least {field_obj.min_value}."
            continue

        if field_obj.field_type in ("decimal", "integer") and val < 0:
            errors[key] = "Must not be negative."
            continue

        if field_obj.field_type == "choice" and field_obj.choices:
            valid_values = {Decimal(str(c["value"])) for c in field_obj.choices}
            if val not in valid_values:
                errors[key] = "Not a valid choice."
                continue

        coerced[key] = val

    return coerced, errors


def _make_lookup_fn(table_cache: dict):
    def lookup(table_name: str, value: Decimal) -> Decimal:
        if table_name not in table_cache:
            try:
                table_cache[table_name] = BandTable.objects.get(name=table_name)
            except BandTable.DoesNotExist:
                raise DSLEvalError(f"Band table '{table_name}' not found")
        return table_cache[table_name].lookup(value)

    return lookup


def catalogue_calculate(
    slice_obj: Slice,
    inputs: dict,
    as_of_date: date,
) -> CatalogueResult:
    """
    Calculate total kg CO₂e for a slice.

    Args:
        slice_obj: Slice model instance
        inputs: {line_item_key: {field_name: raw_value}}
        as_of_date: date for factor resolution (typically entry date)

    Returns CatalogueResult or raises CatalogueValidationError.
    """
    line_items = list(
        slice_obj.line_items.filter(active=True)
        .prefetch_related("input_fields", "formulas")
        .order_by("display_order", "key")
    )

    # Validate all inputs first; collect errors per line item
    all_errors = {}
    item_contexts = {}

    for li in line_items:
        item_inputs = inputs.get(li.key, {})
        coerced, errors = _validate_item_inputs(item_inputs, li.input_fields.all())
        if errors:
            for field_name, msg in errors.items():
                all_errors[f"{li.key}__{field_name}"] = msg
        item_contexts[li.key] = coerced

    if all_errors:
        raise CatalogueValidationError(all_errors)

    # Gather all factor keys needed across all formulas
    all_factor_keys = set()
    item_formulas = {}
    for li in line_items:
        formula = li.published_formula()
        if formula is None:
            continue
        item_formulas[li.key] = formula
        try:
            from engine.dsl import collect_factor_keys, parse

            ast = parse(formula.expression)
            all_factor_keys |= collect_factor_keys(ast)
        except DSLSyntaxError as exc:
            raise CatalogueValidationError({li.key: f"Formula error: {exc}"})

    # Resolve all factors in one DB hit
    resolved_factors = {}
    if all_factor_keys:
        resolved_factors = resolve_factors(list(all_factor_keys), as_of_date)

    pinned_factors = {k: str(v) for k, v in resolved_factors.items()}

    # Evaluate each line item
    total = Decimal(0)
    version_parts = []
    table_cache = {}
    lookup_fn = _make_lookup_fn(table_cache)

    for li in line_items:
        formula = item_formulas.get(li.key)
        if formula is None:
            continue

        # Exclude text fields from formula context — they can't be used in numeric expressions
        raw_context = item_contexts[li.key]
        context = {k: v for k, v in raw_context.items() if isinstance(v, Decimal)}
        try:
            result = eval_expression(
                formula.expression,
                context,
                {k: Decimal(str(v)) for k, v in resolved_factors.items()},
                lookup_fn,
            )
        except (DSLEvalError, DSLSyntaxError) as exc:
            raise CatalogueValidationError({li.key: f"Calculation error: {exc}"})

        total += result
        version_parts.append(f"{li.key}:v{formula.version}")

    result_kg = total.quantize(_QUANTISE, rounding=ROUND_HALF_UP)
    formula_version = "|".join(version_parts) if version_parts else "empty"

    return CatalogueResult(
        result_kg=result_kg,
        pinned_factors=pinned_factors,
        formula_version=formula_version,
    )


def catalogue_recalculate(
    line_item: LineItem,
    item_inputs: dict,
    pinned_factors: dict,
    formula_expression: str,
) -> Decimal:
    """
    Recompute a single line item using already-pinned factors (for edits).
    Returns Decimal result_kg for that item only.
    """
    coerced, errors = _validate_item_inputs(item_inputs, line_item.input_fields.all())
    if errors:
        raise CatalogueValidationError(
            {f"{line_item.key}__{k}": v for k, v in errors.items()}
        )

    # Exclude text fields from formula context
    numeric_context = {k: v for k, v in coerced.items() if isinstance(v, Decimal)}
    factors = {k: Decimal(str(v)) for k, v in pinned_factors.items()}
    try:
        return eval_expression(formula_expression, numeric_context, factors)
    except (DSLEvalError, DSLSyntaxError) as exc:
        raise CatalogueValidationError({line_item.key: str(exc)})
