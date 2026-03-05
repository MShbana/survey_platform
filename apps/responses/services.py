"""Business logic for response validation, encryption.

This module contains the core submission processing pipeline:

1. **Encryption**: Fernet-based symmetric encryption for sensitive field
   values (``encrypt_value`` / ``decrypt_value``).
2. **Validation**: Full survey submission validation including type
   checking, custom rules, conditional visibility, and dependency
   constraint enforcement (``validate_submission``).


Functions:
    encrypt_value: Encrypt a plaintext value using Fernet.
    decrypt_value: Decrypt a Fernet-encrypted value.
    validate_submission: Validate a complete survey submission.

Classes:
    ValidationError: Raised when submission validation fails.
"""

import json
import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from cryptography.fernet import Fernet

from apps.surveys.models import Field

logger = logging.getLogger(__name__)

from apps.surveys.services import (
    get_visible_fields,
    get_visible_sections,
    prefetch_survey_structure,
    resolve_dependencies,
)
from apps.surveys.constants import ValidationRuleKey


def _get_fernet():
    """Create and return a Fernet cipher instance.

    Reads the ``ENCRYPTION_KEY`` from Django settings.  The key must be
    a valid Fernet key (URL-safe base64-encoded 32-byte key).

    Returns:
        Fernet: A configured cipher instance.

    Raises:
        ValueError: If ``ENCRYPTION_KEY`` is empty or not configured.
    """
    key = settings.ENCRYPTION_KEY
    if not key:
        logger.error("ENCRYPTION_KEY is not configured")
        raise ValueError("ENCRYPTION_KEY is not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(value):
    """Encrypt a plaintext value using Fernet symmetric encryption.

    Args:
        value (str): The plaintext value to encrypt.

    Returns:
        str: The encrypted ciphertext as a UTF-8 string.

    Raises:
        ValueError: If ``ENCRYPTION_KEY`` is not configured.
    """
    try:
        f = _get_fernet()
        return f.encrypt(str(value).encode()).decode()
    except Exception:
        logger.error("Encryption failure", exc_info=True)
        raise


def decrypt_value(value):
    """Decrypt a Fernet-encrypted value back to plaintext.

    Args:
        value (str): The encrypted ciphertext string.

    Returns:
        str: The decrypted plaintext value.

    Raises:
        ValueError: If ``ENCRYPTION_KEY`` is not configured.
        cryptography.fernet.InvalidToken: If the ciphertext is invalid
            or was encrypted with a different key.
    """
    try:
        f = _get_fernet()
        return f.decrypt(value.encode()).decode()
    except Exception:
        logger.error("Decryption failure", exc_info=True)
        raise


class ValidationError(Exception):
    """Raised when survey submission validation fails.

    Attributes:
        errors (dict[str, str]): Mapping of field ID (as string) to the
            validation error message for that field.
    """

    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


def validate_submission(survey, answers_dict):
    """Validate a complete survey submission against all business rules.

    Performs the following validation steps using prefetched survey data
    (~5 queries total, avoiding N+1):

    1. **Visibility**: Determines which sections and fields are visible
       based on conditional rules and the submitted answers.
    2. **Required check**: Ensures all required visible fields have values.
    3. **Type validation**: Validates values match their field type (e.g.
       numbers are numeric, emails match a pattern, dates are YYYY-MM-DD).
    4. **Custom rules**: Applies ``validation_rules`` (min, max, min_length,
       max_length, regex).
    5. **Dependency constraints**: Enforces option restrictions from active
       field dependencies (show_options / hide_options).

    Args:
        survey (Survey): The survey instance being submitted to.
        answers_dict (dict[str, Any]): Mapping from field ID (as string)
            to the submitted answer value.

    Returns:
        dict[str, Any]: Cleaned answers containing only visible, validated
        fields.  Keys are field IDs as strings.

    Raises:
        ValidationError: If any field fails validation.  The exception's
        ``errors`` attribute contains a ``{field_id: message}`` dict.

    Examples:
        >>> cleaned = validate_submission(survey, {"1": "Alice", "2": "30"})
        >>> cleaned
        {"1": "Alice", "2": "30"}
    """
    logger.debug(
        "validate_submission started: survey_id=%s, answer_count=%d",
        survey.pk,
        len(answers_dict),
    )
    errors = {}

    # Prefetch all structure in ~5 queries
    sections, fields, section_rules, field_rules, dependencies = (
        prefetch_survey_structure(survey)
    )

    # Build lookup structures
    fields_by_section = {}
    fields_by_id = {}
    for field in fields:
        fields_by_section.setdefault(field.section_id, []).append(field)
        fields_by_id[field.id] = field

    visible_section_ids = set(
        get_visible_sections(
            survey,
            answers_dict,
            sections=sections,
            section_rules=section_rules,
        )
    )

    all_visible_field_ids = set()
    for section in sections:
        if section.id not in visible_section_ids:
            continue
        section_fields = fields_by_section.get(section.id, [])
        visible_ids = get_visible_fields(
            section,
            answers_dict,
            fields=section_fields,
            field_rules=field_rules,
        )
        all_visible_field_ids.update(visible_ids)

    modifications = resolve_dependencies(
        survey,
        answers_dict,
        dependencies=dependencies,
    )

    cleaned = {}

    for field_id in all_visible_field_ids:
        field = fields_by_id[field_id]
        field_id_str = str(field.id)
        value = answers_dict.get(field_id_str)

        # Check required
        if field.required and (value is None or str(value).strip() == ""):
            errors[field_id_str] = "This field is required."
            continue

        if value is None or str(value).strip() == "":
            continue

        value_str = str(value)

        # Validate field type
        field_error = _validate_field_type(field, value, value_str)
        if field_error:
            errors[field_id_str] = field_error
            continue

        # Validate validation_rules
        rule_error = _validate_rules(field, value, value_str)
        if rule_error:
            errors[field_id_str] = rule_error
            continue

        # Validate dependency constraints (option restrictions)
        dep_error = _validate_dependency_options(field, value, modifications)
        if dep_error:
            errors[field_id_str] = dep_error
            continue

        cleaned[field_id_str] = value

    if errors:
        logger.warning(
            "Validation failed: survey_id=%s, failed_field_ids=%s",
            survey.pk,
            list(errors.keys()),
        )
        raise ValidationError(errors)

    return cleaned


def _validate_field_type(field, value, value_str):
    """Validate that a value matches the expected field type.

    Args:
        field (Field): The field definition.
        value (Any): The raw submitted value.
        value_str (str): The value coerced to string.

    Returns:
        str | None: An error message if validation fails, or ``None``
        if the value is valid.
    """
    if field.field_type == Field.FieldType.NUMBER:
        try:
            float(value_str)
        except (ValueError, TypeError):
            return "Must be a number."
    elif field.field_type == Field.FieldType.EMAIL:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value_str):
            return "Invalid email address."
    elif field.field_type == Field.FieldType.DATE:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value_str):
            return "Invalid date format. Use YYYY-MM-DD."
    elif field.field_type in (Field.FieldType.DROPDOWN, Field.FieldType.RADIO):
        if value_str not in [str(o) for o in field.options]:
            return f"Invalid choice. Must be one of: {field.options}"
    elif field.field_type == Field.FieldType.CHECKBOX:
        if not isinstance(value, list):
            return "Checkbox value must be a list."
        valid_options = [str(o) for o in field.options]
        invalid = [str(v) for v in value if str(v) not in valid_options]
        if invalid:
            return f"Invalid choices: {invalid}. Must be from: {field.options}"
    return None


def _validate_rules(field, value, value_str):
    """Apply custom validation rules defined on the field.

    Supports the following rule keys in ``field.validation_rules``:
        - ``min_length`` (int): Minimum string length.
        - ``max_length`` (int): Maximum string length.
        - ``min`` (number): Minimum numeric value.
        - ``max`` (number): Maximum numeric value.
        - ``regex`` (str): Regular expression the value must match.

    Args:
        field (Field): The field definition with ``validation_rules``.
        value (Any): The raw submitted value.
        value_str (str): The value coerced to string.

    Returns:
        str | None: An error message if a rule is violated, or ``None``.
    """
    rules = field.validation_rules
    if not rules:
        return None

    if ValidationRuleKey.MIN_LENGTH in rules and len(value_str) < rules[ValidationRuleKey.MIN_LENGTH]:
        return f"Minimum length is {rules[ValidationRuleKey.MIN_LENGTH]}."
    if ValidationRuleKey.MAX_LENGTH in rules and len(value_str) > rules[ValidationRuleKey.MAX_LENGTH]:
        return f"Maximum length is {rules[ValidationRuleKey.MAX_LENGTH]}."
    if ValidationRuleKey.MIN in rules:
        try:
            if float(value_str) < float(rules[ValidationRuleKey.MIN]):
                return f"Minimum value is {rules[ValidationRuleKey.MIN]}."
        except (ValueError, TypeError):
            pass
    if ValidationRuleKey.MAX in rules:
        try:
            if float(value_str) > float(rules[ValidationRuleKey.MAX]):
                return f"Maximum value is {rules[ValidationRuleKey.MAX]}."
        except (ValueError, TypeError):
            pass
    if ValidationRuleKey.REGEX in rules:
        if not re.match(rules[ValidationRuleKey.REGEX], value_str):
            return "Value does not match required pattern."
    return None


def _validate_dependency_options(field, value, modifications):
    """Check that the submitted value respects active dependency constraints.

    When a field dependency with ``show_options`` or ``hide_options`` is
    active, this function verifies that the submitted value only includes
    allowed options.

    Args:
        field (Field): The dependent field.
        value (Any): The submitted value (string or list for checkboxes).
        modifications (dict[int, list[dict]]): Active dependency
            modifications from :func:`~apps.surveys.services.resolve_dependencies`.

    Returns:
        str | None: An error message if a constraint is violated, or ``None``.
    """
    field_mods = modifications.get(field.id)
    if not field_mods:
        return None

    for mod in field_mods:
        action = mod["action"]
        action_value = mod["action_value"]
        if action == "show_options":
            allowed = [str(o) for o in action_value]
            check = value if isinstance(value, list) else [value]
            invalid = [str(v) for v in check if str(v) not in allowed]
            if invalid:
                return f"Invalid choices given current conditions: {invalid}"
        elif action == "hide_options":
            hidden = [str(o) for o in action_value]
            check = value if isinstance(value, list) else [value]
            blocked = [str(v) for v in check if str(v) in hidden]
            if blocked:
                return f"Options not available given current conditions: {blocked}"
    return None


def _serialize_value(value):
    """Convert a submission value to a string for storage.

    Lists (e.g. checkbox answers) are serialized as JSON so they can be
    reliably parsed back, rather than using Python's repr().
    """
    if isinstance(value, list):
        return json.dumps(value)
    return str(value)


def create_submission(*, survey, user, cleaned_answers, survey_fields):
    """Create a SurveyResponse with its FieldResponses atomically.

    Encrypts values for fields marked ``is_encrypted`` and bulk-creates
    all FieldResponse records within a single database transaction.

    Args:
        survey: The Survey being responded to.
        user: The user submitting the response.
        cleaned_answers: Dict of ``{field_id_str: value}`` after validation.
        survey_fields: Dict of ``{field_id: Field}`` for encryption lookup.

    Returns:
        SurveyResponse: The newly created response.
    """
    from .models import FieldResponse, SurveyResponse

    try:
        with transaction.atomic():
            survey_response = SurveyResponse.objects.create(survey=survey, user=user)

            field_responses = []
            for field_id_str, value in cleaned_answers.items():
                field = survey_fields[int(field_id_str)]
                store_value = _serialize_value(value)
                if field.is_encrypted:
                    try:
                        store_value = encrypt_value(store_value)
                    except Exception:
                        logger.error(
                            "Encryption failed for field_id=%s during submission",
                            field.id,
                            exc_info=True,
                        )
                        raise ValidationError(
                            {field_id_str: "Unable to process this field. Please try again later."}
                        )
                field_responses.append(
                    FieldResponse(
                        survey_response=survey_response,
                        field_id=field.id,
                        value=store_value,
                    )
                )
            FieldResponse.objects.bulk_create(field_responses)
    except IntegrityError:
        raise ValidationError(
            {"survey": "You have already submitted a response to this survey."}
        )

    return survey_response
