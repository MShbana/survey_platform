"""Audit logging models for tracking user actions across the platform.

This module defines the :class:`AuditLog` model which records all
significant user actions (create, update, delete, view, export) on
tracked resources.  Entries are created asynchronously via Celery
tasks and Django signals to avoid blocking request processing.

Models:
    AuditLog: Immutable record of a single auditable user action.
"""

from django.conf import settings
from django.db import models

class AuditLog(models.Model):
    """Immutable record of a single auditable user action.

    Each entry captures who performed the action, what they did, which
    object was affected, the client IP address, and an optional details
    payload for action-specific metadata (e.g. ``{"scope": "list"}``
    for list views, ``{"format": "csv"}`` for exports).

    Records are created via :func:`~apps.audit.tasks.create_audit_log`
    (a Celery shared task) and are never updated or deleted during
    normal operation.

    Attributes:
        user (User | None): FK to the user who performed the action.
            ``SET_NULL`` on user deletion to preserve the audit trail.
        action (str): One of :class:`Action` choices (create, update,
            delete, view, export).
        model_name (str): Name of the affected Django model class
            (e.g. ``"Survey"``, ``"SurveyResponse"``).
        object_id (str): Primary key of the affected object as a string.
        details (dict): Arbitrary JSON metadata about the action.
        ip_address (str | None): Client IP address from the request.
        timestamp (datetime): Auto-set creation timestamp.

    Meta:
        db_table: ``audit_logs``
        ordering: ``["-timestamp"]`` (newest first)
        indexes: ``timestamp``, ``user``, ``(model_name, object_id)``
    """

    class Action(models.TextChoices):
        """Enumeration of auditable action types.

        Members:
            CREATE: A new object was created.
            UPDATE: An existing object was modified.
            DELETE: An object was deleted.
            VIEW: An object or list was viewed.
        """

        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        VIEW = "view", "View"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["user"]),
            models.Index(fields=["model_name", "object_id"]),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        """Return ``"user action model_name:object_id"``."""
        return f"{self.user} {self.action} {self.model_name}:{self.object_id}"
