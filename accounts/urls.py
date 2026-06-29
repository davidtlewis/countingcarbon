from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("account/", views.account_detail, name="account"),
    path("account/delete/", views.account_delete, name="account_delete"),
    path("household/", views.household_settings, name="household"),
    path("household/size/", views.household_size, name="household_size"),
    path("household/invite/", views.household_invite, name="household_invite"),
    path("household/leave/", views.household_leave, name="household_leave"),
    path("invite/<str:token>/", views.invite_accept, name="invite_accept"),
]
