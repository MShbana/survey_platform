from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet

from apps.responses.models import FieldResponse, SurveyResponse
from apps.responses.serializers import (
    FieldResponseSerializer,
    SurveySubmissionSerializer,
)
from apps.surveys.models import Field, Section, Survey

User = get_user_model()


class SubmissionSerializerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(title="S", created_by=self.user)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.field = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )

    def test_valid_submission(self):
        data = {"answers": [{"field_id": self.field.id, "value": "hello"}]}
        s = SurveySubmissionSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)

    def test_invalid_field_id(self):
        data = {"answers": [{"field_id": 99999, "value": "hello"}]}
        s = SurveySubmissionSerializer(data=data)
        self.assertFalse(s.is_valid())

    def test_empty_answers(self):
        data = {"answers": []}
        s = SurveySubmissionSerializer(data=data)
        self.assertTrue(s.is_valid())


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@override_settings(ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class FieldResponseSerializerTest(TestCase):
    """Fix #6: Ciphertext should not be exposed in API responses."""

    def setUp(self):
        from apps.responses.services import encrypt_value

        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.customer = User.objects.create_user(
            email="customer@example.com", password="p", role="customer"
        )
        self.survey = Survey.objects.create(
            title="S", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED
        )
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.encrypted_field = Field.objects.create(
            section=self.section,
            label="SSN",
            field_type=Field.FieldType.TEXT,
            order=1,
            is_encrypted=True,
        )
        self.plain_field = Field.objects.create(
            section=self.section,
            label="Name",
            field_type=Field.FieldType.TEXT,
            order=2,
        )
        self.response = SurveyResponse.objects.create(
            survey=self.survey, user=self.customer
        )
        self.encrypted_fr = FieldResponse.objects.create(
            survey_response=self.response,
            field=self.encrypted_field,
            value=encrypt_value("123-45-6789"),
        )
        self.plain_fr = FieldResponse.objects.create(
            survey_response=self.response,
            field=self.plain_field,
            value="Alice",
        )

    def test_encrypted_field_value_is_decrypted(self):
        data = FieldResponseSerializer(self.encrypted_fr).data
        self.assertEqual(data["value"], "123-45-6789")

    def test_encrypted_field_does_not_expose_ciphertext(self):
        data = FieldResponseSerializer(self.encrypted_fr).data
        self.assertNotIn("gAAAAA", data["value"])

    def test_plain_field_value_unchanged(self):
        data = FieldResponseSerializer(self.plain_fr).data
        self.assertEqual(data["value"], "Alice")

    def test_no_decrypted_value_field_in_response(self):
        data = FieldResponseSerializer(self.encrypted_fr).data
        self.assertNotIn("decrypted_value", data)
