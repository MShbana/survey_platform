from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog

User = get_user_model()


class AuditLogModelTest(TestCase):
    def test_create_audit_log(self):
        user = User.objects.create_user(email="u@example.com", password="p")
        log = AuditLog.objects.create(
            user=user,
            action="create",
            model_name="Survey",
            object_id="1",
            details={"title": "Test"},
            ip_address="127.0.0.1",
        )
        self.assertEqual(str(log), f"{user} create Survey:1")
        self.assertEqual(log.action, "create")

    def test_create_without_user(self):
        log = AuditLog.objects.create(
            action="view",
            model_name="Survey",
            object_id="1",
        )
        self.assertIsNone(log.user)
