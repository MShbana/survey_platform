"""URL configuration for the audit app.

All endpoints are mounted under ``/api/v1/audit/`` by the root URL
config.

Routes:
    GET  /logs/  -- List audit log entries (admin only).
"""

from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("logs/", views.AuditLogListView.as_view(), name="log-list"),
]
