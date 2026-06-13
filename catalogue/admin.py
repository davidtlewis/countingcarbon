from django.contrib import admin

from .models import (
    Band,
    BandTable,
    Factor,
    FactorSet,
    Formula,
    InputField,
    LineItem,
    Slice,
)


class InputFieldInline(admin.TabularInline):
    model = InputField
    extra = 1
    fields = [
        "name",
        "label",
        "field_type",
        "unit",
        "min_value",
        "choices",
        "display_order",
    ]


class FormulaInline(admin.TabularInline):
    model = Formula
    extra = 0
    fields = ["expression", "version", "test_cases", "published_at"]
    readonly_fields = ["version"]


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "slice", "display_order", "active"]
    list_filter = ["slice", "active"]
    inlines = [InputFieldInline, FormulaInline]


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    fields = ["key", "label", "display_order", "active"]
    show_change_link = True


@admin.register(Slice)
class SliceAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "entry_mode", "display_order", "active"]
    list_filter = ["entry_mode", "active"]
    inlines = [LineItemInline]


class FactorInline(admin.TabularInline):
    model = Factor
    extra = 1
    fields = ["key", "value", "unit", "citation"]


@admin.register(FactorSet)
class FactorSetAdmin(admin.ModelAdmin):
    list_display = ["name", "region", "valid_from", "valid_to"]
    inlines = [FactorInline]


@admin.register(Factor)
class FactorAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "unit", "factor_set"]
    list_filter = ["factor_set"]
    search_fields = ["key", "citation"]


class BandInline(admin.TabularInline):
    model = Band
    extra = 1
    fields = ["lower_bound", "value"]


@admin.register(BandTable)
class BandTableAdmin(admin.ModelAdmin):
    inlines = [BandInline]


@admin.register(Formula)
class FormulaAdmin(admin.ModelAdmin):
    list_display = ["line_item", "version", "is_published", "published_at"]
    list_filter = ["published_at"]
    readonly_fields = ["version"]
