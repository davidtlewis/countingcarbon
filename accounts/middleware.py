from django.shortcuts import redirect

# Paths that don't need a household (auth flows, admin, static assets)
_ONBOARDING_EXEMPT_PREFIXES = (
    "/accounts/",
    "/admin/",
    "/onboarding/",
    "/privacy/",
    "/static/",
    "/favicon.ico",
)


class HouseholdOnboardingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not any(
            request.path.startswith(p) for p in _ONBOARDING_EXEMPT_PREFIXES
        ):
            if not hasattr(request.user, "membership"):
                return redirect("accounts:onboarding")
        return self.get_response(request)
