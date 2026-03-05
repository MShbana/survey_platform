"""Serializers for survey response submission, retrieval.

Classes:
    FieldResponseSerializer: Read-only representation of a single field
        answer with transparent decryption.
    SurveyResponseListSerializer: Compact response summary for list views.
    SurveyResponseDetailSerializer: Full response with nested field answers.
    SubmissionAnswerSerializer: Single answer entry in a submission payload.
    SurveySubmissionSerializer: Top-level submission payload with answer
        validation.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.surveys.models import Field

from .models import FieldResponse, SurveyResponse
from .services import decrypt_value


class FieldResponseSerializer(serializers.ModelSerializer):
    """Read-only serializer for a single field's submitted answer.

    Includes the field's label and type for display purposes.  Provides
    a ``decrypted_value`` field that transparently decrypts encrypted
    values; for non-encrypted fields it returns the raw value.

    Attributes:
        field_label (str): Human-readable label of the field.
        field_type (str): The field's input type (e.g. ``text``, ``dropdown``).
        decrypted_value (str | None): The decrypted value for encrypted
            fields, or the raw value for non-encrypted fields.
    """

    field_label = serializers.CharField(source="field.label", read_only=True)
    field_type = serializers.CharField(source="field.field_type", read_only=True)
    value = serializers.SerializerMethodField()

    class Meta:
        model = FieldResponse
        fields = (
            "id",
            "field",
            "field_label",
            "field_type",
            "value",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_value(self, obj) -> str | None:
        """Return the field value, decrypting transparently for encrypted fields.

        Args:
            obj (FieldResponse): The field response instance.

        Returns:
            str | None: The plaintext value (decrypted if needed),
            ``"[decryption error]"`` on failure.
        """
        if obj.field.is_encrypted and obj.value:
            try:
                return decrypt_value(obj.value)
            except Exception:
                return "[decryption error]"
        return obj.value


class SurveyResponseListSerializer(serializers.ModelSerializer):
    """Compact response representation for list endpoints.

    Shows the response ID, parent survey, user (as string), and
    submission timestamp.
    """

    user = serializers.StringRelatedField()

    class Meta:
        model = SurveyResponse
        fields = ("id", "survey", "user", "submitted_at")


class SurveyResponseDetailSerializer(serializers.ModelSerializer):
    """Full response representation with nested field answers.

    Used by the detail endpoint to return all field responses in a
    single request.
    """

    user = serializers.StringRelatedField()
    field_responses = FieldResponseSerializer(many=True, read_only=True)

    class Meta:
        model = SurveyResponse
        fields = ("id", "survey", "user", "submitted_at", "field_responses")


class SubmissionAnswerSerializer(serializers.Serializer):
    """A single answer within a survey submission payload.

    Attributes:
        field_id (int): The ID of the field being answered.
        value (Any): The answer value.  Type depends on the field type
            (string for text, number for numeric, list for checkbox, etc.).
    """

    field_id = serializers.IntegerField()
    value = serializers.JSONField()


class SurveySubmissionSerializer(serializers.Serializer):
    """Top-level serializer for survey submission payloads.

    Expected request body::

        {
            "answers": [
                {"field_id": 1, "value": "Alice"},
                {"field_id": 2, "value": 42},
                {"field_id": 3, "value": ["opt_a", "opt_b"]}
            ]
        }

    Validation:
        - All ``field_id`` values must reference existing :class:`Field`
          records.  IDs that do not exist produce a validation error.
    """

    answers = SubmissionAnswerSerializer(many=True)

    def validate_answers(self, value):
        """Verify that all referenced field IDs exist in the database.

        Args:
            value (list[dict]): List of answer dicts, each containing
                ``field_id`` and ``value``.

        Returns:
            list[dict]: The validated answer list, unchanged.

        Raises:
            serializers.ValidationError: If any ``field_id`` does not
                correspond to an existing field.
        """

        field_ids = [answer["field_id"] for answer in value]
        existing_field_ids = set(
            Field.objects.filter(id__in=field_ids).values_list("id", flat=True)
        )
        missing_field_ids = set(field_ids) - existing_field_ids
        if missing_field_ids:
            raise serializers.ValidationError(f"Invalid field IDs: {missing_field_ids}")
        return value
