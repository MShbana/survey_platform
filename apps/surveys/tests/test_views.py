from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.surveys.models import (
    ComparisonOperator,
    ConditionalRule,
    Field,
    FieldDependency,
    Section,
    Survey,
)

User = get_user_model()


class SurveyViewSetTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.customer = User.objects.create_user(email="cust@example.com", password="p", role="customer")
        self.analyst = User.objects.create_user(email="analyst@example.com", password="p", role="data_analyst")

    def test_create_survey_admin(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post("/api/v1/surveys/", {"title": "New Survey"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["title"], "New Survey")

    def test_create_survey_customer_forbidden(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post("/api/v1/surveys/", {"title": "Bad"})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_surveys_any_authenticated(self):
        Survey.objects.create(title="S1", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get("/api/v1/surveys/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_customer_only_sees_published_surveys(self):
        Survey.objects.create(title="Draft", created_by=self.admin, status=Survey.SurveyStatus.DRAFT)
        Survey.objects.create(title="Published", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED)
        Survey.objects.create(title="Archived", created_by=self.admin, status=Survey.SurveyStatus.ARCHIVED)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get("/api/v1/surveys/")
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["title"], "Published")

    def test_admin_sees_all_statuses(self):
        Survey.objects.create(title="Draft", created_by=self.admin, status=Survey.SurveyStatus.DRAFT)
        Survey.objects.create(title="Published", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED)
        Survey.objects.create(title="Archived", created_by=self.admin, status=Survey.SurveyStatus.ARCHIVED)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/surveys/")
        self.assertEqual(resp.data["count"], 3)

    def test_customer_gets_404_for_draft_survey_detail(self):
        survey = Survey.objects.create(title="S1", created_by=self.admin, status=Survey.SurveyStatus.DRAFT)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(f"/api/v1/surveys/{survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_survey_detail(self):
        survey = Survey.objects.create(title="S1", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        Field.objects.create(section=section, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(f"/api/v1/surveys/{survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["sections"]), 1)
        self.assertEqual(len(resp.data["sections"][0]["fields"]), 1)

    def test_status_transition_via_patch(self):
        survey = Survey.objects.create(title="S", created_by=self.admin)
        section = Section.objects.create(survey=survey, title="Sec", order=1)
        Field.objects.create(section=section, label="Q1", field_type=Field.FieldType.TEXT, order=1)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            f"/api/v1/surveys/{survey.id}/", {"status": Survey.SurveyStatus.PUBLISHED}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        survey.refresh_from_db()
        self.assertEqual(survey.status, Survey.SurveyStatus.PUBLISHED)

    def test_invalid_transition_returns_400(self):
        survey = Survey.objects.create(title="S", created_by=self.admin, status=Survey.SurveyStatus.ARCHIVED)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            f"/api/v1/surveys/{survey.id}/", {"status": Survey.SurveyStatus.PUBLISHED}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_publish_empty_survey_returns_400(self):
        survey = Survey.objects.create(title="S", created_by=self.admin)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            f"/api/v1/surveys/{survey.id}/", {"status": Survey.SurveyStatus.PUBLISHED}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_survey_admin(self):
        survey = Survey.objects.create(title="Old", created_by=self.admin)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f"/api/v1/surveys/{survey.id}/", {"title": "New"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_survey_admin(self):
        survey = Survey.objects.create(title="Del", created_by=self.admin)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.delete(f"/api/v1/surveys/{survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_unauthenticated_access(self):
        resp = self.client.get("/api/v1/surveys/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class SectionViewSetTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.admin)

    def test_create_section(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/",
            {"title": "Section 1", "order": 1},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_list_sections(self):
        Section.objects.create(survey=self.survey, title="S1", order=1)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/sections/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)


class FieldViewSetTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.admin)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)

    def test_create_field(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {"label": "Name", "field_type": Field.FieldType.TEXT, "order": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_dropdown_without_options_fails(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/v1/surveys/{self.survey.id}/sections/{self.section.id}/fields/",
            {"label": "Pick", "field_type": Field.FieldType.DROPDOWN, "order": 1, "options": []},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class SurveyDetailSectionFilteringTest(TestCase):
    """Fix #13: Non-admin users don't see empty sections in detail view."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.customer = User.objects.create_user(
            email="cust@example.com", password="p", role="customer"
        )
        self.survey = Survey.objects.create(
            title="S", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED
        )
        self.section_with_fields = Section.objects.create(
            survey=self.survey, title="Has Fields", order=1
        )
        Field.objects.create(
            section=self.section_with_fields,
            label="Q1",
            field_type=Field.FieldType.TEXT,
            order=1,
        )
        self.empty_section = Section.objects.create(
            survey=self.survey, title="Empty", order=2
        )

    def test_customer_does_not_see_empty_sections(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["sections"]), 1)
        self.assertEqual(resp.data["sections"][0]["title"], "Has Fields")

    def test_admin_sees_all_sections_including_empty(self):
        from django.core.cache import cache as django_cache
        django_cache.clear()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["sections"]), 2)


class SurveyCacheIntegrationTest(TestCase):
    """Integration tests verifying cache behaviour through the API."""

    def setUp(self):
        from django.core.cache import cache as django_cache

        self.client = APIClient()
        self.admin = User.objects.create_user(email="admin@example.com", password="p", role="admin")
        self.survey = Survey.objects.create(title="S", created_by=self.admin, status=Survey.SurveyStatus.PUBLISHED)
        Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.client.force_authenticate(user=self.admin)
        django_cache.clear()

    def test_retrieve_caches_response(self):
        from apps.surveys.cache import SurveyCacheService

        self.assertIsNone(SurveyCacheService.get_structure(self.survey.id))
        resp = self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cached = SurveyCacheService.get_structure(self.survey.id)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["title"], "S")

    def test_update_invalidates_cache(self):
        from apps.surveys.cache import SurveyCacheService

        # Populate cache
        self.client.get(f"/api/v1/surveys/{self.survey.id}/")
        self.assertIsNotNone(SurveyCacheService.get_structure(self.survey.id))
        # Update should invalidate
        self.client.patch(f"/api/v1/surveys/{self.survey.id}/", {"title": "Updated"})
        self.assertIsNone(SurveyCacheService.get_structure(self.survey.id))


class ConditionalRuleCircularDependencyAPITest(TestCase):
    """Fix #4: Circular dependency detection in API path for ConditionalRules."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.client.force_authenticate(user=self.admin)
        self.survey = Survey.objects.create(title="S", created_by=self.admin)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.q1 = Field.objects.create(
            section=self.section, label="Q1", field_type=Field.FieldType.TEXT, order=1
        )
        self.q2 = Field.objects.create(
            section=self.section, label="Q2", field_type=Field.FieldType.TEXT, order=2
        )
        self.q3 = Field.objects.create(
            section=self.section, label="Q3", field_type=Field.FieldType.TEXT, order=3
        )

    def test_circular_cr_rejected_via_api(self):
        # q1 → show q2
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.q2,
            depends_on_field=self.q1,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )
        # q2 → show q3
        ConditionalRule.objects.create(
            survey=self.survey,
            target_field=self.q3,
            depends_on_field=self.q2,
            operator=ComparisonOperator.EQUALS,
            value="yes",
        )
        # Try q3 → show q1 (would create cycle q1→q2→q3→q1)
        url = f"/api/v1/surveys/{self.survey.id}/conditional-rules/"
        resp = self.client.post(
            url,
            {
                "target_field": self.q1.id,
                "depends_on_field": self.q3.id,
                "operator": ComparisonOperator.EQUALS,
                "value": "yes",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class FieldDependencyCircularDependencyAPITest(TestCase):
    """Fix #4: Circular dependency detection in API path for FieldDependencies."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="p", role="admin"
        )
        self.client.force_authenticate(user=self.admin)
        self.survey = Survey.objects.create(title="S", created_by=self.admin)
        self.section = Section.objects.create(survey=self.survey, title="Sec", order=1)
        self.q1 = Field.objects.create(
            section=self.section,
            label="Q1",
            field_type=Field.FieldType.DROPDOWN,
            order=1,
            options=["a", "b"],
        )
        self.q2 = Field.objects.create(
            section=self.section,
            label="Q2",
            field_type=Field.FieldType.DROPDOWN,
            order=2,
            options=["c", "d"],
        )

    def test_circular_fd_rejected_via_api(self):
        # q1 → affects q2
        FieldDependency.objects.create(
            survey=self.survey,
            dependent_field=self.q2,
            depends_on_field=self.q1,
            operator=ComparisonOperator.EQUALS,
            value="a",
            action="show_options",
            action_value=["c"],
        )
        # Try q2 → affects q1 (cycle)
        url = f"/api/v1/surveys/{self.survey.id}/field-dependencies/"
        resp = self.client.post(
            url,
            {
                "dependent_field": self.q1.id,
                "depends_on_field": self.q2.id,
                "operator": ComparisonOperator.EQUALS,
                "value": "c",
                "action": "show_options",
                "action_value": ["a"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
