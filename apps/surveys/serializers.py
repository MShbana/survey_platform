"""Serializers for survey structure CRUD operations.

Provides serializers for every survey-related model.  Write serializers
accept minimal fields while read serializers nest related objects for
a complete representation.

Classes:
    FieldSerializer: CRUD for individual fields within a section.
    SectionSerializer: Read-only section with nested fields.
    SectionWriteSerializer: Write-only section (title, description, order).
    ConditionalRuleSerializer: CRUD for visibility rules with cross-survey
        validation.
    FieldDependencySerializer: CRUD for field dependencies with cross-survey
        validation.
    SurveyListSerializer: Compact survey representation for list views.
    SurveyDetailSerializer: Full survey with nested sections and fields.
    SurveyWriteSerializer: Write-only survey (title, description, status).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import ConditionalRule, Field, FieldDependency, Section, Survey
from .services import (
    validate_conditional_rule_data,
    validate_field_dependency_data,
    validate_field_options,
    validate_validation_rules,
)


class FieldSerializer(serializers.ModelSerializer):
    """Serializer for creating, updating, and reading survey fields.

    The ``section`` field is read-only and set automatically by the view
    based on the URL path parameter. If ``order`` is omitted on create,
    auto-assigns max + 1.
    """

    order = serializers.IntegerField(required=False, min_value=1)

    class Meta:
        model = Field
        fields = (
            "id",
            "section",
            "label",
            "field_type",
            "required",
            "order",
            "options",
            "is_encrypted",
            "validation_rules",
        )
        read_only_fields = ("id", "section")

    def validate(self, data):
        """Validate field options and validation_rules."""
        field_type = data.get("field_type", getattr(self.instance, "field_type", None))
        options = data.get("options", getattr(self.instance, "options", []))
        validation_rules = data.get(
            "validation_rules", getattr(self.instance, "validation_rules", {})
        )
        try:
            validate_field_options(field_type, options)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        try:
            validate_validation_rules(field_type, validation_rules)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return data


class SectionSerializer(serializers.ModelSerializer):
    """Read-only section representation with nested fields.

    Used in survey detail views to return the full section hierarchy.
    """

    fields = FieldSerializer(many=True, read_only=True)

    class Meta:
        model = Section
        fields = ("id", "survey", "title", "description", "order", "fields")
        read_only_fields = ("id",)


class SectionWriteSerializer(serializers.ModelSerializer):
    """Write-only serializer for creating and updating sections.

    The ``survey`` field is read-only and injected by the view's
    ``perform_create`` method using the URL path parameter.
    If ``order`` is omitted on create, auto-assigns max + 1.
    """

    order = serializers.IntegerField(required=False, min_value=1)

    class Meta:
        model = Section
        fields = ("id", "survey", "title", "description", "order")
        read_only_fields = ("id", "survey")


class ConditionalRuleSerializer(serializers.ModelSerializer):
    """Serializer for conditional visibility rules.

    Validation:
        - Exactly one of ``target_section`` or ``target_field`` must be set.
        - All referenced objects must belong to the same survey and match URL.
        - No self-reference, ordering constraints, operator/value validation.

    Raises:
        serializers.ValidationError: On constraint violations.
    """

    class Meta:
        model = ConditionalRule
        fields = (
            "id",
            "target_section",
            "target_field",
            "depends_on_field",
            "operator",
            "value",
        )
        read_only_fields = ("id",)

    def validate(self, data):
        """Enforce all conditional rule constraints."""
        survey_pk = self.context.get("survey_pk")
        try:
            validate_conditional_rule_data(data, survey_pk=survey_pk)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message)
        return data


class FieldDependencySerializer(serializers.ModelSerializer):
    """Serializer for cross-field dependencies.

    Validation:
        - Same survey, URL match, self-reference, ordering, operator/value, action_value.

    Raises:
        serializers.ValidationError: On constraint violations.
    """

    class Meta:
        model = FieldDependency
        fields = (
            "id",
            "dependent_field",
            "depends_on_field",
            "operator",
            "value",
            "action",
            "action_value",
        )
        read_only_fields = ("id",)

    def validate(self, data):
        """Enforce all field dependency constraints."""
        survey_pk = self.context.get("survey_pk")
        try:
            validate_field_dependency_data(data, survey_pk=survey_pk)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message)
        return data


class SurveyListSerializer(serializers.ModelSerializer):
    """Compact survey representation for list endpoints.

    Displays the ``created_by`` user as a string (email + role) rather
    than a nested object.
    """

    created_by = serializers.StringRelatedField()

    class Meta:
        model = Survey
        fields = (
            "id",
            "title",
            "description",
            "created_by",
            "status",
            "created_at",
            "updated_at",
        )


class SurveyDetailSerializer(serializers.ModelSerializer):
    """Full survey representation with nested sections and fields.

    Used by the ``retrieve`` action to return the complete survey structure
    in a single response. Non-admin users see only sections that have fields.
    """

    created_by = serializers.StringRelatedField()
    sections = serializers.SerializerMethodField()
    conditional_rules = ConditionalRuleSerializer(many=True, read_only=True)
    field_dependencies = FieldDependencySerializer(many=True, read_only=True)

    class Meta:
        model = Survey
        fields = (
            "id",
            "title",
            "description",
            "created_by",
            "status",
            "created_at",
            "updated_at",
            "sections",
            "conditional_rules",
            "field_dependencies",
        )

    def get_sections(self, obj):
        """Return sections, filtering out empty ones for non-admin users."""
        sections = obj.sections.all()
        request = self.context.get("request")
        if request and hasattr(request.user, "role") and request.user.role != "admin":
            sections = [s for s in sections if s.fields.all()]
        return SectionSerializer(sections, many=True).data


class SurveyWriteSerializer(serializers.ModelSerializer):
    """Write-only serializer for creating and updating surveys.

    The ``created_by`` field is set automatically in the view's
    ``perform_create`` method.
    """

    class Meta:
        model = Survey
        fields = ("id", "title", "description", "status")
        read_only_fields = ("id",)

    def validate_status(self, value):
        """
        On create, only allow draft status.
        On update, allow any status but enforce allowed transitions.
        """

        # On create, the status must be 'draft'.
        if not self.instance and value != Survey.SurveyStatus.DRAFT:
            raise serializers.ValidationError(
                "New surveys must be created with 'draft' status."
            )

        # On update, it must be a valid transition from the current status.
        if self.instance and value != self.instance.status:
            self.instance.transition_to(value)
        return value
