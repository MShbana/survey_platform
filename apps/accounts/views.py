"""Account management API views.

Provides endpoints for user registration, profile retrieval, and
admin-only user management (list / detail / update).

Views:
    RegisterView: Public endpoint for new user registration.
    MeView: Authenticated endpoint returning the current user's profile.
    UserListView: Admin-only paginated user listing with filtering/search.
    UserDetailView: Admin-only user detail retrieval and update.
"""

import logging

from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .permissions import IsAdmin
from .serializers import (
    UserRegistrationSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user account.

    URL pattern:
        ``POST /api/v1/auth/register/``

    Permissions:
        AllowAny -- no authentication required.

    Request body:
        Validated by :class:`~apps.accounts.serializers.UserRegistrationSerializer`.
        Non-customer roles can only be created by an authenticated admin.

    Returns:
        201: The created user's data (password excluded).
    """

    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def get_serializer_context(self):
        """Inject the current request into serializer context.

        Returns:
            dict: Serializer context with ``request`` key.
        """
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def perform_create(self, serializer):
        user = serializer.save()
        logger.info("User registered: user_id=%s, role=%s", user.id, user.role)


class MeView(generics.RetrieveAPIView):
    """Retrieve the authenticated user's own profile.

    URL pattern:
        ``GET /api/v1/auth/me/``

    Permissions:
        IsAuthenticated -- any logged-in user.

    Returns:
        200: The current user's serialized data.
    """

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return the currently authenticated user.

        Returns:
            User: The request's user instance.
        """
        return self.request.user


class UserListView(generics.ListAPIView):
    """List all users (admin only).

    URL pattern:
        ``GET /api/v1/auth/users/``

    Permissions:
        IsAdmin -- only users with the ``admin`` role.

    Query parameters:
        - ``role``: Filter by role (e.g. ``?role=customer``).
        - ``is_active``: Filter by active status (``true`` / ``false``).
        - ``search``: Search across ``email``, ``first_name``, ``last_name``.

    Returns:
        200: Paginated list of user objects.
    """

    queryset = User.objects.all().order_by("id")
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ["role", "is_active"]
    search_fields = ["email", "first_name", "last_name"]


class UserDetailView(generics.RetrieveUpdateAPIView):
    """Retrieve or update a single user (admin only).

    URL pattern:
        ``GET    /api/v1/auth/users/{id}/``
        ``PUT    /api/v1/auth/users/{id}/``
        ``PATCH  /api/v1/auth/users/{id}/``

    Permissions:
        IsAdmin -- only users with the ``admin`` role.

    Returns:
        200: The user's data. On ``PUT``/``PATCH``, the updated user data.
    """

    queryset = User.objects.all()
    permission_classes = [IsAdmin]

    def get_serializer_class(self):
        """Select serializer based on HTTP method.

        Returns:
            type: :class:`UserUpdateSerializer` for write methods,
            :class:`UserSerializer` for read methods.
        """
        if self.request.method in ("PUT", "PATCH"):
            return UserUpdateSerializer
        return UserSerializer

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(
            "User updated: user_id=%s, admin_user_id=%s",
            instance.id,
            self.request.user.id,
        )
