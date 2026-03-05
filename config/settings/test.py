"""Test settings — in-memory SQLite, LocMemCache, eager Celery."""

from .base import *  # noqa: F401, F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Suppress logging noise during tests
LOGGING["loggers"] = {  # noqa: F405
    name: {
        "handlers": ["console"],
        "level": "CRITICAL",
        "propagate": False,
    }
    for name in APP_LOGGERS  # noqa: F405
}
