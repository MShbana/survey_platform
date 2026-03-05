# Testing

## Configuration

Tests use a dedicated settings module: `config.settings.test` (configured in `setup.cfg`).

| Setting      | Value                        | Why                                    |
|--------------|------------------------------|----------------------------------------|
| Database     | SQLite `:memory:`            | Fast, no external dependency           |
| Cache        | `LocMemCache`                | In-process, no Redis needed            |
| Celery       | `CELERY_TASK_ALWAYS_EAGER`   | Tasks execute synchronously inline     |
| Password     | `MD5PasswordHasher`          | Faster hashing for test performance    |
| Logging      | `CRITICAL` level             | Suppress noise during test runs        |
| DEBUG        | `False`                      | Match production behavior              |

## Running Tests

```bash
# All tests
pytest

# Specific app
pytest apps/surveys/tests/
pytest apps/accounts/tests/
pytest apps/responses/tests/
pytest apps/audit/tests/

# Single test file
pytest apps/responses/tests/test_services.py

# Single test class
pytest apps/surveys/tests/test_views.py::SurveyViewSetTest

# Single test method
pytest apps/surveys/tests/test_views.py::SurveyViewSetTest::test_list_surveys

# With verbose output
pytest -v

# Stop on first failure
pytest -x
```

## Test Structure

Each app has a `tests/` directory with files organized by layer:

```
apps/{app}/tests/
  __init__.py
  test_models.py        # Model validation, constraints, clean() methods
  test_serializers.py   # Serializer validation, field checks
  test_services.py      # Business logic (pure function tests)
  test_views.py         # API endpoint integration tests
  test_permissions.py   # Role-based access (accounts app)
  test_cache.py         # Cache behavior (surveys app)
  test_validations.py   # Field/rule validation logic (surveys app)
```

## Global Fixtures

Defined in `conftest.py` at the project root. Available to all test files.

### User Fixtures

| Fixture          | Email              | Role           | Notes           |
|------------------|--------------------|----------------|-----------------|
| `admin_user`     | admin@test.com     | admin          | is_staff=True, is_superuser=True |
| `customer_user`  | customer@test.com  | customer       |                 |
| `analyst_user`   | analyst@test.com   | data_analyst   |                 |
| `viewer_user`    | viewer@test.com    | data_viewer    |                 |

All use password `testpass123`.

### Authenticated Client Fixtures

| Fixture           | Authenticates as |
|-------------------|------------------|
| `admin_client`    | admin_user       |
| `customer_client` | customer_user    |
| `analyst_client`  | analyst_user     |
| `viewer_client`   | viewer_user      |

These are `APIClient` instances with `force_authenticate()` applied.

### Data Fixtures

| Fixture          | Creates                                          |
|------------------|--------------------------------------------------|
| `survey`         | Published survey (title: "Test Survey")           |
| `section`        | Section in the survey (title: "Section 1", order: 1) |
| `text_field`     | Required text field (label: "Name", order: 1)     |
| `dropdown_field` | Optional dropdown (label: "Color", options: Red/Blue/Green, order: 2) |

## Testing Patterns

### Surveys App

Tests in the surveys app use `django.test.TestCase` (not pytest fixtures) for class-based test organization.

### Cache Tests

When testing role-based detail view responses, clear the cache between tests to avoid stale cached data:

```python
from django.core.cache import cache

def setUp(self):
    cache.clear()
```

### Testing Permissions

Permission tests verify that each role gets the expected HTTP status code:

```python
def test_admin_can_create_survey(self):
    response = self.admin_client.post("/api/v1/surveys/", data)
    self.assertEqual(response.status_code, 201)

def test_customer_cannot_create_survey(self):
    response = self.customer_client.post("/api/v1/surveys/", data)
    self.assertEqual(response.status_code, 403)
```

## Security Scanning

```bash
# Bandit static analysis for security issues
bandit -r apps/ -c bandit.yaml
```

## Load Testing

Requires a running server:

```bash
locust -f locustfile.py --host=http://localhost:8000
```

Then open the Locust web UI at http://localhost:8089.
