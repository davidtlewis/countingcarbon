"""
Catalogue admin.

Key features (T13):
- Monospace textarea for Formula.expression
- "Validate test cases" action — runs all test cases, reports pass/fail
- "Publish" action — blocked if any test case fails
- Factor set import: upload JSON seed file → preview diff → confirm
- Formula audit trail: read-only version history on LineItem detail
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO

from django import forms
from django.contrib import admin, messages
from django.core.management import call_command
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

from .models import (
    Band,
    BandTable,
    Factor,
    FactorSet,
    Formula,
    InputField,
    LineItem,
    Slice,
    resolve_factors,
)

# ── Widgets ────────────────────────────────────────────────────────────────────


class MonospaceTextarea(forms.Textarea):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs.update(
            {
                "style": "font-family: monospace; font-size: 0.9em; width: 100%;",
                "rows": 4,
                "spellcheck": "false",
            }
        )


# ── Formula test runner ────────────────────────────────────────────────────────


def _run_formula_tests(formula: Formula) -> list[dict]:
    """
    Execute all test_cases for a Formula. Returns a list of result dicts:
      {"passed": bool, "expected": Decimal, "got": Decimal|None, "note": str, "error": str}
    """
    from engine.dsl import collect_factor_keys, eval_expression, parse

    results = []
    for tc in formula.test_cases:
        raw_inputs = tc.get("inputs", {})
        expected = Decimal(str(tc.get("expected", 0)))
        note = tc.get("note", "")

        try:
            ast = parse(formula.expression)
            factor_keys = list(collect_factor_keys(ast))
            factors = resolve_factors(factor_keys, date.today()) if factor_keys else {}
            context = {
                k: Decimal(str(v))
                for k, v in raw_inputs.items()
                if not isinstance(v, str)
            }
            got = eval_expression(formula.expression, context, dict(factors))
            passed = abs(got - expected) <= Decimal("0.01")
            results.append(
                {"passed": passed, "expected": expected, "got": got, "note": note}
            )
        except Exception as exc:
            results.append(
                {
                    "passed": False,
                    "expected": expected,
                    "got": None,
                    "note": note,
                    "error": str(exc),
                }
            )

    return results


# ── Admin actions ─────────────────────────────────────────────────────────────


@admin.action(description="Validate & run test cases")
def run_test_cases(modeladmin, request, queryset):
    all_pass = True
    for formula in queryset:
        if not formula.test_cases:
            messages.warning(request, f"{formula}: no test cases defined.")
            continue
        results = _run_formula_tests(formula)
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        if passed == total:
            messages.success(request, f"{formula}: {passed}/{total} test cases PASSED.")
        else:
            all_pass = False
            for i, r in enumerate(results, 1):
                if not r["passed"]:
                    err = r.get("error", f"got {r['got']}, expected {r['expected']}")
                    messages.error(request, f"{formula} case {i}: FAILED — {err}")
    if all_pass and queryset.count() > 0:
        messages.success(request, "All selected formulas passed their test cases.")


@admin.action(description="Publish (blocked if any test case fails)")
def publish_formulas(modeladmin, request, queryset):
    published_count = 0
    for formula in queryset:
        if formula.is_published:
            messages.info(request, f"{formula}: already published, skipped.")
            continue

        if formula.test_cases:
            results = _run_formula_tests(formula)
            failures = [r for r in results if not r["passed"]]
            if failures:
                for r in failures:
                    err = r.get("error", f"got {r['got']}, expected {r['expected']}")
                    messages.error(
                        request,
                        f"Cannot publish {formula}: test case failed — {err}",
                    )
                continue

        formula.published_at = timezone.now()
        formula.save(update_fields=["published_at"])
        published_count += 1

    if published_count:
        messages.success(request, f"Published {published_count} formula(s).")


# ── Form for FormulaAdmin ─────────────────────────────────────────────────────


class FormulaForm(forms.ModelForm):
    class Meta:
        model = Formula
        fields = "__all__"
        widgets = {
            "expression": MonospaceTextarea(),
        }


# ── Inlines ───────────────────────────────────────────────────────────────────


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


class FormulaInline(admin.StackedInline):
    model = Formula
    extra = 0
    form = FormulaForm
    readonly_fields = ["version", "published_at", "is_published"]
    fields = ["version", "expression", "test_cases", "is_published", "published_at"]

    def is_published(self, obj):
        return obj.is_published

    is_published.boolean = True


# ── LineItem admin ─────────────────────────────────────────────────────────────


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "slice", "display_order", "active", "formula_summary"]
    list_filter = ["slice", "active"]
    inlines = [InputFieldInline, FormulaInline]

    def formula_summary(self, obj):
        f = obj.published_formula()
        if f:
            return f"v{f.version} published"
        return "no published formula"

    formula_summary.short_description = "Formula"


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    fields = ["key", "label", "display_order", "active"]
    show_change_link = True


# ── Slice admin ────────────────────────────────────────────────────────────────


@admin.register(Slice)
class SliceAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "entry_mode", "display_order", "active"]
    list_filter = ["entry_mode", "active"]
    inlines = [LineItemInline]


# ── FactorSet admin (with JSON import) ────────────────────────────────────────


class FactorInline(admin.TabularInline):
    model = Factor
    extra = 1
    fields = ["key", "value", "unit", "citation"]


@admin.register(FactorSet)
class FactorSetAdmin(admin.ModelAdmin):
    list_display = ["name", "region", "valid_from", "valid_to", "factor_count"]
    inlines = [FactorInline]

    def factor_count(self, obj):
        return obj.factors.count()

    factor_count.short_description = "Factors"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "import-json/",
                self.admin_site.admin_view(self._import_view),
                name="catalogue_factorset_import",
            )
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["import_url_name"] = "admin:catalogue_factorset_import"
        return super().changelist_view(request, extra_context=extra_context)

    def _import_view(self, request):
        context = {
            **self.admin_site.each_context(request),
            "title": "Import factor set from JSON",
            "done": False,
            "error": None,
            "diff_lines": None,
            "change_count": 0,
            "session_key": "import_json_content",
        }

        if request.method == "POST":
            if request.POST.get("confirmed"):
                content = request.session.pop("import_json_content", None)
                if not content:
                    context["error"] = "Session expired — please upload the file again."
                    return TemplateResponse(
                        request,
                        "admin/catalogue/factorset_import.html",
                        context,
                    )
                change_count, err = self._run_import(content, dry_run=False)
                if err:
                    context["error"] = err
                else:
                    context["done"] = True
                    context["change_count"] = change_count
                    messages.success(
                        request, f"Import complete — {change_count} change(s) applied."
                    )
            else:
                uploaded = request.FILES.get("json_file")
                if not uploaded:
                    context["error"] = "Please select a JSON file."
                    return TemplateResponse(
                        request,
                        "admin/catalogue/factorset_import.html",
                        context,
                    )
                try:
                    content = uploaded.read().decode("utf-8")
                    json.loads(content)  # validate JSON
                except Exception as exc:
                    context["error"] = f"Invalid JSON: {exc}"
                    return TemplateResponse(
                        request,
                        "admin/catalogue/factorset_import.html",
                        context,
                    )

                lines, err = self._dry_run_import(content)
                if err:
                    context["error"] = err
                else:
                    request.session["import_json_content"] = content
                    context["diff_lines"] = lines
                    context["change_count"] = len(lines)

        return TemplateResponse(
            request, "admin/catalogue/factorset_import.html", context
        )

    def _dry_run_import(self, content: str) -> tuple[list[str], str | None]:
        """Run load_catalogue --dry-run on content. Returns (lines, error)."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                f.write(content)
                tmppath = f.name
            out = StringIO()
            call_command(
                "load_catalogue", tmppath, "--dry-run", stdout=out, verbosity=2
            )
            raw = out.getvalue()
            lines = [ln for ln in raw.splitlines() if ln.strip().startswith("[")]
            return lines, None
        except Exception as exc:
            return [], str(exc)

    def _run_import(
        self, content: str, dry_run: bool = False
    ) -> tuple[int, str | None]:
        """Run load_catalogue on content. Returns (change_count, error)."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                f.write(content)
                tmppath = f.name
            out = StringIO()
            args = ["load_catalogue", tmppath]
            if dry_run:
                args.append("--dry-run")
            call_command(*args, stdout=out, verbosity=2)
            raw = out.getvalue()
            count = sum(1 for ln in raw.splitlines() if ln.strip().startswith("["))
            return count, None
        except Exception as exc:
            return 0, str(exc)


# ── Factor admin ───────────────────────────────────────────────────────────────


@admin.register(Factor)
class FactorAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "unit", "factor_set"]
    list_filter = ["factor_set"]
    search_fields = ["key", "citation"]


# ── Formula admin ──────────────────────────────────────────────────────────────


@admin.register(Formula)
class FormulaAdmin(admin.ModelAdmin):
    form = FormulaForm
    list_display = [
        "line_item",
        "version",
        "is_published",
        "published_at",
        "test_case_count",
    ]
    list_filter = ["published_at", "line_item__slice"]
    readonly_fields = ["version", "published_at"]
    actions = [run_test_cases, publish_formulas]

    def test_case_count(self, obj):
        return len(obj.test_cases)

    test_case_count.short_description = "Test cases"


# ── BandTable admin ────────────────────────────────────────────────────────────


class BandInline(admin.TabularInline):
    model = Band
    extra = 1
    fields = ["lower_bound", "value"]


@admin.register(BandTable)
class BandTableAdmin(admin.ModelAdmin):
    inlines = [BandInline]
