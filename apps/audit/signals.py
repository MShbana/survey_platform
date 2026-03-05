"""Django signal receivers for automatic audit logging.

Listens to :data:`~django.db.models.signals.post_save` and
:data:`~django.db.models.signals.post_delete` signals for a set of
tracked models and dispatches asynchronous Celery tasks to create
:class:`~apps.audit.models.AuditLog` entries.

Tracked models:
    - :class:`~apps.surveys.models.Survey`
    - :class:`~apps.surveys.models.Section`
    - :class:`~apps.surveys.models.Field`
    - :class:`~apps.surveys.models.ConditionalRule`
    - :class:`~apps.surveys.models.FieldDependency`
    - :class:`~apps.responses.models.SurveyResponse`

Note:
    Signal handlers are connected when the ``AuditConfig.ready()``
    method imports this module during Django startup.
"""

import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from apps.surveys.models import Survey, Section, Field, ConditionalRule, FieldDependency
from apps.responses.models import SurveyResponse

from .middleware import get_client_ip, get_current_user
from .tasks import create_audit_log

logger = logging.getLogger(__name__)


_TRACKED_MODELS = [Survey, Section, Field, ConditionalRule, FieldDependency, SurveyResponse]


@receiver(post_save)
def audit_post_save(sender, instance, created, **kwargs):
    """Log create/update actions when a tracked model instance is saved.

    Determines the action type based on the ``created`` flag and
    dispatches a Celery task with the current user and IP from
    thread-local storage.

    Args:
        sender (type): The model class that sent the signal.
        instance (Model): The saved model instance.
        created (bool): ``True`` if the instance was just created,
            ``False`` if it was updated.
        **kwargs: Additional signal keyword arguments (unused).
    """
    if sender not in _TRACKED_MODELS:
        return

    current_user = get_current_user()
    user_id = current_user.id if current_user else None
    ip = get_client_ip()

    action = "create" if created else "update"
    logger.debug(
        "Signal dispatched: action=%s, model=%s, pk=%s, user_id=%s",
        action, sender.__name__, instance.pk, user_id,
    )
    create_audit_log.delay(
        user_id=user_id,
        action=action,
        model_name=sender.__name__,
        object_id=str(instance.pk),
        details={"created": created},
        ip_address=ip,
    )


@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    """Log delete actions when a tracked model instance is removed.

    Dispatches a Celery task to record the deletion with the current
    user and IP from thread-local storage.

    Args:
        sender (type): The model class that sent the signal.
        instance (Model): The deleted model instance (still in memory
            but no longer in the database).
        **kwargs: Additional signal keyword arguments (unused).
    """
    if sender not in _TRACKED_MODELS:
        return

    current_user = get_current_user()
    user_id = current_user.id if current_user else None
    ip = get_client_ip()

    logger.debug(
        "Signal dispatched: action=delete, model=%s, pk=%s, user_id=%s",
        sender.__name__, instance.pk, user_id,
    )
    create_audit_log.delay(
        user_id=user_id,
        action="delete",
        model_name=sender.__name__,
        object_id=str(instance.pk),
        ip_address=ip,
    )
