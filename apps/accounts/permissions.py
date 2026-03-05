"""Role-based permission classes for the survey platform.

Each class maps to one or more RBAC roles defined in
:class:`~apps.accounts.models.User.Role`.  All classes require the
user to be authenticated before checking the role.

Permission matrix:
    ================ ======== ============ =========== =========
    Resource         Admin    Data Analyst  Data Viewer  Customer
    ================ ======== ============ =========== =========
    Surveys (write)  Yes      No            No          No
    Surveys (read)   Yes      Yes           Yes         Yes
    Responses (view) Yes      Yes           Yes         No
    Submit response  No       No            No          Yes
    Users            Yes      No            No          No
    Audit logs       Yes      No            No          No
    ================ ======== ============ =========== =========

Classes:
    IsAdmin: Grants access to users with the ``admin`` role.
    IsDataAnalyst: Grants access to users with the ``data_analyst`` role.
    IsDataViewer: Grants access to users with the ``data_viewer`` role.
    IsCustomer: Grants access to users with the ``customer`` role.
    IsAdminOrReadOnly: Allows read access to any authenticated user; write
        access restricted to admins.
    CanViewResponses: Admin, Data Analyst, and Data Viewer can view responses.
"""

from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Allow access only to users with the ``admin`` role.

    Returns ``False`` for unauthenticated requests.
    """

    def has_permission(self, request, view):
        """Check that the user is authenticated and has the admin role.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user is an authenticated admin.
        """
        return request.user.is_authenticated and request.user.role == "admin"


class IsDataAnalyst(BasePermission):
    """Allow access only to users with the ``data_analyst`` role."""

    def has_permission(self, request, view):
        """Check that the user is authenticated with the data_analyst role.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user is an authenticated data analyst.
        """
        return request.user.is_authenticated and request.user.role == "data_analyst"


class IsDataViewer(BasePermission):
    """Allow access only to users with the ``data_viewer`` role."""

    def has_permission(self, request, view):
        """Check that the user is authenticated with the data_viewer role.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user is an authenticated data viewer.
        """
        return request.user.is_authenticated and request.user.role == "data_viewer"


class IsCustomer(BasePermission):
    """Allow access only to users with the ``customer`` role."""

    def has_permission(self, request, view):
        """Check that the user is authenticated with the customer role.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user is an authenticated customer.
        """
        return request.user.is_authenticated and request.user.role == "customer"


class IsAdminOrReadOnly(BasePermission):
    """Allow read access to any authenticated user; write access to admins only.

    Safe methods (``GET``, ``HEAD``, ``OPTIONS``) are permitted for all
    authenticated users.  Unsafe methods (``POST``, ``PUT``, ``PATCH``,
    ``DELETE``) require the ``admin`` role.
    """

    def has_permission(self, request, view):
        """Check authentication and role for the requested HTTP method.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user is authenticated and either the
            method is safe or the user is an admin.
        """
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role == "admin"


class CanViewResponses(BasePermission):
    """Allow Admin, Data Analyst, and Data Viewer to view survey responses.

    Customers are explicitly excluded from viewing responses.
    """

    def has_permission(self, request, view):
        """Check that the user has a response-viewing role.

        Args:
            request (Request): The incoming DRF request.
            view (View): The view being accessed.

        Returns:
            bool: ``True`` if the user has one of the three permitted roles.
        """
        if not request.user.is_authenticated:
            return False
        return request.user.role in ("admin", "data_analyst", "data_viewer")

