"""
Idempotent load/update of the catalogue from a JSON seed file.

Usage:
    uv run python manage.py load_catalogue [path] [--dry-run]

Default path: fixtures/catalogue_seed.json

Rules:
- FactorSets are matched by (name, region); missing ones are created.
- Factors are matched by (factor_set, key); values/units are updated if changed.
- Slices/LineItems/InputFields are matched by key; metadata is updated if changed.
- Formulas: if the latest published formula for a line item already has the same
  expression, it is left alone (test_cases are updated in-place if they differ).
  If the expression differs, a new version is created and published.
- --dry-run shows all changes without committing.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from catalogue.models import (
    Benchmark,
    Factor,
    FactorSet,
    Formula,
    InputField,
    LineItem,
    Slice,
)


class Command(BaseCommand):
    help = "Idempotent upsert of catalogue data from a JSON seed file."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="fixtures/catalogue_seed.json",
            help="Path to the JSON seed file (default: fixtures/catalogue_seed.json)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        dry_run = options["dry_run"]
        verbosity = options["verbosity"]

        if not path.exists():
            raise CommandError(f"Seed file not found: {path}")

        with path.open() as fh:
            data = json.load(fh)

        changes: list[str] = []

        try:
            with transaction.atomic():
                changes += self._load_factor_sets(data.get("factor_sets", []))
                changes += self._load_slices(data.get("slices", []))
                changes += self._load_benchmarks(data.get("benchmarks", []))
                if dry_run:
                    raise _Rollback()
        except _Rollback:
            pass

        if verbosity >= 1:
            if changes:
                for line in changes:
                    self.stdout.write(line)
            verb = "Would apply" if dry_run else "Applied"
            count = len(changes)
            suffix = f"{count} change(s)" if count else "no changes"
            style = self.style.WARNING if dry_run else self.style.SUCCESS
            self.stdout.write(style(f"{verb}: {suffix}."))

    # ── Factor sets ───────────────────────────────────────────────────────────

    def _load_factor_sets(self, factor_sets_data: list) -> list[str]:
        changes: list[str] = []
        for fs_data in factor_sets_data:
            valid_to = (
                date.fromisoformat(fs_data["valid_to"])
                if fs_data.get("valid_to")
                else None
            )
            fs, created = FactorSet.objects.get_or_create(
                name=fs_data["name"],
                region=fs_data["region"],
                defaults={
                    "source": fs_data.get("source", ""),
                    "licence": fs_data.get("licence", ""),
                    "valid_from": date.fromisoformat(fs_data["valid_from"]),
                    "valid_to": valid_to,
                },
            )
            if created:
                changes.append(f"  [CREATED] FactorSet '{fs.name}' ({fs.region})")

            for f_data in fs_data.get("factors", []):
                new_val = Decimal(str(f_data["value"]))
                factor, f_created = Factor.objects.get_or_create(
                    factor_set=fs,
                    key=f_data["key"],
                    defaults={
                        "value": new_val,
                        "unit": f_data.get("unit", ""),
                        "citation": f_data.get("citation", ""),
                    },
                )
                if f_created:
                    changes.append(
                        f"    [CREATED] Factor '{f_data['key']}' = {f_data['value']}"
                    )
                elif factor.value != new_val:
                    changes.append(
                        f"    [UPDATED] Factor '{f_data['key']}': {factor.value} → {new_val}"
                    )
                    factor.value = new_val
                    factor.unit = f_data.get("unit", "")
                    factor.citation = f_data.get("citation", "")
                    factor.save(update_fields=["value", "unit", "citation"])

        return changes

    # ── Slices ────────────────────────────────────────────────────────────────

    def _load_slices(self, slices_data: list) -> list[str]:
        changes: list[str] = []
        for sl_data in slices_data:
            sl, created = Slice.objects.get_or_create(
                key=sl_data["key"],
                defaults={
                    "name": sl_data["name"],
                    "icon": sl_data.get("icon", ""),
                    "description": sl_data.get("description", ""),
                    "entry_mode": sl_data["entry_mode"],
                    "display_order": sl_data.get("display_order", 0),
                    "active": True,
                },
            )
            if created:
                changes.append(f"  [CREATED] Slice '{sl.key}'")
            else:
                updated_fields = []
                for attr, val in [
                    ("name", sl_data["name"]),
                    ("icon", sl_data.get("icon", "")),
                    ("description", sl_data.get("description", "")),
                    ("display_order", sl_data.get("display_order", 0)),
                ]:
                    if getattr(sl, attr) != val:
                        setattr(sl, attr, val)
                        updated_fields.append(attr)
                if updated_fields:
                    sl.save(update_fields=updated_fields)
                    changes.append(
                        f"  [UPDATED] Slice '{sl.key}': {', '.join(updated_fields)}"
                    )

            for li_data in sl_data.get("line_items", []):
                changes += self._load_line_item(sl, li_data)

        return changes

    def _load_line_item(self, sl: Slice, li_data: dict) -> list[str]:
        changes: list[str] = []
        li, created = LineItem.objects.get_or_create(
            slice=sl,
            key=li_data["key"],
            defaults={
                "label": li_data.get("label", ""),
                "help_text": li_data.get("help_text", ""),
                "group": li_data.get("group"),
                "display_order": li_data.get("display_order", 0),
                "active": True,
            },
        )
        if created:
            changes.append(f"    [CREATED] LineItem '{sl.key}/{li.key}'")
        else:
            updated_fields = []
            for attr, val in [
                ("label", li_data.get("label", "")),
                ("help_text", li_data.get("help_text", "")),
                ("group", li_data.get("group")),
                ("display_order", li_data.get("display_order", 0)),
            ]:
                if getattr(li, attr) != val:
                    setattr(li, attr, val)
                    updated_fields.append(attr)
            if updated_fields:
                li.save(update_fields=updated_fields)
                changes.append(
                    f"    [UPDATED] LineItem '{sl.key}/{li.key}': {', '.join(updated_fields)}"
                )

        for order, field_data in enumerate(li_data.get("input_fields", []), start=1):
            changes += self._load_input_field(li, field_data, order)

        formula_expr = li_data.get("formula")
        if formula_expr:
            changes += self._load_formula(
                li, formula_expr, li_data.get("test_cases", [])
            )

        return changes

    def _load_input_field(
        self, li: LineItem, field_data: dict, display_order: int
    ) -> list[str]:
        changes: list[str] = []
        raw_min = field_data.get("min")
        min_value = Decimal(str(raw_min)) if raw_min is not None else None
        choices = field_data.get("choices")

        field, created = InputField.objects.get_or_create(
            line_item=li,
            name=field_data["name"],
            defaults={
                "label": field_data.get("label", ""),
                "field_type": field_data["type"],
                "unit": field_data.get("unit") or "",
                "min_value": min_value,
                "choices": choices,
                "display_order": display_order,
            },
        )
        if created:
            changes.append(
                f"      [CREATED] InputField '{li.key}/{field_data['name']}'"
            )
        else:
            updated_fields = []
            if field.label != field_data.get("label", ""):
                field.label = field_data.get("label", "")
                updated_fields.append("label")
            if field.min_value != min_value:
                field.min_value = min_value
                updated_fields.append("min_value")
            if field.choices != choices:
                field.choices = choices
                updated_fields.append("choices")
            if field.display_order != display_order:
                field.display_order = display_order
                updated_fields.append("display_order")
            if updated_fields:
                field.save(update_fields=updated_fields)
                changes.append(
                    f"      [UPDATED] InputField '{li.key}/{field_data['name']}': {', '.join(updated_fields)}"
                )

        return changes

    def _load_formula(
        self, li: LineItem, expression: str, test_cases: list
    ) -> list[str]:
        changes: list[str] = []
        published = li.published_formula()

        if published and published.expression == expression:
            if published.test_cases != test_cases:
                published.test_cases = test_cases
                published.save(update_fields=["test_cases"])
                changes.append(
                    f"      [UPDATED] Formula '{li.key}' v{published.version}: test_cases"
                )
            return changes

        # Create a new version
        max_v = li.formulas.aggregate(max_v=Max("version"))["max_v"] or 0
        new_version = max_v + 1
        Formula.objects.create(
            line_item=li,
            expression=expression,
            version=new_version,
            test_cases=test_cases,
            published_at=timezone.now(),
        )
        if published:
            changes.append(
                f"      [UPDATED] Formula '{li.key}': v{published.version}→v{new_version} (expression changed)"
            )
        else:
            changes.append(f"      [CREATED] Formula '{li.key}' v{new_version}")

        return changes

    # ── Benchmarks ────────────────────────────────────────────────────────────

    def _load_benchmarks(self, benchmarks_data: list) -> list[str]:
        changes: list[str] = []
        for bm_data in benchmarks_data:
            kg = Decimal(str(bm_data["kg_per_person_year"]))
            bm, created = Benchmark.objects.get_or_create(
                key=bm_data["key"],
                defaults={
                    "label": bm_data["label"],
                    "kg_per_person": kg,
                    "source": bm_data.get("source", ""),
                    "source_url": bm_data.get("source_url", ""),
                    "slice_key": bm_data.get("slice_key", ""),
                    "display_order": bm_data.get("display_order", 0),
                    "active": True,
                },
            )
            if created:
                changes.append(f"  [CREATED] Benchmark '{bm.key}'")
            else:
                updated_fields = []
                for attr, val in [
                    ("label", bm_data["label"]),
                    ("kg_per_person", kg),
                    ("source", bm_data.get("source", "")),
                    ("source_url", bm_data.get("source_url", "")),
                    ("slice_key", bm_data.get("slice_key", "")),
                    ("display_order", bm_data.get("display_order", 0)),
                ]:
                    if getattr(bm, attr) != val:
                        setattr(bm, attr, val)
                        updated_fields.append(attr)
                if updated_fields:
                    bm.save(update_fields=updated_fields)
                    changes.append(
                        f"  [UPDATED] Benchmark '{bm.key}': {', '.join(updated_fields)}"
                    )
        return changes


class _Rollback(Exception):
    """Sentinel raised to roll back a dry-run transaction."""
