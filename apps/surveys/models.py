"""Survey structure models.

This module defines the core data models that represent a survey's
hierarchical structure: Survey -> Section -> Field.  It also includes
models for conditional display logic (ConditionalRule) and cross-field
dependencies (FieldDependency).

Models:
    Survey: Top-level container for a survey.
    Section: A named group of fields within a survey, ordered by position.
    Field: A single input field with type, validation rules, and options.
    ConditionalRule: Controls visibility of a section or field based on
        another field's answer.
    FieldDependency: Modifies a field's available options or value based
        on another field's answer.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Survey(models.Model):
    """Top-level survey container created by an admin.

    A survey is composed of ordered :class:`Section` instances, each
    containing :class:`Field` instances.  Its ``status`` controls whether
    customers can submit responses (only ``published`` surveys accept
    submissions).  Transitions are forward-only: draft → published → archived.

    Attributes:
        title (str): The survey's display title (max 255 chars).
        description (str): Optional long-form description.
        created_by (User): FK to the admin who created the survey.
        status (str): One of ``draft``, ``published``, ``archived``.
            Defaults to ``draft``.
        created_at (datetime): Auto-set on creation.
        updated_at (datetime): Auto-set on each save.

    Meta:
        db_table: ``surveys``
        ordering: ``["-created_at"]`` (newest first)
        indexes: ``status``, ``created_by``
    """

    class SurveyStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    ALLOWED_TRANSITIONS = {
        SurveyStatus.DRAFT: {SurveyStatus.PUBLISHED},
        SurveyStatus.PUBLISHED: {SurveyStatus.ARCHIVED},
        SurveyStatus.ARCHIVED: set(),
    }

    title = models.CharField(
        max_length=255,
    )
    description = models.TextField(
        blank=True,
        default="",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="surveys",
    )
    status = models.CharField(
        max_length=20,
        choices=SurveyStatus.choices,
        default=SurveyStatus.DRAFT,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "surveys"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_by"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        """Return the survey title."""
        return self.title

    @property
    def conditional_rules(self):
        """All conditional rules for this survey's sections and fields."""
        return self.conditional_rules_direct.all()

    @property
    def field_dependencies(self):
        """All field dependencies for this survey's fields."""
        return self.field_dependencies_direct.all()

    def transition_to(self, new_status):
        """Transition the survey to a new status.

        Validates that the transition is allowed and, for publishing,
        that the survey has at least one section with at least one field.

        Args:
            new_status (str): The target status value.

        Raises:
            ValidationError: If the transition is not allowed or the
                survey is not ready to be published.
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValidationError(
                f"Cannot transition from '{self.status}' to '{new_status}'."
            )

        if new_status == self.SurveyStatus.PUBLISHED:
            sections = list(self.sections.prefetch_related("fields"))
            if not sections:
                raise ValidationError(
                    "Cannot publish a survey without at least one section."
                )
            empty_sections = [s for s in sections if not s.fields.all()]
            if empty_sections:
                titles = ", ".join(s.title for s in empty_sections)
                raise ValidationError(
                    f"Cannot publish: the following sections have no fields: {titles}."
                )

        self.status = new_status
        self.save(update_fields=["status"])


class Section(models.Model):
    """An ordered group of fields within a survey.

    Sections divide a survey into logical parts.  Each section has a
    unique ``order`` within its parent survey, enforced by a database
    constraint.

    Attributes:
        survey (Survey): FK to the parent survey.
        title (str): Section heading (max 255 chars).
        description (str): Optional description.
        order (int): Positive integer defining display order.

    Meta:
        db_table: ``survey_sections``
        unique_together: ``(survey, order)``
        ordering: ``["order"]``
    """

    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, related_name="sections"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        default="",
    )
    order = models.PositiveIntegerField()

    class Meta:
        db_table = "survey_sections"
        unique_together = [("survey", "order")]
        ordering = ["order"]

    def __str__(self):
        """Return ``'Survey Title - Section Title'``."""
        return f"{self.survey.title} - {self.title}"


class Field(models.Model):
    """A single input field within a survey section.

    Supports eight field types (see :class:`FieldType`) and optional
    per-field validation rules stored as JSON.  Fields marked with
    ``is_encrypted=True`` will have their response values encrypted at
    rest using Fernet symmetric encryption.

    Attributes:
        section (Section): FK to the parent section.
        label (str): Display label for the field (max 255 chars).
        field_type (str): One of the :class:`FieldType` choices.
        required (bool): Whether the field must be answered.
        order (int): Display order within the section.
        options (list[str]): Available choices for ``dropdown``, ``radio``,
            and ``checkbox`` types.  Empty list for free-text types.
        is_encrypted (bool): If ``True``, response values are encrypted
            before storage.
        validation_rules (dict): Optional rules such as ``min``, ``max``,
            ``min_length``, ``max_length``, ``regex``.

    Meta:
        db_table: ``survey_fields``
        unique_together: ``(section, order)``
        ordering: ``["order"]``
    """

    class FieldType(models.TextChoices):
        """Supported field input types."""

        TEXT = "text", "Text"
        NUMBER = "number", "Number"
        DATE = "date", "Date"
        DROPDOWN = "dropdown", "Dropdown"
        CHECKBOX = "checkbox", "Checkbox"
        RADIO = "radio", "Radio"
        TEXTAREA = "textarea", "Textarea"
        EMAIL = "email", "Email"

    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    label = models.CharField(
        max_length=255,
    )
    field_type = models.CharField(
        max_length=20,
        choices=FieldType.choices,
    )
    required = models.BooleanField(
        default=False,
    )
    order = models.PositiveIntegerField()
    options = models.JSONField(
        blank=True,
        default=list,
        help_text="Options for dropdown/radio/checkbox fields",
    )
    is_encrypted = models.BooleanField(
        default=False,
    )
    validation_rules = models.JSONField(
        blank=True,
        default=dict,
        help_text="Validation rules: min, max, min_length, max_length, regex",
    )

    class Meta:
        db_table = "survey_fields"
        unique_together = [("section", "order")]
        ordering = ["order"]

    def __str__(self):
        """Return ``'Section Title - Field Label'``."""
        return f"{self.section.title} - {self.label}"


class ComparisonOperator(models.TextChoices):
    """Comparison operators for ConditionalRule and FieldDependency."""

    EQUALS = "equals", "Equals"
    NOT_EQUALS = "not_equals", "Not Equals"
    CONTAINS = "contains", "Contains"
    GREATER_THAN = "greater_than", "Greater Than"
    LESS_THAN = "less_than", "Less Than"
    IN = "in", "In"


class ConditionalRule(models.Model):
    """Rule that controls visibility of a section or field.

    A conditional rule makes a target section **or** a target field visible
    only when the ``depends_on_field`` answer satisfies the given
    ``operator`` / ``value`` condition.  Exactly one of ``target_section``
    or ``target_field`` must be set.

    Sections or fields without any conditional rules are always visible.
    If multiple rules target the same entity, it is shown when **any** rule
    is satisfied (OR logic).

    Attributes:
        survey (Survey): Denormalized FK to the parent survey for efficient
            querying.  Must match ``depends_on_field.section.survey``.
        target_section (Section | None): The section to conditionally show.
        target_field (Field | None): The field to conditionally show.
        depends_on_field (Field): The field whose answer is evaluated.
        operator (str): Comparison operator (see :class:`ComparisonOperator`).
        value (JSON): The expected value to compare against (e.g. a string
        for ``EQUALS``, a list for ``IN`` or a number for ``GREATER_THAN``).

    Meta:
        db_table: ``conditional_rules``
    """

    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name="conditional_rules_direct",
    )
    target_section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="conditional_rules",
        null=True,
        blank=True,
    )
    target_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        related_name="conditional_rules",
        null=True,
        blank=True,
    )
    depends_on_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        related_name="dependant_rules",
    )
    operator = models.CharField(
        max_length=20,
        choices=ComparisonOperator.choices,
    )
    value = models.JSONField()

    class Meta:
        db_table = "conditional_rules"

    def clean(self):
        """Ensure exactly one of target_section or target_field is set and survey matches."""
        if bool(self.target_section) == bool(self.target_field):
            raise ValidationError(
                "Exactly one of target_section or target_field must be set."
            )
        if (
            self.depends_on_field_id
            and self.survey_id
            and self.depends_on_field.section.survey_id != self.survey_id
        ):
            raise ValidationError(
                "survey must match depends_on_field's survey."
            )

    def __str__(self):
        """Return a human-readable rule description."""
        target = self.target_section or self.target_field
        return f"If {self.depends_on_field.label} {self.operator} {self.value} → show {target}"


class FieldDependency(models.Model):
    """Cross-field dependency that modifies a field's options or value.

    Unlike :class:`ConditionalRule` (which shows/hides entire elements),
    a field dependency dynamically alters the **behaviour** of the
    ``dependent_field`` -- for example restricting the available dropdown
    options -- when the ``depends_on_field`` answer meets the condition.

    Attributes:
        survey (Survey): Denormalized FK to the parent survey for efficient
            querying.  Must match ``dependent_field.section.survey``.
        dependent_field (Field): The field whose options/value are modified.
        depends_on_field (Field): The field whose answer triggers the
            modification.
        operator (str): Comparison operator (see :class:`ComparisonOperator`).
        value (JSON): Expected value for the condition.
        action (str): The modification type (see :class:`Action`).
        action_value (JSON): Data for the action (e.g. a list of allowed
            options for ``show_options`` or a value for ``set_value``).

    Meta:
        db_table: ``field_dependencies``
    """

    class Action(models.TextChoices):
        """Actions to apply when the dependency condition is met."""

        SHOW_OPTIONS = "show_options", "Show Options"
        HIDE_OPTIONS = "hide_options", "Hide Options"
        SET_VALUE = "set_value", "Set Value"

    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name="field_dependencies_direct",
    )
    dependent_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        related_name="dependencies",
    )
    depends_on_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        related_name="dependants",
    )
    operator = models.CharField(
        max_length=20,
        choices=ComparisonOperator.choices,
    )
    value = models.JSONField()
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )
    action_value = models.JSONField()

    class Meta:
        db_table = "field_dependencies"
        verbose_name_plural = "Field dependencies"

    def clean(self):
        """Ensure survey matches dependent_field's survey."""
        super().clean()
        if (
            self.dependent_field_id
            and self.survey_id
            and self.dependent_field.section.survey_id != self.survey_id
        ):
            raise ValidationError(
                "survey must match dependent_field's survey."
            )

    def __str__(self):
        """Return a human-readable dependency description."""
        return (
            f"If {self.depends_on_field.label} {self.operator} {self.value} "
            f"→ {self.action} on {self.dependent_field.label}"
        )
