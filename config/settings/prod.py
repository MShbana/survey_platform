"""Production settings — PostgreSQL, Redis, security hardening."""

from .base import *  # noqa: F401, F403

DEBUG = False

# Database — all values from environment
DATABASES = {
    "default": {
        "ENGINE": env.str("POSTGRES_ENGINE", default="django.db.backends.postgresql"),  # noqa: F405
        "NAME": env.str("POSTGRES_DB"),  # noqa: F405
        "USER": env.str("POSTGRES_USER"),  # noqa: F405
        "PASSWORD": env.str("POSTGRES_PASSWORD"),  # noqa: F405
        "HOST": env.str("POSTGRES_HOST"),  # noqa: F405
        "PORT": env.str("POSTGRES_PORT", default="5432"),  # noqa: F405
        "CONN_MAX_AGE": 60,
    }
}

# Redis cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env.str("REDIS_URL"),  # noqa: F405
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# CORS
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)  # noqa: F405

# Security
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Production logging — console + rotating file
_LOG_DIR = BASE_DIR / "logs"  # noqa: F405

LOGGING["handlers"]["console"]["formatter"] = "verbose"  # noqa: F405
LOGGING["handlers"]["console"]["level"] = "WARNING"  # noqa: F405
LOGGING["handlers"]["file"] = {  # noqa: F405
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(_LOG_DIR / "survey_platform.log"),
    "maxBytes": 10 * 1024 * 1024,  # 10 MB
    "backupCount": 5,
    "formatter": "verbose",
    "level": "INFO",
}
LOGGING["loggers"] = {  # noqa: F405
    name: {
        "handlers": ["console", "file"],
        "level": "WARNING" if name == "django.db.backends" else "INFO",
        "propagate": False,
    }
    for name in APP_LOGGERS  # noqa: F405
}
