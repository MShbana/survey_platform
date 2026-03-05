"""API views for survey response submission, retrieval, and export.

Provides endpoints for customers to submit survey responses, and for
privileged users (Admin, Data Analyst, Data Viewer) to view and export
response data.  All view/export actions are audit-logged asynchronously
via Celery.

Views:
    SurveySubmitView: Submit a survey response (customer only).
    SurveyResponseListView: List responses for a survey.
    SurveyResponseDetailView: Retrieve a single response with field answers.
"""

import logging

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers as drf_serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanViewResponses, IsCustomer
from apps.audit.tasks import create_audit_log
from apps.audit.middleware import get_client_ip
from apps.surveys.models import Field, Survey

from .models import SurveyResponse
from .serializers import (
    SurveyResponseDetailSerializer,
    SurveyResponseListSerializer,
    SurveySubmissionSerializer,
)
from .services import (
    ValidationError as SubmissionValidationError,
    create_submission,
    validate_submission,
)

logger = logging.getLogger(__name__)


class SurveySubmitView(APIView):
    """Submit a response to an active survey.

    URL pattern:
        ``POST /api/v1/surveys/{survey_pk}/submit/``

    Permissions:
        IsCustomer: Only authenticated customers can submit.

    Request body:
        Validated by :class:`~apps.responses.serializers.SurveySubmissionSerializer`.

    Response codes:
        - 201: Submission created successfully.
        - 400: Validation errors (missing required fields, invalid types,
          dependency constraint violations).
        - 404: Survey not found or not active.
    """

    permission_classes = [IsCustomer]

    @extend_schema(
        request=SurveySubmissionSerializer,
        responses={
            201: inline_serializer(
                name="SubmissionSuccess",
                fields={
                    "id": drf_serializers.IntegerField(),
                    "message": drf_serializers.CharField(),
                },
            ),
            400: inline_serializer(
                name="SubmissionErrors",
                fields={
                    "errors": drf_serializers.DictField(
                        child=drf_serializers.CharField()
                    ),
                },
            ),
        },
        summary="Submit a survey response",
        description="Authenticated customers submit answers for an active survey.",
    )
    def post(self, request, survey_pk):
        """Process a survey submission.

        Validates answers against the survey's conditional logic and field
        dependencies, encrypts sensitive field values, and bulk-creates
        all field responses in a single query.

        Args:
            request (Request): The incoming DRF request.
            survey_pk (int): Primary key of the target survey.

        Returns:
            Response: ``{"id": <response_id>, "message": "..."}`` on
            success, or ``{"errors": {...}}`` on validation failure.
        """
        logger.debug(
            "Submission started: survey_id=%s, user_id=%s", survey_pk, request.user.id
        )
        survey = get_object_or_404(
            Survey, pk=survey_pk, status=Survey.SurveyStatus.PUBLISHED
        )

        serializer = SurveySubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Fetch all fields for this survey in a single query.
        survey_fields = {f.id: f for f in Field.objects.filter(section__survey=survey)}
        survey_field_ids = set(survey_fields.keys())

        # Validate that all submitted field IDs belong to this survey and build
        # a dict of field_id → answer for validation.  The serializer has
        # already verified that all field IDs exist.
        answers_dict = {}
        for a in serializer.validated_data["answers"]:
            fid = a["field_id"]
            if fid not in survey_field_ids:
                logger.warning(
                    "Field does not belong to survey: field_id=%s, survey_id=%s",
                    fid,
                    survey_pk,
                )
                return Response(
                    {"errors": {str(fid): "Field does not belong to this survey."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            answers_dict[str(fid)] = a["value"]

        try:
            cleaned = validate_submission(survey, answers_dict)
        except SubmissionValidationError as e:
            logger.warning(
                "Submission validation failed: survey_id=%s, user_id=%s, failed_field_ids=%s",
                survey_pk,
                request.user.id,
                list(e.errors.keys()),
            )
            return Response({"errors": e.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            survey_response = create_submission(
                survey=survey,
                user=request.user,
                cleaned_answers=cleaned,
                survey_fields=survey_fields,
            )
        except SubmissionValidationError as e:
            return Response({"errors": e.errors}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "Submission successful: response_id=%s, survey_id=%s, user_id=%s, field_count=%d",
            survey_response.id,
            survey_pk,
            request.user.id,
            len(cleaned),
        )

        return Response(
            {
                "id": survey_response.id,
                "message": "Response submitted successfully.",
            },
            status=status.HTTP_201_CREATED,
        )


class SurveyResponseListView(generics.ListAPIView):
    """List all responses for a given survey.

    URL pattern:
        ``GET /api/v1/surveys/{survey_pk}/responses/``

    Permissions:
        CanViewResponses: Admin, Data Analyst, and Data Viewer.

    Side effects:
        Creates an audit log entry (``action="view"``, ``scope="list"``)
        via Celery.
    """

    serializer_class = SurveyResponseListSerializer
    permission_classes = [CanViewResponses]

    def get_queryset(self):
        """Return responses for the given survey with user pre-fetched.

        Returns:
            QuerySet[SurveyResponse]: Filtered, optimised queryset.

        Raises:
            Http404: If the survey does not exist.
        """
        if getattr(self, "swagger_fake_view", False):
            return SurveyResponse.objects.none()
        get_object_or_404(Survey, pk=self.kwargs["survey_pk"])
        return SurveyResponse.objects.filter(
            survey_id=self.kwargs["survey_pk"]
        ).select_related("user")

    def list(self, request, *args, **kwargs):
        """Override list to append an audit log entry after response.

        Args:
            request (Request): The incoming request.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Response: Paginated list of survey responses.
        """
        response = super().list(request, *args, **kwargs)
        logger.info(
            "Response list viewed: survey_id=%s, user_id=%s",
            self.kwargs["survey_pk"],
            request.user.id,
        )
        create_audit_log.delay(
            user_id=request.user.id,
            action="view",
            model_name="SurveyResponse",
            object_id=str(self.kwargs["survey_pk"]),
            details={"scope": "list"},
            ip_address=get_client_ip(),
        )
        return response


class SurveyResponseDetailView(generics.RetrieveAPIView):
    """Retrieve a single response with all field answers.

    URL pattern:
        ``GET /api/v1/surveys/{survey_pk}/responses/{pk}/``

    Permissions:
        CanViewResponses: Admin, Data Analyst, and Data Viewer.

    Side effects:
        Creates an audit log entry (``action="view"``, ``scope="detail"``)
        via Celery.
    """

    serializer_class = SurveyResponseDetailSerializer
    permission_classes = [CanViewResponses]

    def get_queryset(self):
        """Return the response with user and field data pre-fetched.

        Returns:
            QuerySet[SurveyResponse]: Filtered, optimised queryset.

        Raises:
            Http404: If the survey does not exist.
        """
        if getattr(self, "swagger_fake_view", False):
            return SurveyResponse.objects.none()
        get_object_or_404(Survey, pk=self.kwargs["survey_pk"])
        return (
            SurveyResponse.objects.filter(survey_id=self.kwargs["survey_pk"])
            .select_related("user")
            .prefetch_related("field_responses__field")
        )

    def retrieve(self, request, *args, **kwargs):
        """Override retrieve to append an audit log entry after response.

        Args:
            request (Request): The incoming request.
            *args: Positional arguments.
            **kwargs: Must contain ``pk``.

        Returns:
            Response: The full response detail.
        """
        response = super().retrieve(request, *args, **kwargs)
        logger.info(
            "Response detail viewed: response_id=%s, survey_id=%s, user_id=%s",
            kwargs["pk"],
            self.kwargs["survey_pk"],
            request.user.id,
        )
        create_audit_log.delay(
            user_id=request.user.id,
            action="view",
            model_name="SurveyResponse",
            object_id=str(kwargs["pk"]),
            details={"scope": "detail"},
            ip_address=get_client_ip(),
        )
        return response

