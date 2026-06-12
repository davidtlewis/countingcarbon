"""
Hard-coded Phase 1 slice definitions.
In Phase 2 these are replaced by admin-defined catalogue entries, but the
shape of this structure intentionally mirrors the catalogue model so views
and the engine need no changes.
"""

HOME_ENERGY_SLICE = {
    "key": "home_energy",
    "label": "Home Energy",
    "items": [
        {
            "key": "gas_kwh",
            "label": "Natural gas",
            "unit": "kWh",
            "factor": 0.18286,
            "factor_source": "DESNZ 2024, Fuels: natural gas (gross CV)",
            "negative": False,
        },
        {
            "key": "elec_kwh",
            "label": "Grid electricity (import)",
            "unit": "kWh",
            "factor": 0.20707,
            "factor_source": "DESNZ 2024, UK electricity: generation",
            "negative": False,
        },
        {
            "key": "oil_litres",
            "label": "Heating oil (kerosene)",
            "unit": "litres",
            "factor": 2.5202,
            "factor_source": "DESNZ 2024, Fuels: burning oil (kerosene)",
            "negative": False,
        },
        {
            "key": "lpg_litres",
            "label": "LPG",
            "unit": "litres",
            "factor": 1.5534,
            "factor_source": "DESNZ 2024, Fuels: LPG (average)",
            "negative": False,
        },
        {
            "key": "solar_export_kwh",
            "label": "Solar export credit",
            "unit": "kWh",
            "factor": 0.20707,
            "factor_source": "DESNZ 2024, UK electricity: generation",
            "negative": True,
        },
    ],
}

SLICES = {s["key"]: s for s in [HOME_ENERGY_SLICE]}
