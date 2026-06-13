"""
Data migration: add flight factors to DESNZ 2024 and seed the Flights slice.
"""

from django.db import migrations
from django.utils import timezone


def seed_flights(apps, schema_editor):
    FactorSet = apps.get_model("catalogue", "FactorSet")
    Factor = apps.get_model("catalogue", "Factor")
    Slice = apps.get_model("catalogue", "Slice")
    LineItem = apps.get_model("catalogue", "LineItem")
    InputField = apps.get_model("catalogue", "InputField")
    Formula = apps.get_model("catalogue", "Formula")

    fs = FactorSet.objects.get(name="DESNZ 2024", region="GB")

    flight_factors = [
        (
            "flight_short_economy",
            "0.25510",
            "kg CO2e/pax-km",
            "DESNZ 2024, Flights: short-haul economy, with radiative forcing (x1.9)",
        ),
        (
            "flight_long_economy",
            "0.19521",
            "kg CO2e/pax-km",
            "DESNZ 2024, Flights: long-haul economy, with radiative forcing (x1.9)",
        ),
        (
            "flight_long_business",
            "0.42875",
            "kg CO2e/pax-km",
            "DESNZ 2024, Flights: long-haul business class, with radiative forcing (x1.9)",
        ),
    ]
    for key, value, unit, citation in flight_factors:
        Factor.objects.get_or_create(
            factor_set=fs,
            key=key,
            defaults={"value": value, "unit": unit, "citation": citation},
        )

    flights_slice, _ = Slice.objects.get_or_create(
        key="flights",
        defaults={
            "name": "Flights",
            "icon": "✈",
            "description": "Log each flight as a separate event with route, distance and class.",
            "entry_mode": "event",
            "display_order": 3,
            "active": True,
        },
    )

    formula_expr = (
        "passengers * distance_km * (1 + is_return) * "
        'IF(distance_km <= 3700, factor("flight_short_economy"), '
        'IF(cabin_class = 2, factor("flight_long_business"), factor("flight_long_economy")))'
    )

    test_cases = [
        {
            "inputs": {
                "route": "LHR-ATH",
                "passengers": 2,
                "distance_km": 2404,
                "is_return": 1,
                "cabin_class": 1,
            },
            "expected": 2453.04,
            "note": "Matches spreadsheet flight log example",
        },
        {
            "inputs": {
                "route": "LHR-SIN",
                "passengers": 1,
                "distance_km": 10880,
                "is_return": 0,
                "cabin_class": 1,
            },
            "expected": 2123.88,
        },
        {
            "inputs": {
                "route": "LHR-SIN",
                "passengers": 1,
                "distance_km": 10880,
                "is_return": 0,
                "cabin_class": 2,
            },
            "expected": 4664.8,
        },
    ]

    published_at = timezone.now()

    li, _ = LineItem.objects.get_or_create(
        slice=flights_slice,
        key="flight",
        defaults={
            "label": "Flight",
            "help_text": "One-way distance in km; tick return for round trips. Short-haul threshold 3,700 km. Factors include radiative forcing (x1.9).",
            "display_order": 1,
            "active": True,
        },
    )

    input_fields_data = [
        ("route", "Route", "text", "", None, 1, None),
        ("passengers", "Passengers", "integer", "people", "1", 2, None),
        ("distance_km", "Distance one-way", "decimal", "km", "1", 3, None),
        ("is_return", "Return trip", "boolean", "", None, 4, None),
        (
            "cabin_class",
            "Class",
            "choice",
            "",
            None,
            5,
            [{"value": 1, "label": "Economy"}, {"value": 2, "label": "Business"}],
        ),
    ]

    for fname, flabel, ftype, unit, min_val, order, choices in input_fields_data:
        InputField.objects.get_or_create(
            line_item=li,
            name=fname,
            defaults={
                "label": flabel,
                "field_type": ftype,
                "unit": unit,
                "min_value": min_val,
                "choices": choices,
                "display_order": order,
            },
        )

    Formula.objects.get_or_create(
        line_item=li,
        version=1,
        defaults={
            "expression": formula_expr,
            "test_cases": test_cases,
            "published_at": published_at,
        },
    )


def unseed_flights(apps, schema_editor):
    Slice = apps.get_model("catalogue", "Slice")
    Slice.objects.filter(key="flights").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalogue", "0002_seed_home_energy"),
    ]

    operations = [
        migrations.RunPython(seed_flights, unseed_flights),
    ]
