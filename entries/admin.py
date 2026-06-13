from django.contrib import admin

from .models import EventEntry, PeriodicEntry


@admin.register(PeriodicEntry)
class PeriodicEntryAdmin(admin.ModelAdmin):
    list_display = [
        "household",
        "slice_key",
        "period_start",
        "cadence",
        "result_kg",
        "formula_version",
        "logged_by",
        "created_at",
    ]
    list_filter = ["slice_key", "cadence"]
    search_fields = ["household__name", "slice_key", "formula_version"]
    readonly_fields = [
        "household",
        "slice_key",
        "period_start",
        "cadence",
        "inputs",
        "pinned_factors",
        "result_kg",
        "formula_version",
        "logged_by",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (
            "Entry",
            {
                "fields": [
                    "household",
                    "slice_key",
                    "period_start",
                    "cadence",
                    "result_kg",
                    "logged_by",
                ]
            },
        ),
        (
            "Audit trail",
            {
                "fields": ["formula_version", "pinned_factors", "inputs"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]


@admin.register(EventEntry)
class EventEntryAdmin(admin.ModelAdmin):
    list_display = [
        "household",
        "slice_key",
        "event_date",
        "result_kg",
        "formula_version",
        "logged_by",
        "created_at",
    ]
    list_filter = ["slice_key"]
    search_fields = ["household__name", "slice_key", "formula_version"]
    readonly_fields = [
        "household",
        "slice_key",
        "event_date",
        "inputs",
        "pinned_factors",
        "result_kg",
        "formula_version",
        "logged_by",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (
            "Entry",
            {
                "fields": [
                    "household",
                    "slice_key",
                    "event_date",
                    "result_kg",
                    "logged_by",
                ]
            },
        ),
        (
            "Audit trail",
            {
                "fields": ["formula_version", "pinned_factors", "inputs"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {"fields": ["created_at", "updated_at"], "classes": ["collapse"]},
        ),
    ]
