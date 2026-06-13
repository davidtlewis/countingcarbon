"""
End-to-end flow tests: model creation → HTTP → response content.
Covers the T8 acceptance criterion:
  register → household → gas entry → dashboard shows correct annualised figure.
"""

import pytest

from tests.factories import HouseholdFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
class TestEntryToDashboard:
    """
    Full flow: authenticated user with a household enters a gas reading,
    then the dashboard shows the correctly annualised figure.

    1000 kWh gas × factor 0.18286 = 182.86 kg/month
    Annualised (monthly × 12)     = 2194.32 kg/year → displayed as "2194"

    Phase 2: form field names are namespaced as '{line_item_key}__{field_name}'.
    """

    def test_gas_entry_appears_annualised_on_dashboard(self, auth_client):
        user = UserFactory()
        household = HouseholdFactory()
        MembershipFactory(user=user, household=household)
        client = auth_client(user)

        response = client.post(
            "/entries/home-energy/add/",
            {"period_month": "2025-01", "gas__kwh": "1000"},
        )
        assert response.status_code == 200

        response = client.get("/dashboard/")
        assert response.status_code == 200
        content = response.content.decode()
        # 182.86 × 12 = 2194.32 → floatformat:0 → "2194"
        assert "2194" in content

    def test_dashboard_shows_no_data_without_entries(self, auth_client):
        user = UserFactory()
        household = HouseholdFactory()
        MembershipFactory(user=user, household=household)
        client = auth_client(user)

        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert b"No data" in response.content

    def test_chart_data_endpoint_returns_json(self, auth_client):
        user = UserFactory()
        household = HouseholdFactory()
        MembershipFactory(user=user, household=household)
        client = auth_client(user)

        client.post(
            "/entries/home-energy/add/",
            {"period_month": "2025-01", "gas__kwh": "500"},
        )

        response = client.get("/dashboard/chart-data/")
        assert response.status_code == 200
        data = response.json()
        assert "labels" in data
        assert "household" in data
        assert "benchmarks" in data

    def test_chart_gap_for_skipped_month(self, auth_client):
        user = UserFactory()
        household = HouseholdFactory()
        MembershipFactory(user=user, household=household)
        client = auth_client(user)

        # Enter January and March — February is a gap
        client.post(
            "/entries/home-energy/add/", {"period_month": "2025-01", "gas__kwh": "300"}
        )
        client.post(
            "/entries/home-energy/add/", {"period_month": "2025-03", "gas__kwh": "250"}
        )

        response = client.get("/dashboard/chart-data/")
        data = response.json()
        feb_idx = data["labels"].index("Feb 2025")
        assert data["household"][feb_idx] is None

    def test_benchmark_scales_by_member_count(self, auth_client):
        user1 = UserFactory()
        user2 = UserFactory()
        household = HouseholdFactory()
        MembershipFactory(user=user1, household=household)
        MembershipFactory(user=user2, household=household)
        client = auth_client(user1)

        client.post(
            "/entries/home-energy/add/", {"period_month": "2025-01", "gas__kwh": "100"}
        )

        response = client.get("/dashboard/")
        content = response.content.decode()
        # UK average: 10,000 kg/person × 2 members = 20,000 kg
        assert "20,000" in content or "20000" in content


@pytest.mark.django_db
class TestOnboarding:
    def test_unauthenticated_redirected_from_entries(self):
        from django.test import Client

        response = Client().get("/entries/")
        assert response.status_code == 302

    def test_user_without_household_redirected_to_onboarding(self, auth_client):
        user = UserFactory()
        client = auth_client(user)
        response = client.get("/dashboard/")
        assert response.status_code == 302
        assert response["Location"] == "/onboarding/"

    def test_onboarding_creates_household(self, auth_client):
        from accounts.models import HouseholdMembership

        user = UserFactory()
        client = auth_client(user)
        response = client.post("/onboarding/", {"name": "My Home"}, follow=True)
        assert response.status_code == 200
        assert HouseholdMembership.objects.filter(user=user).exists()
