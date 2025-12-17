import os

from dotenv import load_dotenv

from .base import *  # noqa

load_dotenv()

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "test-fallback-key")
