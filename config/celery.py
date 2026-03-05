"""Celery application configuration for the Survey Platform.

Creates and configures the Celery app instance using Django settings
(all settings prefixed with ``CELERY_``).  Task modules are auto-
discovered from all installed Django apps.

The app instance is imported in ``config/__init__.py`` to ensure
Celery is initialised when Django starts.

Attributes:
    app (Celery): The configured Celery application instance.
"""

import logging
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("survey_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger(__name__)
logger.info("Celery app configured for survey_platform")
