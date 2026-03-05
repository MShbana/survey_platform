"""API views for survey structure management.

Provides ViewSets for the multi-step survey builder: surveys, sections,
fields, conditional rules, and field dependencies.  All write operations
are restricted to admins; read access is available to any authenticated
user.

Each mutating operation invalidates the Redis cache entry for the
affected survey so that subsequent ``retrieve`` calls return fresh data.

ViewSets:
    SurveyViewSet: CRUD for surveys with Redis-cached detail retrieval.
    SectionViewSet: CRUD for sections within a survey.
    FieldViewSet: CRUD for fields within a section.
    ConditionalRuleViewSet: CRUD for conditional visibility rules.
    FieldDependencyViewSet: CRUD for cross-field dependencies.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin, IsAdminOrReadOnly
from apps.surveys.cache import SurveyCacheService

from .models import ConditionalRule, Field, FieldDependency, Section, Survey
from .services import (
    create_conditional_rule,
    create_field,
    create_field_dependency,
    delete_conditional_rule,
    delete_field,
    delete_field_dependency,
    delete_section,
    detect_circular_dependencies_cr,
    detect_circular_dependencies_fd,
    update_conditional_rule,
    update_field,
    update_field_dependency,
    update_section,
    validate_survey_is_draft,
)

logger = logging.getLogger(__name__)

from .serializers import (
    ConditionalRuleSerializer,
    FieldDependencySerializer,
    FieldSerializer,
    SectionSerializer,
    SectionWriteSerializer,
    SurveyDetailSerializer,
    SurveyListSerializer,
    SurveyWriteSerializer,
)


def _ensure_draft_survey(survey):
    """Raise DRF ValidationError if survey is not draft."""
    try:
        validate_survey_is_draft(survey)
    except DjangoValidationError as e:
        raise DRFValidationError({"detail": e.message})



class SurveyViewSet(viewsets.ModelViewSet):
    """ViewSet for managing surveys.

    Provides standard CRUD operations.  The ``retrieve`` action is cached
    in Redis for ``SURVEY_CACHE_TIMEOUT`` seconds (default 15 minutes).

    URL patterns (via router):
        - ``GET    /api/v1/surveys/``          -- list surveys
        - ``POST   /api/v1/surveys/``          -- create a new survey
        - ``GET    /api/v1/surveys/{id}/``     -- retrieve (cached)
        - ``PUT    /api/v1/surveys/{id}/``     -- full update
        - ``PATCH  /api/v1/surveys/{id}/``     -- partial update
        - ``DELETE /api/v1/surveys/{id}/``     -- delete

    Permissions:
        IsAdminOrReadOnly: Any authenticated user can read; only admins
        can create, update, or delete.

    Filters:
        - ``status``: Filter by survey status (draft, published, archived).
        - ``search``: Full-text search on ``title`` and ``description``.
        - ``ordering``: ``created_at``, ``title``.
    """

    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["status"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "title"]

    def get_queryset(self):
        """Return surveys with ``created_by`` pre-fetched.

        Customers only see published surveys.  For ``retrieve`` actions,
        sections and fields are also prefetched to avoid N+1 queries.

        Returns:
            QuerySet[Survey]: Optimised queryset.
        """
        if getattr(self, "swagger_fake_view", False):
            return Survey.objects.none()

        qs = Survey.objects.select_related("created_by")

        # filter out non-published surveys for customers
        if self.request.user.role == "customer":
            qs = qs.filter(status=Survey.SurveyStatus.PUBLISHED)

        # prefetch sections, fields, conditional rules, and field dependencies for retrieve action.
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                "sections__fields",
                "conditional_rules_direct__depends_on_field",
                "conditional_rules_direct__target_section",
                "conditional_rules_direct__target_field",
                "field_dependencies_direct__dependent_field",
                "field_dependencies_direct__depends_on_field",
            )

        return qs

    def get_serializer_class(self):
        """Select the appropriate serializer for the current action.

        Returns:
            type: ``SurveyListSerializer`` for ``list``,
            ``SurveyWriteSerializer`` for write actions,
            ``SurveyDetailSerializer`` otherwise.
        """
        if self.action == "list":
            return SurveyListSerializer
        if self.action in ("create", "update", "partial_update"):
            return SurveyWriteSerializer
        return SurveyDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        """Retrieve a survey with Redis caching.

        Checks the cache first (key ``survey:{pk}:structure``).  On a
        cache miss, delegates to the parent ``retrieve`` and stores the
        serialized response for ``SURVEY_CACHE_TIMEOUT`` seconds.

        Args:
            request (Request): The incoming request.
            *args: Positional arguments.
            **kwargs: Must contain ``pk``.

        Returns:
            Response: Serialized survey data.
        """
        pk = kwargs["pk"]

        # attempt to get from cache; if found, return immediately.
        cached = SurveyCacheService.get_structure(pk)
        if cached:
            return Response(cached)

        # cache miss: delegate to parent method to retrieve from DB, then cache the result.
        response = super().retrieve(request, *args, **kwargs)
        SurveyCacheService.set_structure(pk, response.data)
        return response

    def perform_create(self, serializer):
        """Set ``created_by`` to the requesting user before saving."""

        instance = serializer.save(created_by=self.request.user)
        logger.info(
            "Survey created: survey_id=%s, user_id=%s",
            instance.id,
            self.request.user.id,
        )

    def perform_update(self, serializer):
        """Save the survey via service, translating Django→DRF validation errors."""
        instance = serializer.save()
        SurveyCacheService.invalidate_structure(instance.id)
        logger.info(
            "Survey updated: survey_id=%s, user_id=%s",
            serializer.instance.id,
            self.request.user.id,
        )

    def perform_destroy(self, instance):
        """Delete the survey via service."""
        # This might not be needed depending on business needs.
        instance.delete()
        SurveyCacheService.invalidate_structure(instance.id)
        logger.info(
            "Survey deleted: survey_id=%s, user_id=%s",
            instance.id,
            self.request.user.id,
        )


class SectionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing sections within a survey.

    URL patterns:
        - ``GET/POST  /api/v1/surveys/{survey_pk}/sections/``
        - ``GET/PUT/PATCH/DELETE  /api/v1/surveys/{survey_pk}/sections/{pk}/``

    Permissions:
        IsAdmin: Only admins can manage sections.

    URL kwargs:
        ``survey_pk``: Primary key of the parent survey.
    """

    permission_classes = [IsAdmin]

    def get_survey(self):
        """Fetch the parent survey or raise 404."""
        return get_object_or_404(
            Survey, pk=self.kwargs["survey_pk"]
        )

    def get_queryset(self):
        """Return sections for the given survey, with fields prefetched for reads.

        Returns:
            QuerySet[Section]: Filtered and optionally prefetched queryset.
        """
        if getattr(self, "swagger_fake_view", False):
            return Section.objects.none()

        self.get_survey()

        qs = Section.objects.filter(survey_id=self.kwargs["survey_pk"]).order_by("order")

        if self.action in ("retrieve", "list"):
            qs = qs.prefetch_related("fields")
        return qs

    def get_serializer_class(self):
        """Select the appropriate serializer for the current action.

        Returns:
            type: ``SectionWriteSerializer`` for write actions,
            ``SectionSerializer`` for reads.
        """
        if self.action in ("create", "update", "partial_update"):
            return SectionWriteSerializer
        return SectionSerializer

    def perform_create(self, serializer):
        """Attach the section to the survey via service. Auto-assign order if omitted."""

        survey = self.get_survey()
        _ensure_draft_survey(survey)

        data = serializer.validated_data.copy()

        if "order" not in data:
            max_order = Section.objects.filter(
                survey=survey
            ).aggregate(Max("order"))["order__max"]
            data["order"] = (max_order or 0) + 1

        try:
            instance = Section.objects.create(survey=survey, **data)
        except IntegrityError:
            raise DRFValidationError(
                {"order": "A section with this order already exists in this survey."}
            )

        SurveyCacheService.invalidate_structure(survey.id)

        serializer.instance = instance
        logger.info(
            "Section created: section_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey.id,
            self.request.user.id,
        )

    def perform_update(self, serializer):
        """Update the section via service."""
        survey = serializer.instance.survey
        _ensure_draft_survey(survey)
        try:
            instance = update_section(serializer.instance, serializer.validated_data)
        except DjangoValidationError as e:
            raise DRFValidationError({"detail": e.message})
        logger.info(
            "Section updated: section_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            instance.survey_id,
            self.request.user.id,
        )

    def perform_destroy(self, instance):
        """Delete the section via service."""
        _ensure_draft_survey(instance.survey)
        logger.info(
            "Section deleted: section_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            instance.survey_id,
            self.request.user.id,
        )
        delete_section(instance)


class FieldViewSet(viewsets.ModelViewSet):
    """ViewSet for managing fields within a section.

    URL patterns:
        - ``GET/POST  /api/v1/surveys/{survey_pk}/sections/{section_pk}/fields/``
        - ``GET/PUT/PATCH/DELETE  .../fields/{pk}/``

    Permissions:
        IsAdmin: Only admins can manage fields.

    URL kwargs:
        ``survey_pk``: Parent survey PK.
        ``section_pk``: Parent section PK.
    """

    serializer_class = FieldSerializer
    permission_classes = [IsAdmin]

    def get_survey(self):
        """Fetch the parent survey or raise 404."""
        return get_object_or_404(
            Survey, pk=self.kwargs["survey_pk"]
        )

    def get_section(self):
        """Fetch and verify the section belongs to the survey, or raise 404."""
        self.get_survey()
        return get_object_or_404(
            Section,
            pk=self.kwargs["section_pk"],
            survey_id=self.kwargs["survey_pk"],
        )

    def get_queryset(self):
        """Return fields for the given section within the given survey.

        Returns:
            QuerySet[Field]: Filtered queryset.
        """
        if getattr(self, "swagger_fake_view", False):
            return Field.objects.none()

        self.get_section()

        return Field.objects.filter(
            section=self.kwargs["section_pk"],
            section__survey=self.kwargs["survey_pk"],
        ).order_by("order")

    def perform_create(self, serializer):
        """Attach the field to the section via service. Auto-assign order if omitted."""
        section = self.get_section()

        _ensure_draft_survey(section.survey)
        data = serializer.validated_data
        if "order" not in data or data["order"] is None:
            max_order = Field.objects.filter(section=section).aggregate(
                Max("order")
            )["order__max"]
            data["order"] = (max_order or 0) + 1
        try:
            instance = create_field(section=section, **data)
        except DjangoValidationError as e:
            raise DRFValidationError(e.message_dict if hasattr(e, 'message_dict') else {"detail": e.message})
        serializer.instance = instance
        logger.info(
            "Field created: field_id=%s, section_id=%s, user_id=%s",
            instance.id,
            section.id,
            self.request.user.id,
        )

    def perform_update(self, serializer):
        """Update the field via service."""
        _ensure_draft_survey(serializer.instance.section.survey)
        try:
            instance = update_field(serializer.instance, serializer.validated_data)
        except DjangoValidationError as e:
            raise DRFValidationError({"detail": e.message})
        logger.info(
            "Field updated: field_id=%s, user_id=%s", instance.id, self.request.user.id
        )

    def perform_destroy(self, instance):
        """Delete the field via service."""
        _ensure_draft_survey(instance.section.survey)
        logger.info(
            "Field deleted: field_id=%s, user_id=%s", instance.id, self.request.user.id
        )
        delete_field(instance)


class ConditionalRuleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing conditional visibility rules.

    URL patterns:
        - ``GET/POST  /api/v1/surveys/{survey_pk}/conditional-rules/``
        - ``GET/PUT/PATCH/DELETE  .../conditional-rules/{pk}/``

    Permissions:
        IsAdmin: Only admins can manage rules.

    URL kwargs:
        ``survey_pk``: The survey whose rules are managed.
    """

    serializer_class = ConditionalRuleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        """Return rules whose ``depends_on_field`` belongs to the survey."""
        if getattr(self, "swagger_fake_view", False):
            return ConditionalRule.objects.none()
        return ConditionalRule.objects.filter(
            survey_id=self.kwargs["survey_pk"],
        ).select_related("depends_on_field", "target_section", "target_field")

    def get_serializer_context(self):
        """Pass survey_pk to serializer for URL validation."""
        ctx = super().get_serializer_context()
        ctx["survey_pk"] = self.kwargs.get("survey_pk")
        return ctx

    def _check_circular_cr(self, data, exclude_rule_id=None):
        """Run circular dependency detection, raising DRF error on cycle."""
        try:
            detect_circular_dependencies_cr(
                depends_on_field=data.get("depends_on_field"),
                target_field=data.get("target_field"),
                target_section=data.get("target_section"),
                exclude_rule_id=exclude_rule_id,
            )
        except DjangoValidationError as e:
            raise DRFValidationError({"detail": e.message})

    def perform_create(self, serializer):
        """Create the rule via service."""
        _ensure_draft_survey(self.survey)
        self._check_circular_cr(serializer.validated_data)
        instance = create_conditional_rule(serializer.validated_data, self.survey.pk)
        serializer.instance = instance
        logger.info(
            "ConditionalRule created: rule_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            self.survey.pk,
            self.request.user.id,
        )

    def perform_update(self, serializer):
        """Update the rule via service."""
        survey_pk = self.kwargs["survey_pk"]
        survey = get_object_or_404(Survey, pk=survey_pk)
        _ensure_draft_survey(survey)
        self._check_circular_cr(
            serializer.validated_data,
            exclude_rule_id=serializer.instance.pk,
        )
        instance = update_conditional_rule(
            serializer.instance, serializer.validated_data, survey_pk
        )
        logger.info(
            "ConditionalRule updated: rule_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey_pk,
            self.request.user.id,
        )

    def perform_destroy(self, instance):
        """Delete the rule via service."""
        survey_pk = self.kwargs["survey_pk"]
        survey = get_object_or_404(Survey, pk=survey_pk)
        _ensure_draft_survey(survey)
        logger.info(
            "ConditionalRule deleted: rule_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey_pk,
            self.request.user.id,
        )
        delete_conditional_rule(instance, survey_pk)


class FieldDependencyViewSet(viewsets.ModelViewSet):
    """ViewSet for managing cross-field dependencies.

    URL patterns:
        - ``GET/POST  /api/v1/surveys/{survey_pk}/field-dependencies/``
        - ``GET/PUT/PATCH/DELETE  .../field-dependencies/{pk}/``

    Permissions:
        IsAdmin: Only admins can manage dependencies.

    URL kwargs:
        ``survey_pk``: The survey whose dependencies are managed.
    """

    serializer_class = FieldDependencySerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        """Return dependencies whose ``dependent_field`` belongs to the survey."""
        if getattr(self, "swagger_fake_view", False):
            return FieldDependency.objects.none()
        return FieldDependency.objects.filter(
            survey_id=self.kwargs["survey_pk"],
        ).select_related("dependent_field", "depends_on_field")

    def get_serializer_context(self):
        """Pass survey_pk to serializer for URL validation."""
        ctx = super().get_serializer_context()
        ctx["survey_pk"] = self.kwargs.get("survey_pk")
        return ctx

    def _check_circular_fd(self, data, exclude_dep_id=None):
        """Run circular dependency detection, raising DRF error on cycle."""
        try:
            detect_circular_dependencies_fd(
                depends_on_field=data.get("depends_on_field"),
                dependent_field=data.get("dependent_field"),
                exclude_dep_id=exclude_dep_id,
            )
        except DjangoValidationError as e:
            raise DRFValidationError({"detail": e.message})

    def perform_create(self, serializer):
        """Create the dependency via service."""
        survey_pk = self.kwargs["survey_pk"]
        survey = get_object_or_404(Survey, pk=survey_pk)
        _ensure_draft_survey(survey)
        self._check_circular_fd(serializer.validated_data)
        instance = create_field_dependency(serializer.validated_data, survey_pk)
        serializer.instance = instance
        logger.info(
            "FieldDependency created: dep_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey_pk,
            self.request.user.id,
        )

    def perform_update(self, serializer):
        """Update the dependency via service."""
        survey_pk = self.kwargs["survey_pk"]
        survey = get_object_or_404(Survey, pk=survey_pk)
        _ensure_draft_survey(survey)
        self._check_circular_fd(
            serializer.validated_data,
            exclude_dep_id=serializer.instance.pk,
        )
        instance = update_field_dependency(
            serializer.instance, serializer.validated_data, survey_pk
        )
        logger.info(
            "FieldDependency updated: dep_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey_pk,
            self.request.user.id,
        )

    def perform_destroy(self, instance):
        """Delete the dependency via service."""
        survey_pk = self.kwargs["survey_pk"]
        survey = get_object_or_404(Survey, pk=survey_pk)
        _ensure_draft_survey(survey)
        logger.info(
            "FieldDependency deleted: dep_id=%s, survey_id=%s, user_id=%s",
            instance.id,
            survey_pk,
            self.request.user.id,
        )
        delete_field_dependency(instance, survey_pk)
