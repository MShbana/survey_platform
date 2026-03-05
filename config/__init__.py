"""Config package initialiser — ensures Celery is loaded at Django startup.

Importing ``celery_app`` here guarantees that the Celery application
is created and configured (via ``config.celery``) whenever Django
initialises, which is required for ``@shared_task`` decorators to
discover the app instance.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
