"""Business logic for conditional visibility and field dependency evaluation.

This module implements the core survey logic that determines which sections
and fields are visible to a respondent based on their answers, and how
field options are modified by cross-field dependencies.

Functions:
    evaluate_condition: Evaluate a single rule against submitted answers.
    prefetch_survey_structure: Load all survey data in minimal queries.
    get_visible_sections: Determine which sections are visible.
    get_visible_fields: Determine which fields are visible.
    resolve_dependencies: Compute option modifications for dependent fields.
"""

import logging
import re
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .cache import SurveyCacheService
from .models import (
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
    ComparisonOperator,
)
from .constants import ValidationRuleKey, VALIDATION_RULE_KEYS


CHOICE_TYPES = {
    Field.FieldType.DROPDOWN,
    Field.FieldType.RADIO,
    Field.FieldType.CHECKBOX,
}
TEXT_TYPES = {
    Field.FieldType.TEXT,
    Field.FieldType.TEXTAREA,
    Field.FieldType.EMAIL,
}
NUMERIC_TYPES = {
    Field.FieldType.NUMBER,
}


logger = logging.getLogger(__name__)


def evaluate_condition(rule: ConditionalRule | FieldDependency, answers):
    """Evaluate a conditional rule against submitted answers.

    Compares the respondent's answer for ``rule.depends_on_field`` against
    ``rule.value`` using ``rule.operator``.

    Args:
        rule (ConditionalRule | FieldDependency): The rule object containing
            ``depends_on_field_id``, ``operator``, and ``value``.
        answers (dict[str, Any]): Mapping from field ID (as string) to the
            respondent's answer value.

    Returns:
        bool: ``True`` if the condition is satisfied, ``False`` otherwise.

    Notes:
        - Returns ``False`` if the answer for the depended-on field is
          missing (``None``).
        - All comparisons coerce values to ``str`` for equality checks.
        - For ``greater_than`` and ``less_than``, values are coerced to
          ``float``.  Non-numeric values return ``False``.
        - The ``in`` operator expects ``rule.value`` to be a list.  If
          it is a string, Python's ``in`` operator is used directly.
        - The ``contains`` operator checks if the expected value is a
          substring of the answer.

    Examples:
        >>> from unittest.mock import Mock
        >>> rule = Mock(depends_on_field_id=1, operator=ComparisonOperator.EQUALS, value="yes")
        >>> evaluate_condition(rule, {"1": "yes"})
        True
        >>> evaluate_condition(rule, {"1": "no"})
        False
    """
    field_id = str(rule.depends_on_field_id)
    answer = answers.get(field_id)

    if answer is None:
        return False

    operator = rule.operator
    expected = rule.value

    if operator == ComparisonOperator.EQUALS:
        return str(answer) == str(expected)
    elif operator == ComparisonOperator.NOT_EQUALS:
        return str(answer) != str(expected)
    elif operator == ComparisonOperator.CONTAINS:
        return str(expected) in str(answer)
    elif operator == ComparisonOperator.GREATER_THAN:
        try:
            return float(answer) > float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == ComparisonOperator.LESS_THAN:
        try:
            return float(answer) < float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == ComparisonOperator.IN:
        if isinstance(expected, list):
            return str(answer) in [str(v) for v in expected]
        return str(answer) in str(expected)
    return False


def prefetch_survey_structure(survey):
    """Load all survey structure data in minimal database queries.

    Fetches sections, fields, conditional rules, and field dependencies
    for the given survey in approximately 5 queries (one per entity type),
    avoiding N+1 patterns during submission validation.

    Args:
        survey (Survey): The survey instance to load structure for.

    Returns:
        tuple: A 5-element tuple containing:
            - **sections** (list[Section]): All sections ordered by position.
            - **fields** (list[Field]): All fields with ``section``
              pre-fetched, ordered by section then field position.
            - **section_rules** (list[ConditionalRule]): Rules targeting
              sections.
            - **field_rules** (list[ConditionalRule]): Rules targeting
              fields.
            - **dependencies** (list[FieldDependency]): All field
              dependencies.
    """
    sections = list(Section.objects.filter(survey=survey).order_by("order"))

    fields = list(
        Field.objects.filter(section__survey=survey)
        .select_related("section")
        .order_by("section__order", "order")
    )

    section_rules = list(
        ConditionalRule.objects.filter(
            survey=survey,
            target_section__isnull=False,
        ).select_related("depends_on_field")
    )

    field_rules = list(
        ConditionalRule.objects.filter(
            survey=survey,
            target_field__isnull=False,
        ).select_related("depends_on_field")
    )

    dependencies = list(
        FieldDependency.objects.filter(
            survey=survey,
        ).select_related("dependent_field", "depends_on_field")
    )

    logger.debug(
        "prefetch_survey_structure: survey_id=%s, sections=%d, fields=%d, section_rules=%d, field_rules=%d, dependencies=%d",
        survey.pk,
        len(sections),
        len(fields),
        len(section_rules),
        len(field_rules),
        len(dependencies),
    )
    return sections, fields, section_rules, field_rules, dependencies


def get_visible_sections(survey, answers, *, sections=None, section_rules=None):
    """Determine which sections are visible given the respondent's answers.

    A section is visible if:
      - It has **no** conditional rules (unconditionally visible), **or**
      - **At least one** of its conditional rules evaluates to ``True``
        (OR logic).

    Args:
        survey (Survey): The survey instance.
        answers (dict[str, Any]): Field ID → answer mapping.
        sections (list[Section] | None): Pre-fetched sections.  If
            ``None``, fetched from the database.
        section_rules (list[ConditionalRule] | None): Pre-fetched rules
            targeting sections.  If ``None``, fetched from the database.

    Returns:
        list[int]: IDs of the visible sections.
    """
    if sections is None:
        sections = survey.sections.all()
    if section_rules is None:
        section_rules = ConditionalRule.objects.filter(
            target_section__in=sections,
        ).select_related("depends_on_field")

    rules_by_section = {}
    for rule in section_rules:
        rules_by_section.setdefault(rule.target_section_id, []).append(rule)

    visible = []
    for section in sections:
        section_rules_list = rules_by_section.get(section.id)
        if not section_rules_list:
            visible.append(section.id)
        elif any(evaluate_condition(r, answers) for r in section_rules_list):
            visible.append(section.id)

    logger.debug("Visible sections: %s", visible)
    return visible


def get_visible_fields(section, answers, *, fields=None, field_rules=None):
    """Determine which fields in a section are visible given the answers.

    A field is visible if:
      - It has **no** conditional rules (unconditionally visible), **or**
      - **At least one** of its conditional rules evaluates to ``True``
        (OR logic).

    Args:
        section (Section): The section whose fields to evaluate.
        answers (dict[str, Any]): Field ID → answer mapping.
        fields (list[Field] | None): Pre-fetched fields for this section.
            If ``None``, fetched via ``section.fields.all()``.
        field_rules (list[ConditionalRule] | None): Pre-fetched rules
            targeting fields.  If ``None``, fetched from the database.

    Returns:
        list[int]: IDs of the visible fields.
    """
    if fields is None:
        fields = section.fields.all()
    if field_rules is None:
        field_rules = ConditionalRule.objects.filter(
            target_field__in=fields,
        ).select_related("depends_on_field")

    rules_by_field = {}
    for rule in field_rules:
        rules_by_field.setdefault(rule.target_field_id, []).append(rule)

    visible = []
    for field in fields:
        field_rules_list = rules_by_field.get(field.id)
        if not field_rules_list:
            visible.append(field.id)
        elif any(evaluate_condition(r, answers) for r in field_rules_list):
            visible.append(field.id)

    logger.debug("Visible fields for section_id=%s: %s", section.id, visible)
    return visible


def resolve_dependencies(survey, answers, *, dependencies=None):
    """Compute field modifications triggered by active dependencies.

    For each :class:`~apps.surveys.models.FieldDependency` whose condition
    is met, records the ``action`` and ``action_value`` keyed by the
    dependent field's ID.

    Args:
        survey (Survey): The survey instance.
        answers (dict[str, Any]): Field ID → answer mapping.
        dependencies (list[FieldDependency] | None): Pre-fetched
            dependencies.  If ``None``, fetched from the database.

    Returns:
        dict[int, list[dict]]: Mapping of ``dependent_field.id`` to a list
        of ``{"action": str, "action_value": Any}`` dicts for each
        satisfied dependency.

    Examples:
        >>> mods = resolve_dependencies(survey, {"1": "USA"})
        >>> mods[5]
        [{"action": "show_options", "action_value": ["NY", "CA", "TX"]}]
    """
    if dependencies is None:
        dependencies = FieldDependency.objects.filter(
            survey=survey,
        ).select_related("dependent_field", "depends_on_field")

    modifications = {}
    for dep in dependencies:
        if evaluate_condition(dep, answers):
            field_id = dep.dependent_field_id
            modifications.setdefault(field_id, []).append(
                {
                    "action": dep.action,
                    "action_value": dep.action_value,
                }
            )

    logger.debug("Dependency modifications resolved: count=%d", len(modifications))
    return modifications


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_field_options(field_type, options):
    """Validate options based on field type.

    Choice fields (dropdown, radio, checkbox) must have non-empty options.
    Non-choice fields must NOT have options.
    Options must not contain duplicates.

    Raises:
        ValidationError: On constraint violations.
    """
    if field_type in CHOICE_TYPES:
        if not options:
            raise ValidationError(
                {
                    "options": "Options are required for dropdown, radio, and checkbox fields."
                }
            )
        for opt in options:
            if not isinstance(opt, (str, int, float)):
                raise ValidationError(
                    {"options": "Each option must be a string or number."}
                )
        if len(options) != len(set(str(o) for o in options)):
            raise ValidationError({"options": "Options must not contain duplicates."})
    elif options:
        raise ValidationError(
            {"options": f"Options are not allowed for '{field_type}' fields."}
        )


def validate_validation_rules(field_type, rules):
    """Validate validation_rules schema and cross-check against field type.

    Raises:
        ValidationError: On invalid keys, types, or combinations.
    """
    if not rules:
        return

    if not isinstance(rules, dict):
        raise ValidationError({"validation_rules": "Must be a JSON object."})

    unknown_keys = set(rules.keys()) - VALIDATION_RULE_KEYS
    if unknown_keys:
        raise ValidationError(
            {
                "validation_rules": f"Unknown keys: {', '.join(sorted(unknown_keys))}. "
                f"Allowed: {', '.join(sorted(VALIDATION_RULE_KEYS))}."
            }
        )

    errors = {}

    # min/max only for number fields
    has_min = ValidationRuleKey.MIN in rules
    has_max = ValidationRuleKey.MAX in rules
    if has_min or has_max:
        if field_type not in NUMERIC_TYPES:
            errors["validation_rules"] = (
                f"'min'/'max' are only allowed for number fields, not '{field_type}'."
            )
        else:
            if has_min and not isinstance(rules[ValidationRuleKey.MIN], (int, float)):
                errors["validation_rules"] = "'min' must be a number."
            if has_max and not isinstance(rules[ValidationRuleKey.MAX], (int, float)):
                errors["validation_rules"] = "'max' must be a number."
            if has_min and has_max and not errors:
                if rules[ValidationRuleKey.MIN] > rules[ValidationRuleKey.MAX]:
                    errors["validation_rules"] = (
                        "'min' must be less than or equal to 'max'."
                    )

    # min_length/max_length only for text types
    has_min_len = ValidationRuleKey.MIN_LENGTH in rules
    has_max_len = ValidationRuleKey.MAX_LENGTH in rules
    if has_min_len or has_max_len:
        if field_type not in TEXT_TYPES:
            errors.setdefault(
                "validation_rules",
                f"'min_length'/'max_length' are only allowed for text/textarea/email fields, not '{field_type}'.",
            )
        else:
            if has_min_len:
                if not isinstance(rules[ValidationRuleKey.MIN_LENGTH], int) or rules[ValidationRuleKey.MIN_LENGTH] < 0:
                    errors["validation_rules"] = (
                        "'min_length' must be a non-negative integer."
                    )
            if has_max_len:
                if not isinstance(rules[ValidationRuleKey.MAX_LENGTH], int) or rules[ValidationRuleKey.MAX_LENGTH] < 0:
                    errors.setdefault(
                        "validation_rules",
                        "'max_length' must be a non-negative integer.",
                    )
            if has_min_len and has_max_len and "validation_rules" not in errors:
                if rules[ValidationRuleKey.MIN_LENGTH] > rules[ValidationRuleKey.MAX_LENGTH]:
                    errors["validation_rules"] = (
                        "'min_length' must be less than or equal to 'max_length'."
                    )

    # regex only for text types
    if ValidationRuleKey.REGEX in rules:
        if field_type not in TEXT_TYPES:
            errors.setdefault(
                "validation_rules",
                f"'regex' is only allowed for text/textarea/email fields, not '{field_type}'.",
            )
        elif not isinstance(rules[ValidationRuleKey.REGEX], str):
            errors.setdefault("validation_rules", "'regex' must be a string.")
        else:
            try:
                re.compile(rules[ValidationRuleKey.REGEX])
            except re.error:
                errors.setdefault(
                    "validation_rules", f"'regex' is not a valid regular expression."
                )

    if errors:
        raise ValidationError(errors)


def validate_operator_value(depends_on_field, operator, value):
    """Validate operator and value are compatible with the depends_on_field type.

    Raises:
        ValidationError: On incompatible operator/value combinations.
    """
    field_type = depends_on_field.field_type
    field_options = depends_on_field.options or []

    # ComparisonOperator restrictions by field type
    numeric_only_ops = {ComparisonOperator.GREATER_THAN, ComparisonOperator.LESS_THAN}
    if field_type in TEXT_TYPES and operator in numeric_only_ops:
        raise ValidationError(
            f"ComparisonOperator '{operator}' is not allowed for '{field_type}' fields."
        )
    if field_type in CHOICE_TYPES and operator in numeric_only_ops:
        raise ValidationError(
            f"ComparisonOperator '{operator}' is not allowed for '{field_type}' fields."
        )

    # Value validation by field type
    if field_type in NUMERIC_TYPES:
        if operator == ComparisonOperator.IN:
            if not isinstance(value, list):
                raise ValidationError("Value must be a list for 'in' operator.")
            for v in value:
                if not isinstance(v, (int, float)):
                    raise ValidationError(
                        "All values in 'in' list must be numeric for number fields."
                    )
        elif operator not in (ComparisonOperator.CONTAINS,):
            if not isinstance(value, (int, float)):
                try:
                    float(value)
                except (ValueError, TypeError):
                    raise ValidationError("Value must be numeric for number fields.")

    elif field_type == Field.FieldType.DATE:
        if operator == ComparisonOperator.IN:
            if not isinstance(value, list):
                raise ValidationError("Value must be a list for 'in' operator.")
            for v in value:
                _validate_date_string(v)
        elif operator not in (ComparisonOperator.CONTAINS,):
            _validate_date_string(value)

    elif field_type in CHOICE_TYPES:
        if operator == ComparisonOperator.IN:
            if not isinstance(value, list):
                raise ValidationError("Value must be a list for 'in' operator.")
            if field_options:
                for v in value:
                    if str(v) not in [str(o) for o in field_options]:
                        raise ValidationError(
                            f"Value '{v}' is not a valid option for field '{depends_on_field.label}'."
                        )
        elif operator in (ComparisonOperator.EQUALS, ComparisonOperator.NOT_EQUALS):
            if field_type == Field.FieldType.CHECKBOX:
                pass  # checkbox equals can be a list
            elif field_options and str(value) not in [str(o) for o in field_options]:
                raise ValidationError(
                    f"Value '{value}' is not a valid option for field '{depends_on_field.label}'."
                )
        elif operator == ComparisonOperator.CONTAINS and field_options:
            if str(value) not in [str(o) for o in field_options]:
                raise ValidationError(
                    f"Value '{value}' is not a valid option for field '{depends_on_field.label}'."
                )


def _validate_date_string(value):
    """Validate a value is a YYYY-MM-DD date string."""
    if not isinstance(value, str):
        raise ValidationError("Date values must be strings in YYYY-MM-DD format.")
    try:
        from datetime import date

        date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValidationError(f"'{value}' is not a valid date (expected YYYY-MM-DD).")


def validate_ordering_constraint(
    depends_on_field, target_section=None, target_field=None
):
    """Validate that depends_on_field appears before the target.

    For section targets: depends_on_field's section must be strictly before target_section.
    For field targets in same section: depends_on_field's order must be less.
    For field targets in different section: depends_on_field's section order must be less.

    Raises:
        ValidationError: If ordering constraint is violated.
    """
    source_section = depends_on_field.section

    if target_section:
        if source_section.order >= target_section.order:
            raise ValidationError(
                "depends_on_field's section must appear before the target_section "
                f"(section order {source_section.order} >= {target_section.order})."
            )

    if target_field:
        target_section_obj = target_field.section
        if source_section.id == target_section_obj.id:
            # Same section: field order matters
            if depends_on_field.order >= target_field.order:
                raise ValidationError(
                    "depends_on_field must appear before target_field within the same section "
                    f"(field order {depends_on_field.order} >= {target_field.order})."
                )
        else:
            # Different sections: section order matters
            if source_section.order >= target_section_obj.order:
                raise ValidationError(
                    "depends_on_field's section must appear before target_field's section "
                    f"(section order {source_section.order} >= {target_section_obj.order})."
                )


def validate_fd_ordering_constraint(depends_on_field, dependent_field):
    """Validate ordering for field dependencies.

    Raises:
        ValidationError: If depends_on_field doesn't appear before dependent_field.
    """
    source_section = depends_on_field.section
    target_section = dependent_field.section

    if source_section.id == target_section.id:
        if depends_on_field.order >= dependent_field.order:
            raise ValidationError(
                "depends_on_field must appear before dependent_field within the same section "
                f"(field order {depends_on_field.order} >= {dependent_field.order})."
            )
    else:
        if source_section.order >= target_section.order:
            raise ValidationError(
                "depends_on_field's section must appear before dependent_field's section "
                f"(section order {source_section.order} >= {target_section.order})."
            )


def validate_action_value(action, action_value, dependent_field):
    """Validate FieldDependency action_value based on action type and dependent_field.

    Raises:
        ValidationError: On invalid action_value.
    """
    if action in ("show_options", "hide_options"):
        if dependent_field.field_type not in CHOICE_TYPES:
            raise ValidationError(
                f"'{action}' action requires a choice field (dropdown/radio/checkbox), "
                f"not '{dependent_field.field_type}'."
            )
        if not isinstance(action_value, list) or not action_value:
            raise ValidationError(
                f"action_value for '{action}' must be a non-empty list."
            )
        field_options = dependent_field.options or []
        if field_options:
            for v in action_value:
                if str(v) not in [str(o) for o in field_options]:
                    raise ValidationError(
                        f"action_value '{v}' is not a valid option for field '{dependent_field.label}'. "
                        f"Valid options: {field_options}."
                    )

    elif action == "set_value":
        dep_type = dependent_field.field_type
        dep_options = dependent_field.options or []

        if dep_type in (Field.FieldType.DROPDOWN, Field.FieldType.RADIO):
            if dep_options and str(action_value) not in [str(o) for o in dep_options]:
                raise ValidationError(
                    f"set_value '{action_value}' must be one of the field's options: {dep_options}."
                )
        elif dep_type == Field.FieldType.CHECKBOX:
            if not isinstance(action_value, list):
                raise ValidationError("set_value for checkbox fields must be a list.")
            if dep_options:
                for v in action_value:
                    if str(v) not in [str(o) for o in dep_options]:
                        raise ValidationError(
                            f"set_value item '{v}' must be one of the field's options: {dep_options}."
                        )
        elif dep_type == Field.FieldType.NUMBER:
            if not isinstance(action_value, (int, float)):
                try:
                    float(action_value)
                except (ValueError, TypeError):
                    raise ValidationError(
                        "set_value must be numeric for number fields."
                    )
        elif dep_type == Field.FieldType.EMAIL:
            if not isinstance(action_value, str) or "@" not in action_value:
                raise ValidationError("set_value must be a valid email address.")
        elif dep_type == Field.FieldType.DATE:
            _validate_date_string(action_value)


def validate_self_reference_cr(data):
    """Ensure a ConditionalRule's target_field is not the same as depends_on_field.

    Raises:
        ValidationError: On self-reference.
    """
    target_field = data.get("target_field")
    depends_on = data.get("depends_on_field")
    if target_field and depends_on and target_field.pk == depends_on.pk:
        raise ValidationError(
            "target_field cannot be the same as depends_on_field (self-reference)."
        )


def validate_self_reference_fd(data):
    """Ensure a FieldDependency's dependent_field is not the same as depends_on_field.

    Raises:
        ValidationError: On self-reference.
    """
    dependent = data.get("dependent_field")
    depends_on = data.get("depends_on_field")
    if dependent and depends_on and dependent.pk == depends_on.pk:
        raise ValidationError(
            "dependent_field cannot be the same as depends_on_field (self-reference)."
        )


def detect_circular_dependencies_cr(
    depends_on_field, target_field=None, target_section=None, exclude_rule_id=None
):
    """Detect circular dependencies among ConditionalRules.

    Checks if adding a rule from depends_on_field to target creates a cycle.

    Raises:
        ValidationError: On detected cycle.
    """
    if not target_field:
        return  # Section targets can't create field-level cycles

    # Build a directed graph: field_id -> set of field_ids it depends on
    # A CR says: "target_field is visible only if depends_on_field meets condition"
    # So target_field depends on depends_on_field.
    # A cycle: A depends on B, B depends on A.
    rules = ConditionalRule.objects.filter(
        target_field__isnull=False,
        survey=depends_on_field.section.survey,
    ).select_related("target_field", "depends_on_field")

    graph = defaultdict(set)
    for rule in rules:
        if exclude_rule_id and rule.pk == exclude_rule_id:
            continue
        graph[rule.target_field_id].add(rule.depends_on_field_id)

    # Add the proposed edge
    graph[target_field.pk].add(depends_on_field.pk)

    # DFS cycle detection from target_field
    visited = set()
    path = set()

    def has_cycle(node):
        if node in path:
            return True
        if node in visited:
            return False
        visited.add(node)
        path.add(node)
        for neighbor in graph.get(node, set()):
            if has_cycle(neighbor):
                return True
        path.discard(node)
        return False

    if has_cycle(target_field.pk):
        raise ValidationError("Adding this rule would create a circular dependency.")


def detect_circular_dependencies_fd(
    depends_on_field, dependent_field, exclude_dep_id=None
):
    """Detect circular dependencies among FieldDependencies.

    Raises:
        ValidationError: On detected cycle.
    """
    deps = FieldDependency.objects.filter(
        survey=depends_on_field.section.survey,
    ).select_related("dependent_field", "depends_on_field")

    graph = defaultdict(set)
    for dep in deps:
        if exclude_dep_id and dep.pk == exclude_dep_id:
            continue
        graph[dep.dependent_field_id].add(dep.depends_on_field_id)

    graph[dependent_field.pk].add(depends_on_field.pk)

    visited = set()
    path = set()

    def has_cycle(node):
        if node in path:
            return True
        if node in visited:
            return False
        visited.add(node)
        path.add(node)
        for neighbor in graph.get(node, set()):
            if has_cycle(neighbor):
                return True
        path.discard(node)
        return False

    if has_cycle(dependent_field.pk):
        raise ValidationError(
            "Adding this dependency would create a circular dependency."
        )


def validate_cr_fd_conflict(
    depends_on_field_for_fd, action, action_value, dependent_field_for_fd
):
    """Detect conflict between a FieldDependency and existing ConditionalRules.

    If a FD hides options on a field that a CR depends on, and the CR's value
    is among the hidden options, that's a conflict.

    Raises:
        ValidationError: On detected conflict.
    """
    if action != "hide_options":
        return

    # Find CRs that depend on the FD's dependent_field (the field whose options are being hidden)
    conflicting_rules = ConditionalRule.objects.filter(
        depends_on_field=dependent_field_for_fd,
    )

    hidden_options = set(str(v) for v in (action_value or []))

    for rule in conflicting_rules:
        rule_value = rule.value
        if rule.operator in (
            ComparisonOperator.EQUALS,
            ComparisonOperator.NOT_EQUALS,
            ComparisonOperator.CONTAINS,
        ):
            if str(rule_value) in hidden_options:
                raise ValidationError(
                    f"Hiding option '{rule_value}' on field '{dependent_field_for_fd.label}' "
                    f"conflicts with an existing conditional rule that checks for this value."
                )
        elif rule.operator == ComparisonOperator.IN:
            if isinstance(rule_value, list):
                conflicting = hidden_options & set(str(v) for v in rule_value)
                if conflicting:
                    raise ValidationError(
                        f"Hiding options {sorted(conflicting)} on field '{dependent_field_for_fd.label}' "
                        f"conflicts with an existing conditional rule."
                    )


def validate_survey_pk_match_cr(data, survey_pk):
    """Ensure all CR referenced objects belong to the URL's survey_pk.

    Raises:
        ValidationError: If objects don't match URL survey.
    """
    survey_pk = int(survey_pk)
    depends_on = data.get("depends_on_field")
    target_section = data.get("target_section")
    target_field = data.get("target_field")

    if depends_on and depends_on.section.survey_id != survey_pk:
        raise ValidationError("depends_on_field does not belong to this survey.")
    if target_section and target_section.survey_id != survey_pk:
        raise ValidationError("target_section does not belong to this survey.")
    if target_field and target_field.section.survey_id != survey_pk:
        raise ValidationError("target_field does not belong to this survey.")


def validate_survey_pk_match_fd(data, survey_pk):
    """Ensure all FD referenced objects belong to the URL's survey_pk.

    Raises:
        ValidationError: If objects don't match URL survey.
    """
    survey_pk = int(survey_pk)
    depends_on = data.get("depends_on_field")
    dependent = data.get("dependent_field")

    if depends_on and depends_on.section.survey_id != survey_pk:
        raise ValidationError("depends_on_field does not belong to this survey.")
    if dependent and dependent.section.survey_id != survey_pk:
        raise ValidationError("dependent_field does not belong to this survey.")


def validate_survey_is_draft(survey):
    """Ensure a survey is in draft status for structure modifications.

    Raises:
        ValidationError: If survey is not draft.
    """
    if survey.status != Survey.SurveyStatus.DRAFT:
        raise ValidationError(
            f"Cannot modify structure of a {survey.status} survey. "
            "Only draft surveys can be modified."
        )


def validate_conditional_rule_data(data, survey_pk=None):
    """Validate target exclusivity, same-survey, self-reference, ordering, and operator/value.

    Raises:
        ValidationError: On constraint violations.
    """
    target_section = data.get("target_section")
    target_field = data.get("target_field")
    depends_on = data.get("depends_on_field")

    if not target_section and not target_field:
        raise ValidationError("Either target_section or target_field must be set.")
    if target_section and target_field:
        raise ValidationError("Only one of target_section or target_field can be set.")

    if depends_on:
        source_survey_id = depends_on.section.survey_id
        if target_section and target_section.survey_id != source_survey_id:
            raise ValidationError(
                "target_section must belong to the same survey as depends_on_field."
            )
        if target_field and target_field.section.survey_id != source_survey_id:
            raise ValidationError(
                "target_field must belong to the same survey as depends_on_field."
            )

    # URL survey_pk validation
    if survey_pk is not None and depends_on:
        validate_survey_pk_match_cr(data, survey_pk)

    # Self-reference
    validate_self_reference_cr(data)

    # Ordering
    if depends_on:
        validate_ordering_constraint(
            depends_on, target_section=target_section, target_field=target_field
        )

    # ComparisonOperator/value validation
    operator = data.get("operator")
    value = data.get("value")
    if depends_on and operator and value is not None:
        validate_operator_value(depends_on, operator, value)


def validate_field_dependency_data(data, survey_pk=None):
    """Validate same-survey, self-reference, ordering, operator/value, and action_value.

    Raises:
        ValidationError: On constraint violations.
    """
    dependent = data.get("dependent_field")
    depends_on = data.get("depends_on_field")

    if dependent and depends_on:
        if dependent.section.survey_id != depends_on.section.survey_id:
            raise ValidationError(
                "dependent_field and depends_on_field must belong to the same survey."
            )

    # URL survey_pk validation
    if survey_pk is not None:
        validate_survey_pk_match_fd(data, survey_pk)

    # Self-reference
    validate_self_reference_fd(data)

    # Ordering
    if dependent and depends_on:
        validate_fd_ordering_constraint(depends_on, dependent)

    # ComparisonOperator/value validation
    operator = data.get("operator")
    value = data.get("value")
    if depends_on and operator and value is not None:
        validate_operator_value(depends_on, operator, value)

    # Action/action_value validation
    action = data.get("action")
    action_value = data.get("action_value")
    if dependent and action and action_value is not None:
        validate_action_value(action, action_value, dependent)

    # CR+FD conflict detection (only for hide_options)
    if dependent and action == "hide_options" and action_value is not None:
        validate_cr_fd_conflict(depends_on, action, action_value, dependent)


# ---------------------------------------------------------------------------
# Survey CRUD
# ---------------------------------------------------------------------------


# def create_survey(*, created_by, **data):
#     """Create a survey. No cache to invalidate."""
#     return Survey.objects.create(created_by=created_by, **data)


# def delete_survey(instance):
#     """Invalidate cache, then delete."""
#     SurveyCacheService.invalidate_structure(instance.id)
#     instance.delete()


# ---------------------------------------------------------------------------
# Section CRUD
# ---------------------------------------------------------------------------


def update_section(instance, validated_data):
    """Save, invalidate survey cache, revalidate ordering if order changed."""
    old_order = instance.order
    try:
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save(update_fields=list(validated_data.keys()))

            if "order" in validated_data and validated_data["order"] != old_order:
                _revalidate_ordering_for_survey(instance.survey)
    except IntegrityError:
        raise ValidationError(
            "A section with this order already exists in this survey."
        )

    SurveyCacheService.invalidate_structure(instance.survey_id)
    return instance


def delete_section(instance):
    """Invalidate cache, delete."""
    SurveyCacheService.invalidate_structure(instance.survey_id)
    instance.delete()


# ---------------------------------------------------------------------------
# Field CRUD
# ---------------------------------------------------------------------------


def create_field(*, section, **data):
    """Save field, invalidate survey cache."""
    try:
        field = Field.objects.create(section=section, **data)
    except IntegrityError:
        raise ValidationError(
            {"order": "A field with this order already exists in this section."}
        )
    SurveyCacheService.invalidate_structure(section.survey_id)
    return field


def update_field(instance, validated_data):
    """Save, invalidate survey cache, revalidate related rules if type/options changed."""
    old_type = instance.field_type
    old_options = list(instance.options) if instance.options else []

    try:
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save(update_fields=list(validated_data.keys()))

            type_changed = (
                "field_type" in validated_data
                and validated_data["field_type"] != old_type
            )
            options_changed = (
                "options" in validated_data
                and validated_data["options"] != old_options
            )

            if type_changed or options_changed:
                _revalidate_rules_for_field(instance)
    except IntegrityError:
        raise ValidationError(
            "A field with this order already exists in this section."
        )

    SurveyCacheService.invalidate_structure(instance.section.survey_id)
    return instance


def delete_field(instance):
    """Invalidate cache, delete."""
    SurveyCacheService.invalidate_structure(instance.section.survey_id)
    instance.delete()


# ---------------------------------------------------------------------------
# ConditionalRule CRUD
# ---------------------------------------------------------------------------


def create_conditional_rule(validated_data, survey_pk):
    """Save rule, invalidate survey cache."""
    validated_data["survey_id"] = survey_pk
    rule = ConditionalRule.objects.create(**validated_data)
    SurveyCacheService.invalidate_structure(survey_pk)
    return rule


def update_conditional_rule(instance, validated_data, survey_pk):
    """Save, invalidate survey cache."""
    for attr, value in validated_data.items():
        setattr(instance, attr, value)
    instance.save(update_fields=list(validated_data.keys()))
    SurveyCacheService.invalidate_structure(survey_pk)
    return instance


def delete_conditional_rule(instance, survey_pk):
    """Invalidate cache, delete."""
    SurveyCacheService.invalidate_structure(survey_pk)
    instance.delete()


# ---------------------------------------------------------------------------
# FieldDependency CRUD
# ---------------------------------------------------------------------------


def create_field_dependency(validated_data, survey_pk):
    """Save dependency, invalidate survey cache."""
    validated_data["survey_id"] = survey_pk
    dep = FieldDependency.objects.create(**validated_data)
    SurveyCacheService.invalidate_structure(survey_pk)
    return dep


def update_field_dependency(instance, validated_data, survey_pk):
    """Save, invalidate survey cache."""
    for attr, value in validated_data.items():
        setattr(instance, attr, value)
    instance.save(update_fields=list(validated_data.keys()))
    SurveyCacheService.invalidate_structure(survey_pk)
    return instance


def delete_field_dependency(instance, survey_pk):
    """Invalidate cache, delete."""
    SurveyCacheService.invalidate_structure(survey_pk)
    instance.delete()


# ---------------------------------------------------------------------------
# Cascading revalidation helpers
# ---------------------------------------------------------------------------


def _revalidate_rules_for_field(field):
    """Revalidate all CRs and FDs that reference this field after type/options change.

    Raises:
        ValidationError: If existing rules become invalid after the change.
    """
    errors = []

    # CRs where this field is depends_on_field
    cr_rules = ConditionalRule.objects.filter(
        depends_on_field=field,
    ).select_related("target_section", "target_field")

    for rule in cr_rules:
        try:
            validate_operator_value(field, rule.operator, rule.value)
        except ValidationError as e:
            errors.append(f"ConditionalRule #{rule.pk}: {e.message}")

    # FDs where this field is depends_on_field
    fd_deps = FieldDependency.objects.filter(
        depends_on_field=field,
    ).select_related("dependent_field")

    for dep in fd_deps:
        try:
            validate_operator_value(field, dep.operator, dep.value)
        except ValidationError as e:
            errors.append(f"FieldDependency #{dep.pk} (operator/value): {e.message}")

    # FDs where this field is dependent_field (action_value references its options)
    fd_targets = FieldDependency.objects.filter(
        dependent_field=field,
    )

    for dep in fd_targets:
        try:
            validate_action_value(dep.action, dep.action_value, field)
        except ValidationError as e:
            errors.append(f"FieldDependency #{dep.pk} (action_value): {e.message}")

    if errors:
        raise ValidationError(
            "Changing this field would invalidate existing rules/dependencies: "
            + "; ".join(errors)
        )


def _revalidate_ordering_for_survey(survey):
    """Revalidate ordering constraints on all CRs and FDs in a survey after section order change.

    Raises:
        ValidationError: If existing rules become invalid after the order change.
    """
    errors = []

    cr_rules = ConditionalRule.objects.filter(
        survey=survey,
    ).select_related(
        "depends_on_field",
        "depends_on_field__section",
        "target_section",
        "target_field",
        "target_field__section",
    )

    for rule in cr_rules:
        try:
            validate_ordering_constraint(
                rule.depends_on_field,
                target_section=rule.target_section,
                target_field=rule.target_field,
            )
        except ValidationError as e:
            errors.append(f"ConditionalRule #{rule.pk}: {e.message}")

    fd_deps = FieldDependency.objects.filter(
        survey=survey,
    ).select_related(
        "depends_on_field",
        "depends_on_field__section",
        "dependent_field",
        "dependent_field__section",
    )

    for dep in fd_deps:
        try:
            validate_fd_ordering_constraint(dep.depends_on_field, dep.dependent_field)
        except ValidationError as e:
            errors.append(f"FieldDependency #{dep.pk}: {e.message}")

    if errors:
        raise ValidationError(
            "Changing section order would invalidate existing rules/dependencies: "
            + "; ".join(errors)
        )
