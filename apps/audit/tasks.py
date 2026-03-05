"""Celery tasks for asynchronous audit log creation.

Provides a single shared task that creates :class:`~apps.audit.models.AuditLog`
records outside the request/response cycle.  This avoids adding database
write latency to user-facing API responses.

Tasks:
    create_audit_log: Create an audit log entry asynchronously.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def create_audit_log(
    user_id, action, model_name, object_id="", details=None, ip_address=None
):
    """Create an :class:`~apps.audit.models.AuditLog` entry.

    This task is dispatched via ``create_audit_log.delay(...)`` from
    signal handlers and view code.  The model import is deferred to
    avoid circular imports at module load time.

    Args:
        user_id (int | None): Primary key of the user who performed
            the action, or ``None`` for anonymous/system actions.
        action (str): The action type (``"create"``, ``"update"``,
            ``"delete"``, ``"view"``, or ``"export"``).
        model_name (str): Name of the affected Django model class
            (e.g. ``"Survey"``).
        object_id (str): Primary key of the affected object as a
            string.  Defaults to ``""``.
        details (dict | None): Optional JSON-serialisable metadata
            about the action.  Defaults to ``{}``.
        ip_address (str | None): Client IP address from the request.
    """
    from .models import AuditLog

    try:
        AuditLog.objects.create(
            user_id=user_id,
            action=action,
            model_name=model_name,
            object_id=str(object_id),
            details=details or {},
            ip_address=ip_address,
        )
        logger.info(
            "Audit log created: action=%s, model=%s, object_id=%s, user_id=%s",
            action,
            model_name,
            object_id,
            user_id,
        )
    except Exception:
        logger.error(
            "Audit log creation failed: action=%s, model=%s, object_id=%s, user_id=%s",
            action,
            model_name,
            object_id,
            user_id,
            exc_info=True,
        )
        raise
