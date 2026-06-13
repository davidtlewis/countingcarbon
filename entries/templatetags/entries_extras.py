from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    """Return d[key], or '' if missing/not a dict. Supports JSON field access in templates."""
    if not isinstance(d, dict):
        return ""
    val = d.get(key)
    return "" if val is None else val
