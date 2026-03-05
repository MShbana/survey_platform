"""Django app configuration for the audit app.

Classes:
    AuditConfig: Registers signal handlers on application startup.
"""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """App configuration for the audit logging system.

    Connects :mod:`apps.audit.signals` on startup so that
    ``post_save`` and ``post_delete`` receivers are registered
    for all tracked models.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"

    def ready(self):
        """Import signal handlers to connect receivers at startup."""
        import apps.audit.signals  # noqa: F401
