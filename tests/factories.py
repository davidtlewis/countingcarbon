import factory
from django.contrib.auth import get_user_model

from accounts.models import Household, HouseholdInvitation, HouseholdMembership
from entries.models import HouseholdSlicePreference, PeriodicEntry

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or "testpassword123")
        if create:
            obj.save(update_fields=["password"])


class HouseholdFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Household

    name = factory.Sequence(lambda n: f"Test Household {n}")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HouseholdMembership

    user = factory.SubFactory(UserFactory)
    household = factory.SubFactory(HouseholdFactory)


class InvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HouseholdInvitation

    household = factory.SubFactory(HouseholdFactory)
    email = factory.Sequence(lambda n: f"invited{n}@example.com")
    invited_by = factory.SubFactory(UserFactory)


class SlicePreferenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HouseholdSlicePreference

    household = factory.SubFactory(HouseholdFactory)
    slice_key = "home_energy"
    cadence = "monthly"


class PeriodicEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PeriodicEntry

    household = factory.SubFactory(HouseholdFactory)
    slice_key = "home_energy"
    period_start = factory.Faker("date_object")
    cadence = "monthly"
    inputs = factory.LazyAttribute(lambda _: {"gas_kwh": "1000"})
    pinned_factors = factory.LazyAttribute(
        lambda _: {
            "gas_kwh": "0.18286",
            "elec_kwh": "0.20707",
            "oil_litres": "2.5202",
            "lpg_litres": "1.5534",
            "solar_export_kwh": "0.20707",
        }
    )
    result_kg = factory.LazyAttribute(lambda _: "182.8600")
    formula_version = "abcd1234efgh5678"
    logged_by = None
