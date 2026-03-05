"""Serializers for user registration, retrieval, and update.

Classes:
    UserRegistrationSerializer: Handles new user creation with role validation.
    UserSerializer: Read-only representation of a user (used in lists/detail).
    UserUpdateSerializer: Writable serializer for admin user management.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for creating new user accounts.

    Accepts ``email``, ``password``, ``first_name``, ``last_name``, and
    ``role``.  The ``password`` field is write-only and must be at least
    8 characters.

    Context requirements:
        ``request``: The current HTTP request.  Used by ``validate_role``
        to verify that only admins can assign non-customer roles.

    Raises:
        ValidationError: If a non-admin attempts to create a user with a
            role other than ``customer``.
    """

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name", "role")

    def validate_role(self, value):
        """Ensure only admins can create non-customer users.

        Args:
            value (str): The requested role string.

        Returns:
            str: The validated role.

        Raises:
            serializers.ValidationError: If the caller is not an admin and
                the role is not ``customer``.
        """
        request = self.context.get("request")
        if value != User.Role.CUSTOMER and (
            not request
            or not request.user.is_authenticated
            or request.user.role != User.Role.ADMIN
        ):
            raise serializers.ValidationError(
                "Only admins can create non-customer users."
            )
        return value

    def create(self, validated_data):
        """Create a new user via the custom manager.

        Args:
            validated_data (dict): Validated field data including
                plain-text ``password``.

        Returns:
            User: The newly created user with a hashed password.
        """
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    """Read-only user representation.

    Used for listing users and retrieving profile data.  The ``id`` and
    ``date_joined`` fields are always read-only.

    Attributes:
        id (int): Primary key.
        email (str): User email.
        first_name (str): First name.
        last_name (str): Last name.
        role (str): RBAC role.
        is_active (bool): Account active flag.
        date_joined (datetime): Registration timestamp.
    """

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "date_joined",
        )
        read_only_fields = ("id", "date_joined")


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin-driven user updates.

    Allows modification of ``email``, ``first_name``, ``last_name``,
    ``role``, and ``is_active``.  The ``id`` field is always read-only.
    """

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "role", "is_active")
        read_only_fields = ("id",)
