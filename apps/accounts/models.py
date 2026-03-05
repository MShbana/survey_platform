"""User authentication models for the survey platform.

This module defines the custom User model and its manager. The platform uses
email-based authentication (no username field) with four role-based access
levels: Admin, Data Analyst, Data Viewer, and Customer.

Classes:
    UserManager: Custom manager providing ``create_user`` and ``create_superuser``.
    User: Custom user model extending ``AbstractBaseUser`` and ``PermissionsMixin``.
"""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager for email-based user creation.

    Provides helper methods that normalise the email address, hash the
    password, and persist the user to the database.
    """

    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user.

        Args:
            email (str): The user's email address. Will be normalised
                (lowercased domain part).
            password (str | None): Plain-text password. Hashed before storage.
            **extra_fields: Arbitrary keyword arguments forwarded to the
                ``User`` model (e.g. ``role``, ``first_name``).

        Returns:
            User: The newly created user instance.

        Raises:
            ValueError: If ``email`` is empty or ``None``.
        """
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser with admin privileges.

        Automatically sets ``is_staff``, ``is_superuser``, and the ``admin``
        role unless overridden via *extra_fields*.

        Args:
            email (str): The superuser's email address.
            password (str | None): Plain-text password.
            **extra_fields: Additional fields forwarded to ``create_user``.

        Returns:
            User: The newly created superuser instance.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model using email as the unique identifier.

    This model replaces Django's default ``User`` and drops the ``username``
    field entirely.  Access control is handled through the ``role`` field
    which supports four levels defined in the :class:`Role` enum.

    Attributes:
        email (str): Unique email address used for authentication
            (``USERNAME_FIELD``).
        first_name (str): Optional first name.
        last_name (str): Optional last name.
        role (str): One of ``admin``, ``data_analyst``, ``data_viewer``, or
            ``customer``.  Defaults to ``customer``.
        is_active (bool): Whether the account is active.  Defaults to ``True``.
        is_staff (bool): Whether the user can access the Django admin site.
        date_joined (datetime): Timestamp set automatically on creation.

    Meta:
        db_table: ``users``
    """

    class Role(models.TextChoices):
        """Enumeration of supported RBAC roles."""

        ADMIN = "admin", "Admin"
        DATA_ANALYST = "data_analyst", "Data Analyst"
        DATA_VIEWER = "data_viewer", "Data Viewer"
        CUSTOMER = "customer", "Customer"

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def get_short_name(self):
        return self.first_name or self.email.split("@")[0]

    def get_full_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.email

    def __str__(self):
        """Return a human-readable representation: ``email (Role Display)``."""
        return f"{self.email} ({self.get_role_display()})"
