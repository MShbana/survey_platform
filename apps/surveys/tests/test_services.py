from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.surveys.models import (
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
    ComparisonOperator,
)
from unittest.mock import patch

from apps.surveys.services import (
    create_field,
    delete_field,
    delete_section,
    evaluate_condition,
    get_visible_fields,
    get_visible_sections,
    resolve_dependencies,
    update_field,
    update_section,
    validate_conditional_rule_data,
    validate_field_dependency_data,
    validate_field_options,
)

from django.core.exceptions import ValidationError

User = get_user_model()


class EvaluateConditionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )

    def _make_rule(self, operator, value, **kwargs):
        return ConditionalRule(
            depends_on_field=self.field,
            operator=operator,
            value=value,
            **kwargs,
        )

    def test_equals(self):
        rule = self._make_rule(ComparisonOperator.EQUALS, "yes")
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "yes"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "no"}))

    def test_not_equals(self):
        rule = self._make_rule(ComparisonOperator.NOT_EQUALS, "yes")
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "no"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "yes"}))

    def test_contains(self):
        rule = self._make_rule(ComparisonOperator.CONTAINS, "hello")
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "say hello world"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "goodbye"}))

    def test_greater_than(self):
        rule = self._make_rule(ComparisonOperator.GREATER_THAN, 5)
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "10"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "3"}))

    def test_less_than(self):
        rule = self._make_rule(ComparisonOperator.LESS_THAN, 5)
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "3"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "10"}))

    def test_in_operator(self):
        rule = self._make_rule(ComparisonOperator.IN, ["a", "b", "c"])
        self.assertTrue(evaluate_condition(rule, {str(self.field.id): "a"}))
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "d"}))

    def test_missing_answer_returns_false(self):
        rule = self._make_rule(ComparisonOperator.EQUALS, "yes")
        self.assertFalse(evaluate_condition(rule, {}))

    def test_invalid_number_comparison(self):
        rule = self._make_rule(ComparisonOperator.GREATER_THAN, 5)
        self.assertFalse(evaluate_condition(rule, {str(self.field.id): "abc"}))


class VisibilitySectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="Always", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="Conditional", order=2)
        self.q1 = Field.objects.create(section=self.s1, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=self.s2,
            depends_on_field=self.q1,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )

    def test_section_visible_when_condition_met(self):
        visible = get_visible_sections(self.survey, {str(self.q1.id): "yes"})
        self.assertIn(self.s1.id, visible)
        self.assertIn(self.s2.id, visible)

    def test_section_hidden_when_condition_not_met(self):
        visible = get_visible_sections(self.survey, {str(self.q1.id): "no"})
        self.assertIn(self.s1.id, visible)
        self.assertNotIn(self.s2.id, visible)


class VisibilityFieldTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.q1 = Field.objects.create(section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        self.q2 = Field.objects.create(section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=2)
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.q2,
            depends_on_field=self.q1,
            operator=ComparisonOperator.EQUALS,
            value="show",
        )

    def test_field_visible_when_condition_met(self):
        visible = get_visible_fields(self.section, {str(self.q1.id): "show"})
        self.assertIn(self.q1.id, visible)
        self.assertIn(self.q2.id, visible)

    def test_field_hidden_when_condition_not_met(self):
        visible = get_visible_fields(self.section, {str(self.q1.id): "hide"})
        self.assertIn(self.q1.id, visible)
        self.assertNotIn(self.q2.id, visible)


class DependencyResolutionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.country = Field.objects.create(
            section=self.section, label="Country", field_type=Field.FieldType.DROPDOWN,
            order=1, options=["US", "UK", "CA"],
        )
        self.city = Field.objects.create(
            section=self.section, label="City", field_type=Field.FieldType.DROPDOWN,
            order=2, options=["New York", "London", "Toronto"],
        )
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=self.city,
            depends_on_field=self.country,
            operator=ComparisonOperator.EQUALS,
            value="US",
            action="show_options",
            action_value=["New York"],
        )

    def test_dependency_resolved(self):
        mods = resolve_dependencies(self.survey, {str(self.country.id): "US"})
        self.assertIn(self.city.id, mods)
        self.assertEqual(mods[self.city.id][0]["action"], "show_options")

    def test_dependency_not_triggered(self):
        mods = resolve_dependencies(self.survey, {str(self.country.id): "UK"})
        self.assertNotIn(self.city.id, mods)

class CreateSectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)



class DeleteSectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_delete_section_invalidates_cache(self, mock_invalidate):
        section_id = self.section.id
        delete_section(self.section)
        self.assertFalse(Section.objects.filter(id=section_id).exists())
        mock_invalidate.assert_called_once_with(self.survey.id)


class CreateFieldTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_create_field_invalidates_cache(self, mock_invalidate):
        field = create_field(section=self.section, label="Q", field_type=Field.FieldType.TEXT, order=1)
        self.assertEqual(field.section_id, self.section.id)
        mock_invalidate.assert_called_once_with(self.survey.id)


class DeleteFieldTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(section=self.section, label="Q", field_type=Field.FieldType.TEXT, order=1)

    @patch("apps.surveys.services.SurveyCacheService.invalidate_structure")
    def test_delete_field_invalidates_cache(self, mock_invalidate):
        field_id = self.field.id
        delete_field(self.field)
        self.assertFalse(Field.objects.filter(id=field_id).exists())
        mock_invalidate.assert_called_once_with(self.survey.id)


class ValidateConditionalRuleDataTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1)

        self.survey2 = Survey.objects.create(title="S2", created_by=self.user)
        self.section2 = Section.objects.create(survey=self.survey2, title="Sec2", order=1)
        self.field2 = Field.objects.create(section=self.section2, label="Q2", field_type=Field.FieldType.TEXT, order=1)

    def test_no_target_raises(self):
        with self.assertRaises(ValidationError):
            validate_conditional_rule_data({"depends_on_field": self.field})

    def test_both_targets_raises(self):
        with self.assertRaises(ValidationError):
            validate_conditional_rule_data({
                "target_section": self.section,
                "target_field": self.field,
                "depends_on_field": self.field,
            })

    def test_cross_survey_section_raises(self):
        with self.assertRaises(ValidationError):
            validate_conditional_rule_data({
                "target_section": self.section2,
                "depends_on_field": self.field,
            })

    def test_cross_survey_field_raises(self):
        with self.assertRaises(ValidationError):
            validate_conditional_rule_data({
                "target_field": self.field2,
                "depends_on_field": self.field,
            })

    def test_valid_section_target(self):
        section2 = Section.objects.create(survey=self.survey, title="Sec2", order=2)
        validate_conditional_rule_data({
            "target_section": section2,
            "depends_on_field": self.field,
        })

    def test_valid_field_target(self):
        field2 = Field.objects.create(section=self.section, label="Q3", field_type=Field.FieldType.TEXT, order=2)
        validate_conditional_rule_data({
            "target_field": field2,
            "depends_on_field": self.field,
        })


class ValidateFieldDependencyDataTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field1 = Field.objects.create(section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        self.field2 = Field.objects.create(section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=2)

        self.survey2 = Survey.objects.create(title="S2", created_by=self.user)
        self.section2 = Section.objects.create(survey=self.survey2, title="Sec2", order=1)
        self.field3 = Field.objects.create(section=self.section2, label="Q3", field_type=Field.FieldType.TEXT, order=1)

    def test_same_survey_valid(self):
        validate_field_dependency_data({
            "dependent_field": self.field2,
            "depends_on_field": self.field1,
        })

    def test_cross_survey_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_dependency_data({
                "dependent_field": self.field1,
                "depends_on_field": self.field3,
            })


class ValidateFieldOptionsTest(TestCase):
    def test_dropdown_without_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.DROPDOWN, [])

    def test_radio_without_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.RADIO, [])

    def test_checkbox_without_options_raises(self):
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.CHECKBOX, [])

    def test_dropdown_with_options_valid(self):
        validate_field_options(Field.FieldType.DROPDOWN, ["a", "b"])

    def test_text_without_options_valid(self):
        validate_field_options(Field.FieldType.TEXT, [])

    def test_dict_option_raises(self):
        """Fix #9: Unhashable types like dicts should be rejected."""
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.DROPDOWN, [{"a": 1}, "b"])

    def test_list_option_raises(self):
        """Fix #9: Nested lists should be rejected."""
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.RADIO, [["nested"], "b"])

    def test_none_option_raises(self):
        """Fix #9: None values should be rejected."""
        with self.assertRaises(ValidationError):
            validate_field_options(Field.FieldType.CHECKBOX, [None, "a"])

    def test_numeric_options_valid(self):
        """Fix #9: Numeric options should be accepted."""
        validate_field_options(Field.FieldType.DROPDOWN, [1, 2, 3])


class CreateFieldIntegrityTest(TestCase):
    """Fix #2: create_field catches IntegrityError on duplicate order."""

    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def test_duplicate_order_raises_validation_error(self):
        create_field(section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        with self.assertRaises(ValidationError):
            create_field(section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=1)


class UpdateSectionIntegrityTest(TestCase):
    """Fix #3: update_section catches IntegrityError on order collision."""

    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.s1 = Section.objects.create(survey=self.survey, title="S1", order=1)
        self.s2 = Section.objects.create(survey=self.survey, title="S2", order=2)

    def test_duplicate_order_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            update_section(self.s2, {"order": 1})


class UpdateFieldIntegrityTest(TestCase):
    """Fix #3: update_field catches IntegrityError on order collision."""

    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.f1 = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        self.f2 = Field.objects.create(
            section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=2
        )

    def test_duplicate_order_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            update_field(self.f2, {"order": 1})
