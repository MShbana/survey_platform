"""Development settings — mirrors production stack (PostgreSQL + Redis)."""

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS += ["django_extensions"]  # noqa: F405

# PostgreSQL — same engine as production, local defaults
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB", default="survey_platform"),  # noqa: F405
        "USER": env.str("POSTGRES_USER", default="postgres"),  # noqa: F405
        "PASSWORD": env.str("POSTGRES_PASSWORD", default="postgres"),  # noqa: F405
        "HOST": env.str("POSTGRES_HOST", default="localhost"),  # noqa: F405
        "PORT": env.str("POSTGRES_PORT", default="5432"),  # noqa: F405
    }
}

# Redis cache — same backend as production
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env.str("REDIS_URL", default="redis://localhost:6379/1"),  # noqa: F405
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

CORS_ALLOW_ALL_ORIGINS = True

# Dev logging — console only, verbose output
LOGGING["handlers"]["console"]["formatter"] = "simple"  # noqa: F405
LOGGING["handlers"]["console"]["level"] = "DEBUG"  # noqa: F405
LOGGING["loggers"] = {  # noqa: F405
    name: {
        "handlers": ["console"],
        "level": "DEBUG" if name != "django.db.backends" else "INFO",
        "propagate": False,
    }
    for name in APP_LOGGERS  # noqa: F405
}
