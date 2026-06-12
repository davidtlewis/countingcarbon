import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass
class CalculationResult:
    result_kg: Decimal
    pinned_factors: dict  # {item_key: str(factor_value)}
    formula_version: str


class ValidationError(Exception):
    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(str(errors))


def _slice_version(slice_def: dict) -> str:
    """16-char hex hash of the slice definition. Changes if any factor changes."""
    canonical = json.dumps(slice_def, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _validate_inputs(slice_def: dict, inputs: dict) -> dict:
    """Return error dict (empty = valid). Inputs must be non-negative numbers."""
    errors = {}
    valid_keys = {item["key"] for item in slice_def["items"]}

    for key in inputs:
        if key not in valid_keys:
            errors[key] = f"Unknown field '{key}'"

    for item in slice_def["items"]:
        key = item["key"]
        val = inputs.get(key)
        if val is None or val == "":
            continue  # optional — treated as zero
        try:
            d = Decimal(str(val))
            if d < 0:
                errors[key] = "Value must be zero or positive"
        except InvalidOperation:
            errors[key] = "Must be a number"

    return errors


def calculate(slice_def: dict, inputs: dict) -> CalculationResult:
    """
    Validate inputs against slice_def, compute result_kg, return pinned factors
    and a formula_version hash of slice_def. Raises ValidationError on bad inputs.
    """
    errors = _validate_inputs(slice_def, inputs)
    if errors:
        raise ValidationError(errors)

    pinned_factors = {}
    result = Decimal("0")

    for item in slice_def["items"]:
        key = item["key"]
        factor = Decimal(str(item["factor"]))
        pinned_factors[key] = str(factor)

        quantity = Decimal(str(inputs.get(key) or 0))
        contribution = quantity * factor
        if item.get("negative"):
            result -= contribution  # credit — reduces footprint
        else:
            result += contribution

    return CalculationResult(
        result_kg=result.quantize(Decimal("0.0001")),
        pinned_factors=pinned_factors,
        formula_version=_slice_version(slice_def),
    )


def recalculate(slice_def: dict, inputs: dict, pinned_factors: dict) -> Decimal:
    """
    Recompute result_kg using stored pinned_factors (not current slice factors).
    Used when editing a past entry so historical factors are preserved.
    Raises ValidationError on bad inputs.
    """
    errors = _validate_inputs(slice_def, inputs)
    if errors:
        raise ValidationError(errors)

    result = Decimal("0")
    for item in slice_def["items"]:
        key = item["key"]
        factor = Decimal(str(pinned_factors.get(key, item["factor"])))
        quantity = Decimal(str(inputs.get(key) or 0))
        contribution = quantity * factor
        if item.get("negative"):
            result -= contribution
        else:
            result += contribution

    return result.quantize(Decimal("0.0001"))
