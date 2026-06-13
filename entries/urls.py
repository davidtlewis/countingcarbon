from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "entries"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="entries:home_energy"), name="index"),
    # Home Energy (periodic)
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
    # Transport (periodic)
    path("transport/", views.transport, name="transport"),
    path("transport/add/", views.transport_add, name="transport_add"),
    path("transport/cadence/", views.transport_cadence, name="transport_cadence"),
    path("transport/<int:entry_id>/row/", views.transport_row, name="transport_row"),
    path(
        "transport/<int:entry_id>/edit-form/",
        views.transport_edit_form,
        name="transport_edit_form",
    ),
    path("transport/<int:entry_id>/edit/", views.transport_edit, name="transport_edit"),
    # Flights (event)
    path("flights/", views.flights, name="flights"),
    path("flights/add/", views.add_flight, name="add_flight"),
    path("flights/<int:entry_id>/row/", views.flight_row, name="flight_row"),
    path(
        "flights/<int:entry_id>/edit-form/",
        views.edit_flight_form,
        name="edit_flight_form",
    ),
    path("flights/<int:entry_id>/edit/", views.edit_flight, name="edit_flight"),
    path("flights/<int:entry_id>/delete/", views.delete_flight, name="delete_flight"),
    # Breakdowns (transparency)
    path(
        "breakdown/periodic/<int:entry_id>/",
        views.breakdown_periodic,
        name="breakdown_periodic",
    ),
    path(
        "breakdown/event/<int:entry_id>/",
        views.breakdown_event,
        name="breakdown_event",
    ),
    path(
        "breakdown/estimate/<int:entry_id>/",
        views.breakdown_estimate,
        name="breakdown_estimate",
    ),
    # Food (annual estimate)
    path("food/", views.food, name="food"),
    path("food/save/", views.food_save, name="food_save"),
    # Purchases (annual estimate)
    path("purchases/", views.purchases, name="purchases"),
    path("purchases/save/", views.purchases_save, name="purchases_save"),
]
