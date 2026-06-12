from datetime import date

from django.conf import settings
from django.db import models

from accounts.models import Household

CADENCE_CHOICES = [
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("annual", "Annual"),
]


class HouseholdSlicePreference(models.Model):
    """Stores per-household cadence choice for each slice (default: monthly)."""

    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="slice_preferences",
    )
    slice_key = models.CharField(max_length=100)
    cadence = models.CharField(
        max_length=20, choices=CADENCE_CHOICES, default="monthly"
    )

    class Meta:
        unique_together = [("household", "slice_key")]

    def __str__(self):
        return f"{self.household} / {self.slice_key}: {self.cadence}"


class PeriodicEntry(models.Model):
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="periodic_entries",
    )
    slice_key = models.CharField(max_length=100)
    period_start = models.DateField()
    cadence = models.CharField(max_length=20, choices=CADENCE_CHOICES)
    inputs = models.JSONField()
    pinned_factors = models.JSONField()
    result_kg = models.DecimalField(max_digits=12, decimal_places=4)
    formula_version = models.CharField(max_length=64)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="logged_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("household", "slice_key", "period_start")]
        ordering = ["-period_start"]

    def __str__(self):
        return f"{self.household} / {self.slice_key} / {self.period_label}"

    @property
    def period_label(self) -> str:
        if self.cadence == "monthly":
            return self.period_start.strftime("%B %Y")
        if self.cadence == "quarterly":
            q = (self.period_start.month - 1) // 3 + 1
            return f"Q{q} {self.period_start.year}"
        return str(self.period_start.year)

    @property
    def period_end(self) -> date:
        """Exclusive end date of this period (first day of the next period)."""
        if self.cadence == "monthly":
            y, m = self.period_start.year, self.period_start.month
            return date(y + (m // 12), m % 12 + 1, 1)
        if self.cadence == "quarterly":
            m = self.period_start.month + 3
            return date(self.period_start.year + (m > 12), (m - 1) % 12 + 1, 1)
        return date(self.period_start.year + 1, 1, 1)
