import logging

from rest_framework.views import exception_handler
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """Custom exception handler that extends DRF's default handler.

    This function intercepts exceptions raised in API views and allows for
    custom handling of specific exception types, while falling back to DRF's
    default behavior for unhandled exceptions.

    Args:
        exc (Exception): The exception that was raised.
        context (dict): Additional context about the exception, including the view.
    Returns:
        Response: A DRF Response object with the appropriate status code and data.
    """

    view_name = context.get("view", "").__class__.__name__ if context.get("view") else "unknown"

    # Handle IntegrityError exceptions (e.g., database constraint violations)
    if isinstance(exc, IntegrityError):
        logger.warning("IntegrityError in view=%s", view_name)
        return Response(
            {"detail": "A database integrity error occurred. Check your request data and try again."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # For all other exceptions, use DRF's default exception handler
    response = exception_handler(exc, context)

    # If the default handler returns None, it means the exception was not handled
    if response is None:
        logger.error(
            "Unhandled exception in view=%s", view_name, exc_info=True
        )
        return Response(
            {"detail": "An unexpected error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
