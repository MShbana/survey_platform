"""Survey response storage models.

This module defines the models that capture respondent submissions.
Each :class:`SurveyResponse` represents a single completed submission
by an authenticated customer, and contains one :class:`FieldResponse`
per answered field.

Models:
    SurveyResponse: A customer's submission to a survey.
    FieldResponse: The value submitted for a single field.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

class SurveyResponse(models.Model):
    """A single survey submission by an authenticated customer.

    Links the respondent (:attr:`user`) to the :attr:`survey` and records
    the submission timestamp.  Individual field answers are stored as
    related :class:`FieldResponse` instances.

    Attributes:
        survey (Survey): FK to the survey that was answered.
        user (User): FK to the customer who submitted the response.
        submitted_at (datetime): Auto-set timestamp of submission.

    Meta:
        db_table: ``survey_responses``
        ordering: ``["-submitted_at"]`` (newest first)
        indexes: ``(survey, user)``, ``submitted_at``
    """

    survey = models.ForeignKey(
        "surveys.Survey",
        on_delete=models.CASCADE,
        related_name="responses",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="survey_responses",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survey_responses"
        unique_together = [("survey", "user")]
        indexes = [
            models.Index(fields=["submitted_at"]),
        ]
        ordering = ["-submitted_at"]

    def __str__(self):
        """Return ``"Response to 'Survey Title' by user@email.com"``."""
        return f"Response to '{self.survey.title}' by {self.user.email}"

    def clean(self):
        """Perform integrity checks before saving.

        - survey must be published
        - user must have ``customer`` role
        - a given user may only submit once per survey
        """
        # delay import to avoid circular dependency
        from apps.accounts.models import User
        from apps.surveys.models import Survey

        if self.survey and self.survey.status != Survey.SurveyStatus.PUBLISHED:
            raise ValidationError("Cannot submit response to an unpublished survey.")

        # only customers can create responses
        if hasattr(self.user, "role") and self.user.role != User.Role.CUSTOMER:
            raise ValidationError("Only customers may submit survey responses.")

        # disallow duplicate responses by same user/survey
        existing = SurveyResponse.objects.filter(
            survey=self.survey, user=self.user
        )
        if self.pk:
            existing = existing.exclude(pk=self.pk)
        if existing.exists():
            raise ValidationError("User has already submitted a response to this survey.")


class FieldResponse(models.Model):
    """The value submitted for a single survey field.

    Values are stored as text.  For fields with ``is_encrypted=True``,
    the value is Fernet-encrypted before storage and decrypted on read
    via the serializer.

    Attributes:
        survey_response (SurveyResponse): FK to the parent submission.
        field (Field): FK to the survey field definition.
        value (str): The submitted value (possibly encrypted).

    Meta:
        db_table: ``field_responses``
        indexes: ``(survey_response, field)``
    """

    survey_response = models.ForeignKey(
        SurveyResponse,
        on_delete=models.CASCADE,
        related_name="field_responses",
    )
    field = models.ForeignKey(
        "surveys.Field",
        on_delete=models.CASCADE,
        related_name="responses",
    )
    value = models.TextField(blank=True, default="")

    class Meta:
        db_table = "field_responses"
        indexes = [
            models.Index(fields=["survey_response", "field"]),
        ]

    def __str__(self):
        """Return ``"Field Label: value (truncated to 50 chars)"``."""
        return f"{self.field.label}: {self.value[:50]}"

    def clean(self):
        """Ensure the field belongs to the same survey as the parent response.

        This prevents dangling or cross-survey field responses that could be
        inserted via the admin site or other bulk operations.
        """
        if self.survey_response_id and self.field_id:
            if self.field.section.survey_id != self.survey_response.survey_id:
                raise ValidationError(
                    "Field must belong to the same survey as the survey response."
                )
