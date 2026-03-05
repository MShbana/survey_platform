from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet

from apps.responses.services import (
    ValidationError,
    create_submission,
    decrypt_value,
    encrypt_value,
    validate_submission,
)
from apps.surveys.models import (
    ComparisonOperator,
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
)
from apps.surveys.constants import ValidationRuleKey


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()
User = get_user_model()


@override_settings(ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class EncryptionTest(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        original = "sensitive data"
        encrypted = encrypt_value(original)
        self.assertNotEqual(encrypted, original)
        decrypted = decrypt_value(encrypted)
        self.assertEqual(decrypted, original)

    def test_different_values_produce_different_ciphertexts(self):
        e1 = encrypt_value("value1")
        e2 = encrypt_value("value2")
        self.assertNotEqual(e1, e2)


class ValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="p", role="admin"
        )
        self.survey = Survey.objects.create(
            title="S", created_by=self.user, status=Survey.SurveyStatus.PUBLISHED
        )
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def test_required_field_missing(self):
        field = Field.objects.create(
            section=self.section,
            label="Name",
            field_type=Field.FieldType.TEXT,
            order=1,
            required=True,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_submission(self.survey, {})
        self.assertIn(str(field.id), ctx.exception.errors)

    def test_email_validation(self):
        field = Field.objects.create(
            section=self.section,
            label="Email",
            field_type=Field.FieldType.EMAIL,
            order=1,
            required=True,
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "notanemail"})

        result = validate_submission(self.survey, {str(field.id): "test@example.com"})
        self.assertIn(str(field.id), result)

    def test_number_validation(self):
        field = Field.objects.create(
            section=self.section,
            label="Age",
            field_type=Field.FieldType.NUMBER,
            order=1,
            required=True,
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "abc"})

        result = validate_submission(self.survey, {str(field.id): "25"})
        self.assertIn(str(field.id), result)

    def test_date_validation(self):
        field = Field.objects.create(
            section=self.section,
            label="DOB",
            field_type=Field.FieldType.DATE,
            order=1,
            required=True,
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "01-01-2020"})

        result = validate_submission(self.survey, {str(field.id): "2020-01-01"})
        self.assertIn(str(field.id), result)

    def test_dropdown_validation(self):
        field = Field.objects.create(
            section=self.section,
            label="Color",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            required=True,
            options=["red", "blue"],
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "green"})

        result = validate_submission(self.survey, {str(field.id): "red"})
        self.assertIn(str(field.id), result)

    def test_checkbox_validation(self):
        field = Field.objects.create(
            section=self.section,
            label="Hobbies",
            field_type=Field.FieldType.CHECKBOX,
            order=1,
            required=True,
            options=["reading", "gaming"],
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): ["reading", "swimming"]})

        result = validate_submission(
            self.survey, {str(field.id): ["reading", "gaming"]}
        )
        self.assertIn(str(field.id), result)

    def test_min_max_validation_rules(self):
        field = Field.objects.create(
            section=self.section,
            label="Score",
            field_type=Field.FieldType.NUMBER,
            order=1,
            required=True,
            validation_rules={ValidationRuleKey.MIN: 1, ValidationRuleKey.MAX: 100},
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "200"})

        result = validate_submission(self.survey, {str(field.id): "50"})
        self.assertIn(str(field.id), result)

    def test_regex_validation_rule(self):
        field = Field.objects.create(
            section=self.section,
            label="Zip",
            field_type=Field.FieldType.TEXT,
            order=1,
            required=True,
            validation_rules={ValidationRuleKey.REGEX: r"^\d{5}$"},
        )
        with self.assertRaises(ValidationError):
            validate_submission(self.survey, {str(field.id): "1234"})

        result = validate_submission(self.survey, {str(field.id): "12345"})
        self.assertIn(str(field.id), result)

    def test_conditional_section_hides_fields(self):
        q1 = Field.objects.create(
            section=self.section,
            label="Show more?",
            field_type=Field.FieldType.TEXT,
            order=1,
        )
        section2 = Section.objects.create(survey=self.survey, title="Extra", order=2)
        q2 = Field.objects.create(
            section=section2,
            label="Detail",
            field_type=Field.FieldType.TEXT,
            order=1,
            required=True,
        )
        ConditionalRule.objects.create(
            survey=self.survey,
            target_section=section2,
            depends_on_field=q1,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )
        # Section2 hidden → q2 not required
        result = validate_submission(self.survey, {str(q1.id): "no"})
        self.assertNotIn(str(q2.id), result)

    def test_dependency_restricts_options(self):
        country = Field.objects.create(
            section=self.section,
            label="Country",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["US", "UK"],
        )
        city = Field.objects.create(
            section=self.section,
            label="City",
            field_type=Field.FieldType.DROPDOWN,
            order=2,
            options=["NYC", "London"],
            required=True,
        )
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=city,
            depends_on_field=country,
            operator=ComparisonOperator.EQUALS,
            value="US",
            action="show_options",
            action_value=["NYC"],
        )
        with self.assertRaises(ValidationError):
            validate_submission(
                self.survey,
                {
                    str(country.id): "US",
                    str(city.id): "London",
                },
            )


class DuplicateSubmissionTest(TestCase):
    """Fix #1: Duplicate submissions are rejected at the database level."""

    def setUp(self):
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
        self.field = Field.objects.create(
            section=self.section,
            label="Name",
            field_type=Field.FieldType.TEXT,
            order=1,
            required=True,
        )

    def test_duplicate_submission_raises_validation_error(self):
        survey_fields = {self.field.id: self.field}
        cleaned = {str(self.field.id): "Alice"}
        create_submission(
            survey=self.survey,
            user=self.customer,
            cleaned_answers=cleaned,
            survey_fields=survey_fields,
        )
        with self.assertRaises(ValidationError) as ctx:
            create_submission(
                survey=self.survey,
                user=self.customer,
                cleaned_answers=cleaned,
                survey_fields=survey_fields,
            )
        self.assertIn("survey", ctx.exception.errors)


class CheckboxSerializationTest(TestCase):
    """Fix #8: Checkbox list values should be stored as JSON, not Python repr."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.customer = User.objects.create_user(
            email="cust@example.com", password="p", role="customer"
        )
        self.survey = Survey.objects.create(
            title="S", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED
        )
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.checkbox_field = Field.objects.create(
            section=self.section,
            label="Hobbies",
            field_type=Field.FieldType.CHECKBOX,
            order=1,
            options=["reading", "gaming"],
        )

    def test_checkbox_value_stored_as_json(self):
        import json
        from apps.responses.models import FieldResponse

        survey_fields = {self.checkbox_field.id: self.checkbox_field}
        cleaned = {str(self.checkbox_field.id): ["reading", "gaming"]}
        response = create_submission(
            survey=self.survey,
            user=self.customer,
            cleaned_answers=cleaned,
            survey_fields=survey_fields,
        )
        fr = FieldResponse.objects.get(
            survey_response=response, field=self.checkbox_field
        )
        # Should be valid JSON, not Python repr
        parsed = json.loads(fr.value)
        self.assertEqual(parsed, ["reading", "gaming"])
