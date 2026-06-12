from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "entries"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="entries:home_energy"), name="index"),
    path("home-energy/", views.home_energy, name="home_energy"),
    path("home-energy/add/", views.add_entry, name="add_entry"),
    path("home-energy/cadence/", views.update_cadence, name="update_cadence"),
    path("home-energy/<int:entry_id>/row/", views.entry_row, name="entry_row"),
    path(
        "home-energy/<int:entry_id>/edit-form/",
        views.edit_entry_form,
        name="edit_entry_form",
    ),
    path("home-energy/<int:entry_id>/edit/", views.edit_entry, name="edit_entry"),
]
