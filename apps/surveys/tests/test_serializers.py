from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.surveys.models import Field, Section, Survey, ComparisonOperator
from apps.surveys.serializers import (
    ConditionalRuleSerializer,
    FieldSerializer,
    SectionWriteSerializer,
)

User = get_user_model()


class FieldSerializerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def test_dropdown_requires_options(self):
        data = {
            "section": self.section.id,
            "label": "Choose",
            "field_type": Field.FieldType.DROPDOWN,
            "order": 1,
            "options": [],
        }
        s = FieldSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn("options", s.errors)

    def test_text_field_no_options_needed(self):
        data = {
            "section": self.section.id,
            "label": "Name",
            "field_type": Field.FieldType.TEXT,
            "order": 1,
        }
        s = FieldSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)


class ConditionalRuleSerializerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(
            section=self.section, label="Q", field_type=Field.FieldType.TEXT, order=1
        )

    def test_must_set_target(self):
        data = {
            "depends_on_field": self.field.id,
            "operator": ComparisonOperator.EQUALS,
            "value": "yes",
        }
        s = ConditionalRuleSerializer(data=data)
        self.assertFalse(s.is_valid())

    def test_cannot_set_both_targets(self):
        section2 = Section.objects.create(survey=self.survey, title="Sec2", order=2)
        field2 = Field.objects.create(
            section=section2, label="Q2", field_type=Field.FieldType.TEXT, order=1
        )
        data = {
            "target_section": section2.id,
            "target_field": field2.id,
            "depends_on_field": self.field.id,
            "operator": ComparisonOperator.EQUALS,
            "value": "yes",
        }
        s = ConditionalRuleSerializer(data=data)
        self.assertFalse(s.is_valid())


class OrderValidationTest(TestCase):
    """Fix #10: Negative order values should be rejected by serializers."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def test_field_negative_order_rejected(self):
        data = {
            "label": "Q1",
            "field_type": Field.FieldType.TEXT,
            "order": -1,
        }
        s = FieldSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn("order", s.errors)

    def test_field_zero_order_rejected(self):
        data = {
            "label": "Q1",
            "field_type": Field.FieldType.TEXT,
            "order": 0,
        }
        s = FieldSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn("order", s.errors)

    def test_field_positive_order_accepted(self):
        data = {
            "label": "Q1",
            "field_type": Field.FieldType.TEXT,
            "order": 1,
        }
        s = FieldSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)

    def test_section_negative_order_rejected(self):
        data = {
            "title": "Sec2",
            "order": -1,
        }
        s = SectionWriteSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn("order", s.errors)

    def test_section_zero_order_rejected(self):
        data = {
            "title": "Sec2",
            "order": 0,
        }
        s = SectionWriteSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn("order", s.errors)

    def test_section_positive_order_accepted(self):
        data = {
            "title": "Sec2",
            "order": 1,
        }
        s = SectionWriteSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)
