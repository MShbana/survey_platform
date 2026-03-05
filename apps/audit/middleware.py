"""Middleware for capturing request context used by audit logging.

Stores the client IP address and authenticated user in thread-local
storage so that Django signal handlers (which lack access to the
request object) can include this information in audit log entries.

Functions:
    get_client_ip: Retrieve the stored client IP for the current thread.
    get_current_user: Retrieve the stored user for the current thread.

Classes:
    AuditIPMiddleware: Django middleware that populates thread-local
        request context on each request.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_thread_local = threading.local()


def get_client_ip():
    """Return the client IP address for the current request thread.

    Returns:
        str | None: The IP address stored by :class:`AuditIPMiddleware`,
        or ``None`` if called outside a request context.
    """
    return getattr(_thread_local, "ip_address", None)


def get_current_user():
    """Return the authenticated user for the current request thread.

    Returns:
        User | None: The authenticated user stored by
        :class:`AuditIPMiddleware`, or ``None`` if the request is
        anonymous or called outside a request context.
    """
    return getattr(_thread_local, "current_user", None)


class AuditIPMiddleware:
    """Django middleware that stores request context in thread-local storage.

    On each request, extracts the client IP address (respecting
    ``X-Forwarded-For`` for proxied requests) and the authenticated
    user, and stores them in :data:`_thread_local` for access by
    signal handlers and other code that lacks a direct request reference.

    Note:
        This middleware must be placed **after**
        ``django.contrib.auth.middleware.AuthenticationMiddleware`` in
        ``MIDDLEWARE`` so that ``request.user`` is populated.
    """

    def __init__(self, get_response):
        """Initialise the middleware.

        Args:
            get_response (callable): The next middleware or view in the
                Django middleware chain.
        """
        self.get_response = get_response

    def __call__(self, request):
        """Process a request and populate thread-local context.

        Extracts the client IP from ``HTTP_X_FORWARDED_FOR`` (first
        entry) or ``REMOTE_ADDR``, and stores the authenticated user
        (if any) in thread-local storage before passing the request
        to the next handler.

        Args:
            request (HttpRequest): The incoming Django request.

        Returns:
            HttpResponse: The response from downstream middleware/views.
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        _thread_local.ip_address = ip

        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            _thread_local.current_user = user
        else:
            _thread_local.current_user = None

        logger.debug(
            "Request context: user_id=%s, path=%s",
            user.id if user and getattr(user, "is_authenticated", False) else None,
            request.path,
        )

        response = self.get_response(request)
        return response
