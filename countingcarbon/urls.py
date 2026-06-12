from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import onboarding

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("accounts.urls")),
    path("onboarding/", onboarding, name="onboarding"),
    path(
        "privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"
    ),
    path("", TemplateView.as_view(template_name="hello.html"), name="home"),
]
