from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.accounts.permissions import (
    CanViewResponses,
    IsAdmin,
    IsCustomer,
    IsDataAnalyst,
    IsDataViewer,
)

User = get_user_model()


class PermissionClassTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.analyst = User.objects.create_user(email="analyst@example.com", password="p", role="data_analyst")
        self.viewer = User.objects.create_user(email="viewer@example.com", password="p", role="data_viewer")
        self.customer = User.objects.create_user(email="customer@example.com", password="p", role="customer")

    def _make_request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_is_admin(self):
        perm = IsAdmin()
        self.assertTrue(perm.has_permission(self._make_request(self.admin), None))
        self.assertFalse(perm.has_permission(self._make_request(self.customer), None))

    def test_is_data_analyst(self):
        perm = IsDataAnalyst()
        self.assertTrue(perm.has_permission(self._make_request(self.analyst), None))
        self.assertFalse(perm.has_permission(self._make_request(self.admin), None))

    def test_is_data_viewer(self):
        perm = IsDataViewer()
        self.assertTrue(perm.has_permission(self._make_request(self.viewer), None))
        self.assertFalse(perm.has_permission(self._make_request(self.customer), None))

    def test_is_customer(self):
        perm = IsCustomer()
        self.assertTrue(perm.has_permission(self._make_request(self.customer), None))
        self.assertFalse(perm.has_permission(self._make_request(self.admin), None))

    def test_can_view_responses(self):
        perm = CanViewResponses()
        self.assertTrue(perm.has_permission(self._make_request(self.admin), None))
        self.assertTrue(perm.has_permission(self._make_request(self.analyst), None))
        self.assertTrue(perm.has_permission(self._make_request(self.viewer), None))
        self.assertFalse(perm.has_permission(self._make_request(self.customer), None))
