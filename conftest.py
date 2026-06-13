import pytest
from django.test import Client

# allauth's backend is the only one in AUTHENTICATION_BACKENDS.
# Specify it explicitly so force_login works reliably in tests.
_ALLAUTH_BACKEND = "allauth.account.auth_backends.AuthenticationBackend"


@pytest.fixture
def auth_client():
    """Return a function(user) → authenticated Client (fresh instance each call)."""

    def _make(user):
        c = Client()
        c.force_login(user, backend=_ALLAUTH_BACKEND)
        return c

    return _make
