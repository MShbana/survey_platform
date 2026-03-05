from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from apps.surveys.models import (
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
    ComparisonOperator,
)

User = get_user_model()


class SurveyModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )

    def test_create_survey(self):
        survey = Survey.objects.create(title="Test Survey", created_by=self.user)
        self.assertEqual(str(survey), "Test Survey")
        self.assertEqual(survey.status, survey.SurveyStatus.DRAFT)

    def test_transition_draft_to_published(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        Field.objects.create(
            section=section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        survey.transition_to(Survey.SurveyStatus.PUBLISHED)
        self.assertEqual(survey.status, Survey.SurveyStatus.PUBLISHED)

    def test_transition_publish_empty_survey(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)

    def test_transition_publish_empty_section(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        Section.objects.create(survey=survey, title="Sec", order=1)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)

    def test_transition_published_to_archived(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        Field.objects.create(
            section=section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        survey.transition_to(Survey.SurveyStatus.PUBLISHED)
        survey.transition_to(Survey.SurveyStatus.ARCHIVED)
        self.assertEqual(survey.status, Survey.SurveyStatus.ARCHIVED)

    def test_transition_archived_to_published(self):
        survey = Survey.objects.create(
            title="S", created_by=self.user, status=Survey.SurveyStatus.ARCHIVED
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            survey.transition_to(Survey.SurveyStatus.PUBLISHED)

    def test_transition_draft_to_archived(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            survey.transition_to(Survey.SurveyStatus.ARCHIVED)

    def test_section_ordering(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        s2 = Section.objects.create(survey=survey, title="Second", order=2)
        s1 = Section.objects.create(survey=survey, title="First", order=1)
        sections = list(survey.sections.all())
        self.assertEqual(sections[0], s1)
        self.assertEqual(sections[1], s2)

    def test_section_unique_order(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        Section.objects.create(survey=survey, title="A", order=1)
        with self.assertRaises(IntegrityError):
            Section.objects.create(survey=survey, title="B", order=1)

    def test_field_unique_order(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        Field.objects.create(
            section=section, label="A", field_type=Field.FieldType.TEXT, order=1
        )
        with self.assertRaises(IntegrityError):
            Field.objects.create(
                section=section, label="B", field_type=Field.FieldType.TEXT, order=1
            )

    def test_conditional_rule_str(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        section2 = Section.objects.create(survey=survey, title="Sec2", order=2)
        field = Field.objects.create(
            section=section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        rule = ConditionalRule.objects.create(
            survey=survey,
            target_section=section2,
            depends_on_field=field,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )
        self.assertIn("Q1", str(rule))

    def test_field_dependency_str(self):
        survey = Survey.objects.create(title="S", created_by=self.user)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        f1 = Field.objects.create(
            section=section,
            label="Q1",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["a", "b"],
        )
        f2 = Field.objects.create(
            section=section,
            label="Q2",
            field_type=Field.FieldType.DROPDOWN,
            order=2,
            options=["x", "y"],
        )
        dep = FieldDependency.objects.create(
            survey=survey,
            dependent_field=f2,
            depends_on_field=f1,
            operator=ComparisonOperator.EQUALS,
            value="a",
            action="show_options",
            action_value=["x"],
        )
        self.assertIn("Q1", str(dep))
        self.assertIn("Q2", str(dep))
