from django.db.models import Prefetch
from django.shortcuts import render

from .models import Factor, FactorSet, Formula, InputField, LineItem, Slice


def browse(request):
    slices = (
        Slice.objects.filter(active=True)
        .prefetch_related(
            Prefetch(
                "line_items",
                queryset=LineItem.objects.filter(active=True).order_by(
                    "display_order", "key"
                ),
            ),
            Prefetch(
                "line_items__input_fields",
                queryset=InputField.objects.order_by("display_order"),
            ),
            Prefetch(
                "line_items__formulas",
                queryset=Formula.objects.order_by("-version"),
            ),
        )
        .order_by("display_order", "name")
    )
    factor_sets = FactorSet.objects.prefetch_related(
        Prefetch("factors", queryset=Factor.objects.order_by("key"))
    ).order_by("name", "valid_from")
    return render(
        request,
        "catalogue/browse.html",
        {"slices": slices, "factor_sets": factor_sets},
    )
