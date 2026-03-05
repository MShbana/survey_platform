"""Tests for the new validation functions and behaviors added in the data integrity phase.

Covers:
    - validate_field_options (non-choice fields, duplicate options)
    - validate_validation_rules (schema, type cross-check)
    - validate_operator_value (operator/value compat with field type)
    - validate_ordering_constraint / validate_fd_ordering_constraint
    - validate_action_value (set_value, show/hide options)
    - validate_self_reference_cr / validate_self_reference_fd
    - detect_circular_dependencies_cr / detect_circular_dependencies_fd
    - validate_cr_fd_conflict
    - validate_survey_is_draft
    - Publish validation (all sections must have fields)
    - Cascading revalidation on field mutation
    - Survey immutability through views
    - Auto-assign order
    - Reorder endpoints
    - Hide empty sections for non-admins
    - URL survey_pk match validation
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.surveys.models import (
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
    ComparisonOperator,
)
from apps.surveys.services import (
    detect_circular_dependencies_cr,
    detect_circular_dependencies_fd,
    update_field,
    update_section,
    validate_action_value,
    validate_cr_fd_conflict,
    validate_fd_ordering_constraint,
    validate_field_options,
    validate_operator_value,
    validate_ordering_constraint,
    validate_self_reference_cr,
    validate_self_reference_fd,
    validate_survey_is_draft,
    validate_validation_rules,
)

from apps.surveys.constants import ValidationRuleKey

User = get_user_model()


# ---------------------------------------------------------------------------
# validate_field_options
# ---------------------------------------------------------------------------


class ValidateFieldOptionsExtendedTest(TestCase):
    def test_non_choice_field_with_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.TEXT, ["a", "b"])

    def test_number_field_with_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.NUMBER, ["1", "2"])

    def test_date_field_with_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.DATE, ["2024-01-01"])

    def test_email_field_with_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.EMAIL, ["a@b.com"])

    def test_textarea_with_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.TEXTAREA, ["opt"])

    def test_duplicate_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.DROPDOWN, ["a", "a", "b"])

    def test_unique_options_valid(self):
        validate_field_options(Field.FieldType.DROPDOWN, ["a", "b", "c"])

    def test_text_no_options_valid(self):
        validate_field_options(Field.FieldType.TEXT, [])


# ---------------------------------------------------------------------------
# validate_validation_rules
# ---------------------------------------------------------------------------


class ValidateValidationRulesTest(TestCase):
    def test_empty_rules_valid(self):
        validate_validation_rules(Field.FieldType.TEXT, {})

    def test_none_rules_valid(self):
        validate_validation_rules(Field.FieldType.TEXT, None)

    def test_unknown_key_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, {"foo": "bar"})

    def test_min_max_for_number_valid(self):
        validate_validation_rules(Field.FieldType.NUMBER, {ValidationRuleKey.MIN: 0, ValidationRuleKey.MAX: 100})

    def test_min_max_for_text_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, {ValidationRuleKey.MIN: 0})

    def test_min_max_for_dropdown_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.DROPDOWN, {ValidationRuleKey.MIN: 0})

    def test_min_greater_than_max_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.NUMBER, {ValidationRuleKey.MIN: 100, ValidationRuleKey.MAX: 0})

    def test_non_numeric_min_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.NUMBER, {ValidationRuleKey.MIN: "abc"})

    def test_min_length_max_length_for_text_valid(self):
        validate_validation_rules(
            Field.FieldType.TEXT, {ValidationRuleKey.MIN_LENGTH: 1, ValidationRuleKey.MAX_LENGTH: 100}
        )

    def test_min_length_max_length_for_email_valid(self):
        validate_validation_rules(
            Field.FieldType.EMAIL, {ValidationRuleKey.MIN_LENGTH: 5, ValidationRuleKey.MAX_LENGTH: 100}
        )

    def test_min_length_for_number_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.NUMBER, {ValidationRuleKey.MIN_LENGTH: 1})

    def test_min_length_greater_than_max_length_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(
                Field.FieldType.TEXT, {ValidationRuleKey.MIN_LENGTH: 100, ValidationRuleKey.MAX_LENGTH: 1}
            )

    def test_negative_min_length_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, {ValidationRuleKey.MIN_LENGTH: -1})

    def test_regex_for_text_valid(self):
        validate_validation_rules(Field.FieldType.TEXT, {ValidationRuleKey.REGEX: "^[a-z]+$"})

    def test_regex_for_number_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.NUMBER, {ValidationRuleKey.REGEX: ".*"})

    def test_invalid_regex_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, {ValidationRuleKey.REGEX: "[unclosed"})

    def test_non_string_regex_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, {ValidationRuleKey.REGEX: 123})

    def test_non_dict_rules_raises(self):
        with self.assertRaises(ValidationError):
            validate_validation_rules(Field.FieldType.TEXT, "invalid")


# ---------------------------------------------------------------------------
# validate_operator_value
# ---------------------------------------------------------------------------


class ValidateOperatorValueTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def _make_field(self, field_type, options=None):
        return Field.objects.create(
            section=self.section,
            label=f"{field_type}_field",
            field_type=field_type,
            order=Field.objects.filter(section=self.section).count() + 1,
            options=options or [],
        )

    def test_text_field_greater_than_raises(self):
        field = self._make_field(Field.FieldType.TEXT)
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.GREATER_THAN, "5")

    def test_dropdown_greater_than_raises(self):
        field = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.GREATER_THAN, "5")

    def test_number_equals_valid(self):
        field = self._make_field(Field.FieldType.NUMBER)
        validate_operator_value(field, ComparisonOperator.EQUALS, 5)

    def test_number_greater_than_valid(self):
        field = self._make_field(Field.FieldType.NUMBER)
        validate_operator_value(field, ComparisonOperator.GREATER_THAN, 10)

    def test_number_non_numeric_value_raises(self):
        field = self._make_field(Field.FieldType.NUMBER)
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.EQUALS, "abc")

    def test_number_in_non_list_raises(self):
        field = self._make_field(Field.FieldType.NUMBER)
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.IN, "5")

    def test_number_in_non_numeric_list_raises(self):
        field = self._make_field(Field.FieldType.NUMBER)
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.IN, [1, "abc"])

    def test_date_valid_format(self):
        field = self._make_field(Field.FieldType.DATE)
        validate_operator_value(field, ComparisonOperator.EQUALS, "2024-01-15")

    def test_date_invalid_format_raises(self):
        field = self._make_field(Field.FieldType.DATE)
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.EQUALS, "not-a-date")

    def test_dropdown_equals_valid_option(self):
        field = self._make_field(Field.FieldType.DROPDOWN, ["a", "b", "c"])
        validate_operator_value(field, ComparisonOperator.EQUALS, "a")

    def test_dropdown_equals_invalid_option_raises(self):
        field = self._make_field(Field.FieldType.DROPDOWN, ["a", "b", "c"])
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.EQUALS, "d")

    def test_dropdown_in_valid(self):
        field = self._make_field(Field.FieldType.DROPDOWN, ["a", "b", "c"])
        validate_operator_value(field, ComparisonOperator.IN, ["a", "b"])

    def test_dropdown_in_invalid_option_raises(self):
        field = self._make_field(Field.FieldType.DROPDOWN, ["a", "b", "c"])
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.IN, ["a", "z"])

    def test_date_greater_than_valid(self):
        field = self._make_field(Field.FieldType.DATE)
        validate_operator_value(field, ComparisonOperator.GREATER_THAN, "2024-01-01")

    def test_checkbox_less_than_raises(self):
        field = self._make_field(Field.FieldType.CHECKBOX, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_operator_value(field, ComparisonOperator.LESS_THAN, "5")


# ---------------------------------------------------------------------------
# validate_ordering_constraint
# ---------------------------------------------------------------------------


class ValidateOrderingConstraintTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.f1 = Field.objects.create(
            section=self.s1, label="F1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.s1, label="F2", field_type=Field.FieldType.TEXT, order=2
        )
        self.f3 = Field.objects.create(
            section=self.s2, label="F3", field_type=Field.FieldType.TEXT, order=1
        )

    def test_cr_section_target_after_source_valid(self):
        validate_ordering_constraint(self.f1, target_section=self.s2)

    def test_cr_section_target_before_source_raises(self):
        with self.assertRaises(ValidationError):
            validate_ordering_constraint(self.f3, target_section=self.s1)

    def test_cr_section_target_same_section_raises(self):
        with self.assertRaises(ValidationError):
            validate_ordering_constraint(self.f1, target_section=self.s1)

    def test_cr_field_target_after_in_same_section_valid(self):
        validate_ordering_constraint(self.f1, target_field=self.f2)

    def test_cr_field_target_before_in_same_section_raises(self):
        with self.assertRaises(ValidationError):
            validate_ordering_constraint(self.f2, target_field=self.f1)

    def test_cr_field_target_in_later_section_valid(self):
        validate_ordering_constraint(self.f1, target_field=self.f3)

    def test_cr_field_target_in_earlier_section_raises(self):
        with self.assertRaises(ValidationError):
            validate_ordering_constraint(self.f3, target_field=self.f1)


class ValidateFdOrderingConstraintTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.f1 = Field.objects.create(
            section=self.s1, label="F1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.s1, label="F2", field_type=Field.FieldType.TEXT, order=2
        )
        self.f3 = Field.objects.create(
            section=self.s2, label="F3", field_type=Field.FieldType.TEXT, order=1
        )

    def test_same_section_valid_order(self):
        validate_fd_ordering_constraint(self.f1, self.f2)

    def test_same_section_invalid_order_raises(self):
        with self.assertRaises(ValidationError):
            validate_fd_ordering_constraint(self.f2, self.f1)

    def test_cross_section_valid(self):
        validate_fd_ordering_constraint(self.f1, self.f3)

    def test_cross_section_invalid_raises(self):
        with self.assertRaises(ValidationError):
            validate_fd_ordering_constraint(self.f3, self.f1)


# ---------------------------------------------------------------------------
# validate_action_value
# ---------------------------------------------------------------------------


class ValidateActionValueTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def _make_field(self, field_type, options=None):
        return Field.objects.create(
            section=self.section,
            label=f"F",
            field_type=field_type,
            order=Field.objects.filter(section=self.section).count() + 1,
            options=options or [],
        )

    def test_show_options_on_non_choice_raises(self):
        f = self._make_field(Field.FieldType.TEXT)
        with self.assertRaises(ValidationError):
            validate_action_value("show_options", ["a"], f)

    def test_show_options_empty_list_raises(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_action_value("show_options", [], f)

    def test_show_options_not_list_raises(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_action_value("show_options", "a", f)

    def test_show_options_invalid_option_raises(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_action_value("show_options", ["z"], f)

    def test_show_options_valid(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b", "c"])
        validate_action_value("show_options", ["a", "b"], f)

    def test_hide_options_valid(self):
        f = self._make_field(Field.FieldType.RADIO, ["x", "y", "z"])
        validate_action_value("hide_options", ["x"], f)

    def test_set_value_dropdown_valid_option(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        validate_action_value("set_value", "a", f)

    def test_set_value_dropdown_invalid_option_raises(self):
        f = self._make_field(Field.FieldType.DROPDOWN, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_action_value("set_value", "z", f)

    def test_set_value_checkbox_valid(self):
        f = self._make_field(Field.FieldType.CHECKBOX, ["a", "b", "c"])
        validate_action_value("set_value", ["a", "b"], f)

    def test_set_value_checkbox_not_list_raises(self):
        f = self._make_field(Field.FieldType.CHECKBOX, ["a", "b"])
        with self.assertRaises(ValidationError):
            validate_action_value("set_value", "a", f)

    def test_set_value_number_valid(self):
        f = self._make_field(Field.FieldType.NUMBER)
        validate_action_value("set_value", 42, f)

    def test_set_value_number_non_numeric_raises(self):
        f = self._make_field(Field.FieldType.NUMBER)
        with self.assertRaises(ValidationError):
            validate_action_value("set_value", "abc", f)

    def test_set_value_email_valid(self):
        f = self._make_field(Field.FieldType.EMAIL)
        validate_action_value("set_value", "a@b.com", f)

    def test_set_value_email_invalid_raises(self):
        f = self._make_field(Field.FieldType.EMAIL)
        with self.assertRaises(ValidationError):
            validate_action_value("set_value", "notanemail", f)

    def test_set_value_date_valid(self):
        f = self._make_field(Field.FieldType.DATE)
        validate_action_value("set_value", "2024-01-15", f)

    def test_set_value_date_invalid_raises(self):
        f = self._make_field(Field.FieldType.DATE)
        with self.assertRaises(ValidationError):
            validate_action_value("set_value", "not-a-date", f)


# ---------------------------------------------------------------------------
# Self-reference prevention
# ---------------------------------------------------------------------------


class SelfReferenceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )

    def test_cr_self_reference_raises(self):
        with self.assertRaises(ValidationError):
            validate_self_reference_cr(
                {
                    "target_field": self.field,
                    "depends_on_field": self.field,
                }
            )

    def test_cr_no_self_reference_valid(self):
        field2 = Field.objects.create(
            section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=2
        )
        validate_self_reference_cr(
            {
                "target_field": field2,
                "depends_on_field": self.field,
            }
        )

    def test_fd_self_reference_raises(self):
        with self.assertRaises(ValidationError):
            validate_self_reference_fd(
                {
                    "dependent_field": self.field,
                    "depends_on_field": self.field,
                }
            )


# ---------------------------------------------------------------------------
# Circular dependency detection
# ---------------------------------------------------------------------------


class CircularDependencyCRTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.s3 = Section.objects.create(survey=self.survey, title="S3", order=3)
        self.f1 = Field.objects.create(
            section=self.s1, label="F1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.s2, label="F2", field_type=Field.FieldType.TEXT, order=1
        )
        self.f3 = Field.objects.create(
            section=self.s3, label="F3", field_type=Field.FieldType.TEXT, order=1
        )

    def test_direct_cycle_detected(self):
        # F1 -> F2 exists
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="x",
        )
        # Adding F2 -> F1 would create cycle
        with self.assertRaises(ValidationError):
            detect_circular_dependencies_cr(self.f2, target_field=self.f1)

    def test_no_cycle_valid(self):
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="x",
        )
        # F1 -> F3 is fine (no cycle)
        detect_circular_dependencies_cr(self.f1, target_field=self.f3)

    def test_section_target_no_cycle_check(self):
        # Section targets can't create field-level cycles
        detect_circular_dependencies_cr(self.f1, target_section=self.s2)


class CircularDependencyFDTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.f1 = Field.objects.create(
            section=self.section,
            label="F1",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["a", "b"],
        )
        self.f2 = Field.objects.create(
            section=self.section,
            label="F2",
            field_type=Field.FieldType.DROPDOWN,
            order=2,
            options=["x", "y"],
        )
        self.f3 = Field.objects.create(
            section=self.section,
            label="F3",
            field_type=Field.FieldType.DROPDOWN,
            order=3,
            options=["m", "n"],
        )

    def test_direct_cycle_detected(self):
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="a",
            action="show_options",
            action_value=["x"],
        )
        with self.assertRaises(ValidationError):
            detect_circular_dependencies_fd(self.f2, self.f1)

    def test_no_cycle_valid(self):
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="a",
            action="show_options",
            action_value=["x"],
        )
        detect_circular_dependencies_fd(self.f2, self.f3)


# ---------------------------------------------------------------------------
# CR+FD conflict detection
# ---------------------------------------------------------------------------


class CrFdConflictTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.trigger = Field.objects.create(
            section=self.s1,
            label="Trigger",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["a", "b", "c"],
        )
        self.target = Field.objects.create(
            section=self.s1,
            label="Target",
            field_type=Field.FieldType.DROPDOWN,
            order=2,
            options=["x", "y", "z"],
        )

    def test_hide_options_conflict_with_cr_equals(self):
        # CR depends on target's value "x"
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=self.s2,
            depends_on_field=self.target,
            operator=ComparisonOperator.EQUALS,
            value="x",
        )
        # FD hides "x" on target → conflict
        with self.assertRaises(ValidationError):
            validate_cr_fd_conflict(self.trigger, "hide_options", ["x"], self.target)

    def test_hide_options_no_conflict(self):
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=self.s2,
            depends_on_field=self.target,
            operator=ComparisonOperator.EQUALS,
            value="x",
        )
        # Hiding "y" doesn't conflict with CR checking for "x"
        validate_cr_fd_conflict(self.trigger, "hide_options", ["y"], self.target)

    def test_show_options_no_conflict_check(self):
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=self.s2,
            depends_on_field=self.target,
            operator=ComparisonOperator.EQUALS,
            value="x",
        )
        # show_options action doesn't trigger conflict check
        validate_cr_fd_conflict(self.trigger, "show_options", ["x"], self.target)


# ---------------------------------------------------------------------------
# validate_survey_is_draft
# ---------------------------------------------------------------------------


class ValidateSurveyIsDraftTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )

    def test_draft_valid(self):
        survey = Survey.objects.create(
            title="S", created_by=self.user, status=Survey.SurveyStatus.DRAFT
        )
        validate_survey_is_draft(survey)

    def test_published_raises(self):
        survey = Survey.objects.create(
            title="S", created_by=self.user, status=Survey.SurveyStatus.PUBLISHED
        )
        with self.assertRaises(ValidationError):
            validate_survey_is_draft(survey)

    def test_archived_raises(self):
        survey = Survey.objects.create(
            title="S", created_by=self.user, status=Survey.SurveyStatus.ARCHIVED
        )
        with self.assertRaises(ValidationError):
            validate_survey_is_draft(survey)


# ---------------------------------------------------------------------------
# Publish validation (all sections must have fields)
# ---------------------------------------------------------------------------


class PublishValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )

    def test_publish_no_sections_raises(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        with self.assertRaises(ValidationError):
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)

    def test_publish_empty_section_raises(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        Section.objects.create(survey=survey, title="S1", order=1)
        with self.assertRaises(ValidationError) as ctx:
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)
        self.assertIn("S1", str(ctx.exception))

    def test_publish_mixed_sections_raises(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        s1 = Section.objects.create(survey=survey, title="Populated", order=1)
        Field.objects.create(
            section=s1, label="Q", field_type=Field.FieldType.TEXT, order=1
        )
        Section.objects.create(survey=survey, title="Empty", order=2)
        with self.assertRaises(ValidationError) as ctx:
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)
        self.assertIn("Empty", str(ctx.exception))

    def test_publish_all_sections_have_fields_valid(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        s1 = Section.objects.create(survey=survey, title="S1", order=1)
        Field.objects.create(
            section=s1, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        s2 = Section.objects.create(survey=survey, title="S2", order=2)
        Field.objects.create(
            section=s2, label="Q2", field_type=Field.FieldType.TEXT, order=1
        )
        survey.transition_to(Survey.SurveyStatus.PUBLISHED)
        self.assertEqual(survey.status, Survey.SurveyStatus.PUBLISHED)


# ---------------------------------------------------------------------------
# Cascading revalidation
# ---------------------------------------------------------------------------


class CascadingRevalidationFieldTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.f1 = Field.objects.create(
            section=self.s1,
            label="Color",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["Red", "Blue", "Green"],
        )
        self.f2 = Field.objects.create(
            section=self.s2,
            label="Detail",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["X", "Y"],
        )

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_changing_type_to_text_invalidates_numeric_operator(self, mock_cache):
        # Change f1 to number type first, then add a CR with greater_than
        self.f1.field_type = Field.FieldType.NUMBER
        self.f1.options = []
        self.f1.save()
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=self.s2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.GREATER_THAN,
            value=5,
        )
        # Change f1 from number to text - greater_than is not allowed for text
        with self.assertRaises(ValidationError):
            update_field(self.f1, {"field_type": Field.FieldType.TEXT})

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_changing_options_invalidates_fd_action_value(self, mock_cache):
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="Red",
            action="show_options",
            action_value=["X"],
        )
        # Removing "X" from f2's options invalidates the FD's action_value
        with self.assertRaises(ValidationError):
            update_field(self.f2, {"options": ["Y", "Z"]})


class CascadingRevalidationSectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)
        self.f1 = Field.objects.create(
            section=self.s1, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.s2, label="Q2", field_type=Field.FieldType.TEXT, order=1
        )
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.f2,
            depends_on_field=self.f1,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_swapping_section_order_breaks_ordering(self, mock_cache):
        # S1 (order 1) has f1, S2 (order 2) has f2, CR: f1 -> f2
        # If we move S1 to order 3, f1 would come after f2, breaking the ordering constraint
        with self.assertRaises(ValidationError):
            update_section(self.s1, {"order": 3})


# ---------------------------------------------------------------------------
# View-level immutability tests
# ---------------------------------------------------------------------------


class SurveyImmutabilityViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(
            title="S", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED
        )
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        Field.objects.create(
            section=self.section, label="Q", field_type=Field.FieldType.TEXT, order=1
        )
        self.client.force_authenticate(user=self.admin)

    def test_cannot_create_section_on_published_survey(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/",
            {"title": "New Section", "order": 2},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_create_field_on_published_survey(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {"label": "New", "field_type": Field.FieldType.TEXT, "order": 2},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_delete_section_on_published_survey(self):
        resp = self.client.delete(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_modify_draft_survey_structure(self):
        draft_survey = Survey.objects.create(
            title="Draft", created_by=self.admin, status=Survey.SurveyStatus.DRAFT
        )
        resp = self.client.post(
            f"/api/v1/surveys/{draft_survey.id}/sections/",
            {"title": "New Section", "order": 1},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Auto-assign order
# ---------------------------------------------------------------------------


class AutoAssignOrderTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.admin)
        self.client.force_authenticate(user=self.admin)

    def test_section_auto_order_first(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/",
            {"title": "Auto Section"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["order"], 1)

    def test_section_auto_order_increment(self):
        Section.objects.create(survey=self.survey, title="S1", order=5)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/",
            {"title": "Auto Section"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["order"], 6)

    def test_field_auto_order_first(self):
        section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{section.id}/fields/",
            {"label": "Q", "field_type": Field.FieldType.TEXT},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["order"], 1)

    def test_field_auto_order_increment(self):
        section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        Field.objects.create(
            section=section, label="Q1", field_type=Field.FieldType.TEXT, order=3
        )
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{section.id}/fields/",
            {"label": "Q2", "field_type": Field.FieldType.TEXT},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["order"], 4)


# ---------------------------------------------------------------------------
# Hide empty sections from non-admin
# ---------------------------------------------------------------------------


class HideEmptySectionsTest(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.customer = User.objects.create_user(
            email="cust@example.com", password="p", role="customer"
        )
        self.survey = Survey.objects.create(
            title="S",
            created_by=self.admin,
            status=Survey.SurveyStatus.PUBLISHED,
        )
        self.s1 = Section.objects.create(
            survey=self.survey, title="With Fields", order=1
        )
        Field.objects.create(
            section=self.s1, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        self.s2 = Section.objects.create(survey=self.survey, title="Empty", order=2)

    def test_admin_sees_empty_sections(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertEqual(len(resp.data["sections"]), 2)

    def test_customer_does_not_see_empty_sections(self):
        from django.core.cache import cache

        cache.clear()  # Clear any cached admin response
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertEqual(len(resp.data["sections"]), 1)
        self.assertEqual(resp.data["sections"][0]["title"], "With Fields")


# ---------------------------------------------------------------------------
# URL survey_pk match validation (via view integration)
# ---------------------------------------------------------------------------


class URLSurveyPkMatchTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey1 = Survey.objects.create(title="S1", created_by=self.admin)
        self.survey2 = Survey.objects.create(title="S2", created_by=self.admin)
        self.s1 = Section.objects.create(survey=self.survey1, title="Sec1", order=1)
        self.s2 = Section.objects.create(survey=self.survey2, title="Sec2", order=1)
        self.f1 = Field.objects.create(
            section=self.s1, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.s2, label="Q2", field_type=Field.FieldType.TEXT, order=1
        )
        self.client.force_authenticate(user=self.admin)

    def test_cr_cross_survey_url_mismatch_rejected(self):
        # POST to survey1's CR endpoint with fields from survey2
        s1_2 = Section.objects.create(survey=self.survey1, title="Sec1b", order=2)
        f1_2 = Field.objects.create(
            section=s1_2, label="Q1b", field_type=Field.FieldType.TEXT, order=1
        )
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey1.id}/conditional-rules/",
            {
                "target_field": f1_2.id,
                "depends_on_field": self.f2.id,  # from survey2
                "operator": ComparisonOperator.EQUALS,
                "value": "yes",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fd_cross_survey_url_mismatch_rejected(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey1.id}/field-dependencies/",
            {
                "dependent_field": self.f1.id,
                "depends_on_field": self.f2.id,  # from survey2
                "operator": ComparisonOperator.EQUALS,
                "value": "yes",
                "action": "set_value",
                "action_value": "test",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# FieldSerializer validation_rules integration
# ---------------------------------------------------------------------------


class FieldSerializerValidationRulesTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.admin)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.client.force_authenticate(user=self.admin)

    def test_create_field_with_valid_rules(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {
                "label": "Age",
                "field_type": Field.FieldType.NUMBER,
                "order": 1,
                "validation_rules": {ValidationRuleKey.MIN: 0, ValidationRuleKey.MAX: 150},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_field_with_invalid_rules_rejected(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {
                "label": "Age",
                "field_type": Field.FieldType.TEXT,
                "order": 1,
                "validation_rules": {ValidationRuleKey.MIN: 0},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_text_field_with_options_rejected(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {
                "label": "Name",
                "field_type": Field.FieldType.TEXT,
                "order": 1,
                "options": ["a", "b"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_dropdown_with_duplicate_options_rejected(self):
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {
                "label": "Pick",
                "field_type": Field.FieldType.DROPDOWN,
                "order": 1,
                "options": ["a", "a", "b"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
