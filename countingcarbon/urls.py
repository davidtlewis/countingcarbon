from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import onboarding

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("accounts.urls")),
    path("onboarding/", onboarding, name="onboarding"),
    path("dashboard/", include("dashboard.urls")),
    path("entries/", include("entries.urls")),
    path("catalogue/", include("catalogue.urls")),
    path(
        "privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"
    ),
    path("", TemplateView.as_view(template_name="hello.html"), name="home"),
]
