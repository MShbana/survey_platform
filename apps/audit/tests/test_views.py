from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog

User = get_user_model()


class AuditLogViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.customer = User.objects.create_user(email="cust@example.com", password="p", role="customer")
        AuditLog.objects.create(
            user=self.admin, action="create", model_name="Survey",
            object_id="1", ip_address="127.0.0.1",
        )

    def test_admin_can_list_logs(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/audit/logs/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(resp.data["count"], 1)

    def test_customer_cannot_list_logs(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get("/api/v1/audit/logs/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_list_logs(self):
        resp = self.client.get("/api/v1/audit/logs/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
