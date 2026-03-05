from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class AuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="adminpass123", role="admin"
        )
        self.customer = User.objects.create_user(
            email="customer1@example.com", password="custpass123", role="customer"
        )

    def test_register_customer(self):
        resp = self.client.post("/api/v1/auth/register/", {
            "password": "strongpass123",
            "email": "new@example.com",
            "role": "customer",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["role"], "customer")

    def test_register_admin_role_without_auth_fails(self):
        resp = self.client.post("/api/v1/auth/register/", {
            "email": "newadmin@example.com",
            "password": "strongpass123",
            "role": "admin",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_admin_role_with_admin_auth(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post("/api/v1/auth/register/", {
            "email": "newadmin@example.com",
            "password": "strongpass123",
            "role": "admin",
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_login(self):
        resp = self.client.post("/api/v1/auth/login/", {
            "email": "admin@example.com",
            "password": "adminpass123",
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_invalid(self):
        resp = self.client.post("/api/v1/auth/login/", {
            "email": "admin@example.com",
            "password": "wrong",
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_authenticated(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get("/api/v1/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["email"], "customer1@example.com")

    def test_me_unauthenticated(self):
        resp = self.client.get("/api/v1/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_list_admin_only(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_user_list_customer_forbidden(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get("/api/v1/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_detail_update(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f"/api/v1/auth/users/{self.customer.id}/", {
            "role": "data_viewer",
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, "data_viewer")


class PermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="pass123", role="admin")
        self.analyst = User.objects.create_user(email="analyst@example.com", password="pass123", role="data_analyst")
        self.viewer = User.objects.create_user(email="viewer@example.com", password="pass123", role="data_viewer")
        self.customer = User.objects.create_user(email="customer@example.com", password="pass123", role="customer")

    def test_admin_can_access_user_list(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_analyst_cannot_access_user_list(self):
        self.client.force_authenticate(user=self.analyst)
        resp = self.client.get("/api/v1/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_access_user_list(self):
        self.client.force_authenticate(user=self.viewer)
        resp = self.client.get("/api/v1/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
