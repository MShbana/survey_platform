from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet
from rest_framework import status
from rest_framework.test import APIClient

from apps.surveys.models import Field, Section, Survey

User = get_user_model()
TEST_KEY = Fernet.generate_key().decode()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, ENCRYPTION_KEY=TEST_KEY)
class SubmissionViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.customer = User.objects.create_user(
            email="cust@example.com", password="p", role="customer"
        )
        self.analyst = User.objects.create_user(
            email="analyst@example.com", password="p", role="data_analyst"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="p", role="data_viewer"
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

    def test_submit_response(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {"answers": [{"field_id": self.field.id, "value": "John"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", resp.data)

    def test_submit_missing_required(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {"answers": []},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_non_customer_forbidden(self):
        self.client.force_authenticate(user=self.analyst)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {"answers": [{"field_id": self.field.id, "value": "John"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_submit_draft_survey(self):
        self.survey.status = Survey.SurveyStatus.DRAFT
        self.survey.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {"answers": [{"field_id": self.field.id, "value": "John"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_archived_survey(self):
        self.survey.status = Survey.SurveyStatus.ARCHIVED
        self.survey.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {"answers": [{"field_id": self.field.id, "value": "John"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_responses_analyst(self):
        self.client.force_authenticate(user=self.analyst)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/responses/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_list_responses_viewer(self):
        self.client.force_authenticate(user=self.viewer)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/responses/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_list_responses_customer_forbidden(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/responses/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_encrypted_field_roundtrip(self):
        enc_field = Field.objects.create(
            section=self.section,
            label="SSN",
            field_type=Field.FieldType.TEXT,
            order=2,
            is_encrypted=True,
            required=True,
        )
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/submit/",
            {
                "answers": [
                    {"field_id": self.field.id, "value": "John"},
                    {"field_id": enc_field.id, "value": "123-45-6789"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        from apps.responses.models import FieldResponse

        fr = FieldResponse.objects.get(field=enc_field)
        self.assertNotEqual(fr.value, "123-45-6789")  # encrypted at rest


class ResponseListDetailNonexistentSurveyTest(TestCase):
    """Fix #17: Response list/detail return 404 for nonexistent survey."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.client.force_authenticate(user=self.admin)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_list_responses_nonexistent_survey_returns_404(self):
        resp = self.client.get("/api/v1/surveys/99999/responses/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_detail_response_nonexistent_survey_returns_404(self):
        resp = self.client.get("/api/v1/surveys/99999/responses/1/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class IntegrationTest(TestCase):
    """Full flow: create survey → add sections → add fields → submit → view."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, ENCRYPTION_KEY=TEST_KEY)
    def test_full_survey_flow(self):
        client = APIClient()
        admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        customer = User.objects.create_user(
            email="cust@example.com", password="p", role="customer"
        )

        # Admin creates survey
        client.force_authenticate(user=admin)
        resp = client.post("/api/v1/surveys/", {"title": "Feedback"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        survey_id = resp.data["id"]

        # Add section
        resp = client.post(
            f"/api/v1/surveys/{survey_id}/sections/",
            {"title": "General", "order": 1},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        section_id = resp.data["id"]

        # Add fields
        resp = client.post(
            f"/api/v1/surveys/{survey_id}/sections/{section_id}/fields/",
            {
                "label": "Name",
                "field_type": Field.FieldType.TEXT,
                "order": 1,
                "required": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        name_field_id = resp.data["id"]

        resp = client.post(
            f"/api/v1/surveys/{survey_id}/sections/{section_id}/fields/",
            {
                "label": "Rating",
                "field_type": Field.FieldType.DROPDOWN,
                "order": 2,
                "required": True,
                "options": ["1", "2", "3", "4", "5"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        rating_field_id = resp.data["id"]

        # Activate survey
        resp = client.patch(
            f"/api/v1/surveys/{survey_id}/", {"status": Survey.SurveyStatus.PUBLISHED}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Customer submits
        client.force_authenticate(user=customer)
        resp = client.post(
            f"/api/v1/surveys/{survey_id}/submit/",
            {
                "answers": [
                    {"field_id": name_field_id, "value": "Alice"},
                    {"field_id": rating_field_id, "value": "5"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        response_id = resp.data["id"]

        # Admin views responses
        client.force_authenticate(user=admin)
        resp = client.get(f"/api/v1/surveys/{survey_id}/responses/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

        resp = client.get(f"/api/v1/surveys/{survey_id}/responses/{response_id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["field_responses"]), 2)
