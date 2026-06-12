from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    """Return d[key], or '' if missing. Supports JSON field access in templates."""
    if d is None:
        return ""
    val = d.get(key)
    return "" if val is None else val
