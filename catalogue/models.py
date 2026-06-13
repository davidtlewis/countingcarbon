from decimal import Decimal

from django.db import models
from django.db.models import Q


class Slice(models.Model):
    ENTRY_MODES = [
        ("periodic", "Periodic"),
        ("event", "Event"),
        ("annual_estimate", "Annual estimate"),
    ]

    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    icon = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    entry_mode = models.CharField(max_length=20, choices=ENTRY_MODES)
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class LineItem(models.Model):
    slice = models.ForeignKey(
        Slice, on_delete=models.CASCADE, related_name="line_items"
    )
    key = models.CharField(max_length=100)
    label = models.CharField(max_length=200)
    help_text = models.TextField(blank=True)
    group = models.CharField(max_length=100, blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("slice", "key")]
        ordering = ["display_order", "key"]

    def __str__(self):
        return f"{self.slice.key} / {self.key}"

    def published_formula(self):
        """Return the latest published Formula for this line item, or None."""
        return (
            self.formulas.filter(published_at__isnull=False)
            .order_by("-version")
            .first()
        )


class InputField(models.Model):
    FIELD_TYPES = [
        ("decimal", "Decimal"),
        ("integer", "Integer"),
        ("boolean", "Boolean"),
        ("choice", "Choice"),
        ("text", "Text"),
    ]

    line_item = models.ForeignKey(
        LineItem, on_delete=models.CASCADE, related_name="input_fields"
    )
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    unit = models.CharField(max_length=50, blank=True)
    min_value = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    choices = models.JSONField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("line_item", "name")]
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.line_item} / {self.name}"


class Formula(models.Model):
    line_item = models.ForeignKey(
        LineItem, on_delete=models.CASCADE, related_name="formulas"
    )
    expression = models.TextField()
    version = models.PositiveIntegerField(default=1)
    test_cases = models.JSONField(default=list)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("line_item", "version")]
        ordering = ["version"]

    def __str__(self):
        status = "published" if self.published_at else "draft"
        return f"{self.line_item} v{self.version} ({status})"

    @property
    def is_published(self):
        return self.published_at is not None


class FactorSet(models.Model):
    name = models.CharField(max_length=200)
    source = models.TextField(blank=True)
    licence = models.CharField(max_length=200, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    region = models.CharField(max_length=10, default="GB")

    class Meta:
        ordering = ["valid_from", "name"]

    def __str__(self):
        return f"{self.name} ({self.region}, from {self.valid_from})"


class Factor(models.Model):
    factor_set = models.ForeignKey(
        FactorSet, on_delete=models.CASCADE, related_name="factors"
    )
    key = models.CharField(max_length=100)
    value = models.DecimalField(max_digits=14, decimal_places=6)
    unit = models.CharField(max_length=100, blank=True)
    citation = models.TextField(blank=True)

    class Meta:
        unique_together = [("factor_set", "key")]
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value} ({self.factor_set.name})"


class BandTable(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    def lookup(self, value: Decimal) -> Decimal:
        """Return the band value for value (step function — highest lower_bound ≤ value wins)."""
        band = (
            self.bands.filter(lower_bound__lte=value).order_by("-lower_bound").first()
        )
        if band is None:
            raise ValueError(f"No band found in '{self.name}' for value {value}")
        return band.value


class Band(models.Model):
    band_table = models.ForeignKey(
        BandTable, on_delete=models.CASCADE, related_name="bands"
    )
    lower_bound = models.DecimalField(max_digits=14, decimal_places=4)
    value = models.DecimalField(max_digits=14, decimal_places=6)

    class Meta:
        unique_together = [("band_table", "lower_bound")]
        ordering = ["lower_bound"]

    def __str__(self):
        return f"{self.band_table.name} [{self.lower_bound}] = {self.value}"


def resolve_factors(keys: list, as_of_date, region: str = "GB") -> dict:
    """
    Return {factor_key: Decimal} for each key in `keys`, using factor sets
    valid on `as_of_date` in `region`.

    Raises ValueError if a key is missing from all valid sets, or if two
    simultaneously-valid sets both define the same key (ambiguity).
    """
    valid_sets = FactorSet.objects.filter(
        region=region,
        valid_from__lte=as_of_date,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of_date))

    factors = Factor.objects.filter(
        factor_set__in=valid_sets,
        key__in=keys,
    ).select_related("factor_set")

    result = {}
    seen = {}  # key → factor_set name for ambiguity detection
    for f in factors:
        if f.key in seen:
            raise ValueError(
                f"Factor '{f.key}' is defined in multiple simultaneously-valid "
                f"factor sets: '{seen[f.key]}' and '{f.factor_set.name}'. "
                "Add valid_to dates to disambiguate."
            )
        result[f.key] = f.value
        seen[f.key] = f.factor_set.name

    missing = set(keys) - set(result)
    if missing:
        raise ValueError(
            f"Factor key(s) not found in any valid factor set on {as_of_date}: "
            f"{sorted(missing)}"
        )

    return result
