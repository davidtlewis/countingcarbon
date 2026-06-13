"""
Data migration: seed the DESNZ 2024 factor set (home energy factors) and
the Home Energy catalogue slice with its 5 line items, input fields and
published formulas.

This replaces the Phase 1 hard-coded HOME_ENERGY_SLICE dict; existing
PeriodicEntry rows are left untouched (their pinned_factors remain valid).
"""

import datetime

from django.db import migrations
from django.utils import timezone


def seed_home_energy(apps, schema_editor):
    FactorSet = apps.get_model("catalogue", "FactorSet")
    Factor = apps.get_model("catalogue", "Factor")
    Slice = apps.get_model("catalogue", "Slice")
    LineItem = apps.get_model("catalogue", "LineItem")
    InputField = apps.get_model("catalogue", "InputField")
    Formula = apps.get_model("catalogue", "Formula")

    # ── DESNZ 2024 factor set ───────────────────────────────────────────────
    fs, _ = FactorSet.objects.get_or_create(
        name="DESNZ 2024",
        region="GB",
        defaults={
            "source": "UK Government Greenhouse Gas Reporting: Conversion Factors 2024",
            "licence": "Open Government Licence v3.0",
            "valid_from": datetime.date(2024, 6, 1),
            "valid_to": None,
        },
    )

    home_energy_factors = [
        (
            "gas_kwh",
            "0.18286",
            "kg CO2e/kWh",
            "DESNZ 2024, Fuels: natural gas (gross CV)",
        ),
        (
            "elec_kwh",
            "0.20707",
            "kg CO2e/kWh",
            "DESNZ 2024, UK electricity: generation",
        ),
        (
            "oil_litres",
            "2.52020",
            "kg CO2e/litre",
            "DESNZ 2024, Fuels: burning oil (kerosene)",
        ),
        ("lpg_litres", "1.55340", "kg CO2e/litre", "DESNZ 2024, Fuels: LPG (average)"),
    ]
    for key, value, unit, citation in home_energy_factors:
        Factor.objects.get_or_create(
            factor_set=fs,
            key=key,
            defaults={"value": value, "unit": unit, "citation": citation},
        )

    # ── Home Energy slice ───────────────────────────────────────────────────
    he_slice, _ = Slice.objects.get_or_create(
        key="home_energy",
        defaults={
            "name": "Home Energy",
            "icon": "⚡",
            "description": "Gas, electricity, heating oil, LPG and solar export.",
            "entry_mode": "periodic",
            "display_order": 1,
            "active": True,
        },
    )

    items = [
        # (key, label, help_text, display_order, field_name, field_label, field_type, unit, min_value, formula_expr, negative)
        (
            "gas",
            "Natural gas",
            "From your meter or bill, in kWh.",
            1,
            "kwh",
            "Gas used",
            "decimal",
            "kWh",
            "0",
            'kwh * factor("gas_kwh")',
        ),
        (
            "electricity_import",
            "Grid electricity (import)",
            "Units imported from the grid (not solar self-consumption), in kWh.",
            2,
            "kwh",
            "Electricity imported",
            "decimal",
            "kWh",
            "0",
            'kwh * factor("elec_kwh")',
        ),
        (
            "heating_oil",
            "Heating oil (kerosene)",
            "Litres consumed in the period.",
            3,
            "litres",
            "Heating oil",
            "decimal",
            "litres",
            "0",
            'litres * factor("oil_litres")',
        ),
        (
            "lpg",
            "LPG",
            "Litres consumed in the period.",
            4,
            "litres",
            "LPG",
            "decimal",
            "litres",
            "0",
            'litres * factor("lpg_litres")',
        ),
        (
            "solar_export",
            "Solar export credit",
            "kWh exported to the grid — reduces your footprint.",
            5,
            "kwh",
            "Solar export",
            "decimal",
            "kWh",
            "0",
            '-kwh * factor("elec_kwh")',
        ),
    ]

    published_at = timezone.now()

    for (
        item_key,
        label,
        help_text,
        order,
        field_name,
        field_label,
        field_type,
        unit,
        min_val,
        formula_expr,
    ) in items:
        li, _ = LineItem.objects.get_or_create(
            slice=he_slice,
            key=item_key,
            defaults={
                "label": label,
                "help_text": help_text,
                "display_order": order,
                "active": True,
            },
        )

        InputField.objects.get_or_create(
            line_item=li,
            name=field_name,
            defaults={
                "label": field_label,
                "field_type": field_type,
                "unit": unit,
                "min_value": min_val,
                "display_order": 1,
            },
        )

        Formula.objects.get_or_create(
            line_item=li,
            version=1,
            defaults={
                "expression": formula_expr,
                "test_cases": [],
                "published_at": published_at,
            },
        )


def unseed_home_energy(apps, schema_editor):
    Slice = apps.get_model("catalogue", "Slice")
    FactorSet = apps.get_model("catalogue", "FactorSet")
    Slice.objects.filter(key="home_energy").delete()
    FactorSet.objects.filter(name="DESNZ 2024", region="GB").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalogue", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_home_energy, unseed_home_energy),
    ]
