import os

from dotenv import load_dotenv

from .base import *  # noqa: F401, F403

load_dotenv()

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-change-me-before-production",
)

DEBUG = True

ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Skip email verification in dev — avoids needing to copy links from console
ACCOUNT_EMAIL_VERIFICATION = "none"
