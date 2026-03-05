"""API views for browsing the audit log.

Provides a read-only, paginated, filterable list of audit log entries
for administrators.

Views:
    AuditLogListView: List all audit log entries (admin only).
"""

from rest_framework import generics

from apps.accounts.permissions import IsAdmin

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(generics.ListAPIView):
    """List all audit log entries with filtering, search, and ordering.

    URL pattern:
        ``GET /api/v1/audit/logs/``

    Permissions:
        IsAdmin: Only administrators can view the audit trail.

    Filtering (via ``django-filter``):
        - ``action``: Filter by action type (create, update, delete,
          view, export).
        - ``model_name``: Filter by affected model name.
        - ``user``: Filter by user ID.

    Search:
        Free-text search across ``model_name`` and ``object_id``.

    Ordering:
        Sortable by ``timestamp`` (default: newest first).
    """

    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ["action", "model_name", "user"]
    search_fields = ["model_name", "object_id"]
    ordering_fields = ["timestamp"]
