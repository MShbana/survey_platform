"""Serializers for audit log API responses.

Classes:
    AuditLogSerializer: Read-only representation of an audit log entry.
"""

from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for :class:`~apps.audit.models.AuditLog`.

    Renders the ``user`` field as a string (email address) via
    :class:`~rest_framework.serializers.StringRelatedField` so that
    the API consumer sees a human-readable identifier rather than a
    raw primary key.

    Attributes:
        user (str): String representation of the user (email).
    """

    user = serializers.StringRelatedField()

    class Meta:
        model = AuditLog
        fields = (
            "id", "user", "action", "model_name", "object_id",
            "details", "ip_address", "timestamp",
        )
