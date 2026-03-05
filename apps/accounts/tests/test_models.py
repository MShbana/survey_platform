from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()


class UserModelTest(TestCase):
    def test_create_user_default_role(self):
        user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.assertEqual(user.role, User.Role.CUSTOMER)

    def test_create_user_with_role(self):
        user = User.objects.create_user(
            email="analyst@example.com", password="testpass123", role=User.Role.DATA_ANALYST
        )
        self.assertEqual(user.role, User.Role.DATA_ANALYST)

    def test_str_representation(self):
        user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.assertEqual(str(user), "test@example.com (Customer)")

    def test_role_choices(self):
        choices = [c[0] for c in User.Role.choices]
        self.assertIn("admin", choices)
        self.assertIn("data_analyst", choices)
        self.assertIn("data_viewer", choices)
        self.assertIn("customer", choices)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="testpass123")

    def test_no_username_field(self):
        self.assertFalse(hasattr(User, "username"))
        self.assertEqual(User.USERNAME_FIELD, "email")
