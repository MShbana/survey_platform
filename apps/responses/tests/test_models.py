from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.responses.models import FieldResponse, SurveyResponse
from apps.surveys.models import Field, Section, Survey

User = get_user_model()


class ResponseModelTest(TestCase):
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
        self.field = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )

    def test_create_response(self):
        resp = SurveyResponse.objects.create(survey=self.survey, user=self.customer)
        self.assertIn("S", str(resp))
        self.assertIn("cust@example.com", str(resp))

    def test_create_field_response(self):
        resp = SurveyResponse.objects.create(survey=self.survey, user=self.customer)
        fr = FieldResponse.objects.create(
            survey_response=resp, field=self.field, value="Hello"
        )
        self.assertIn("Q1", str(fr))
