import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.surveys.models import Field, Section, Survey

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@test.com", password="testpass123", role="admin",
        is_staff=True, is_superuser=True,
    )


@pytest.fixture
def analyst_user(db):
    return User.objects.create_user(
        email="analyst@test.com", password="testpass123", role="data_analyst",
    )


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        email="viewer@test.com", password="testpass123", role="data_viewer",
    )


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="customer@test.com", password="testpass123", role="customer",
    )


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def customer_client(api_client, customer_user):
    api_client.force_authenticate(user=customer_user)
    return api_client


@pytest.fixture
def analyst_client(api_client, analyst_user):
    api_client.force_authenticate(user=analyst_user)
    return api_client


@pytest.fixture
def viewer_client(api_client, viewer_user):
    api_client.force_authenticate(user=viewer_user)
    return api_client


@pytest.fixture
def survey(admin_user):
    return Survey.objects.create(
        title="Test Survey", description="A test survey",
        created_by=admin_user, status=Survey.SurveyStatus.PUBLISHED,
    )


@pytest.fixture
def section(survey):
    return Section.objects.create(
        survey=survey, title="Section 1", order=1,
    )


@pytest.fixture
def text_field(section):
    return Field.objects.create(
        section=section, label="Name", field_type=Field.FieldType.TEXT,
        required=True, order=1,
    )


@pytest.fixture
def dropdown_field(section):
    return Field.objects.create(
        section=section, label="Color", field_type="dropdown",
        required=False, order=2, options=["Red", "Blue", "Green"],
    )
