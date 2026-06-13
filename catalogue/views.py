from django.shortcuts import render

from .models import FactorSet, Slice


def browse(request):
    slices = (
        Slice.objects.filter(active=True)
        .prefetch_related(
            "line_items",
            "line_items__input_fields",
            "line_items__formulas",
        )
        .order_by("display_order", "name")
    )
    from django.db.models import Prefetch

    from .models import Factor

    factor_sets = FactorSet.objects.prefetch_related(
        Prefetch("factors", queryset=Factor.objects.order_by("key"))
    ).order_by("name", "valid_from")
    return render(
        request,
        "catalogue/browse.html",
        {"slices": slices, "factor_sets": factor_sets},
    )
