# Survey Platform

A Django REST Framework application for building and managing surveys with conditional logic, role-based access control, encrypted responses, and an audit trail.

## Prerequisites

- **Docker & Docker Compose** (recommended), or
- **Python 3.14+**, **PostgreSQL 17+**, and **Redis 8+** for running without Docker

## Quick Start (Docker)

1. **Clone the repository and create your `.env` file:**

   ```bash
   cp .env.example .env
   ```

2. **Generate an encryption key and add it to `.env`:**

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Set the output as the `ENCRYPTION_KEY` value in `.env`.

3. **Set passwords in `.env`:**

   Update `SECRET_KEY`, `REDIS_PASSWORD`, `DEFAULT_ADMIN_PASSWORD`, and optionally `JWT_SECRET_KEY`. Make sure the Redis password is consistent across `REDIS_PASSWORD`, `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND`.

4. **Start the stack:**

   ```bash
   docker compose up --build
   ```

   This starts PostgreSQL, Redis, the Django web server (port 8000), and a Celery worker. Migrations run automatically on container startup.

5. **Access the API:**

   - API root: http://localhost:8000/api/v1/
   - Swagger UI: http://localhost:8000/api/v1/docs/
   - ReDoc: http://localhost:8000/api/v1/redoc/
   - Django Admin: http://localhost:8000/admin/

   Log in with the `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` from your `.env`.

## Local Development (without Docker)

1. **Create and activate a virtual environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements-dev.txt
   ```

3. **Set up PostgreSQL and Redis:**

   Ensure PostgreSQL and Redis are running locally. Create a database:

   ```bash
   createdb survey_platform
   ```

4. **Configure environment variables:**

   ```bash
   cp .env.example .env
   ```

   Update the `.env` for local services:

   ```
   POSTGRES_HOST=localhost
   POSTGRES_DB=survey_platform
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   REDIS_URL=redis://localhost:6379/1
   CELERY_BROKER_URL=redis://localhost:6379/1
   CELERY_RESULT_BACKEND=redis://localhost:6379/2
   ENCRYPTION_KEY=<generate with the command above>
   ```

5. **Run migrations:**

   ```bash
   python manage.py migrate
   ```

6. **Create a superuser:**

   ```bash
   python manage.py createsuperuser
   ```

7. **Start the development server:**

   ```bash
   python manage.py runserver
   ```

8. **Start a Celery worker** (separate terminal):

   ```bash
   celery -A config.celery worker --loglevel=info
   ```

## Running Tests

```bash
# All tests (uses SQLite in-memory, no external services needed)
pytest

# Specific app
pytest apps/surveys/tests/

# Single test file
pytest apps/responses/tests/test_services.py

# Single test
pytest apps/surveys/tests/test_views.py::SurveyViewSetTest::test_list_surveys
```

## Security Scan

```bash
bandit -r apps/ -c bandit.yaml
```

## Load Testing

With the server running:

```bash
locust -f locustfile.py --host=http://localhost:8000
```

## API Endpoints

| Prefix | Description |
|--------|-------------|
| `/api/v1/auth/` | Registration, login (JWT), user management |
| `/api/v1/surveys/` | Survey CRUD with nested sections, fields, and rules |
| `/api/v1/surveys/{id}/submit/` | Survey submission |
| `/api/v1/surveys/{id}/responses/` | Response list, detail, and CSV export |
| `/api/v1/audit/` | Audit log (admin only) |
| `/api/v1/schema/` | OpenAPI 3 schema |
| `/api/v1/docs/` | Swagger UI |
| `/api/v1/redoc/` | ReDoc |

## Roles

| Role | Surveys | Responses | Users | Audit |
|------|---------|-----------|-------|-------|
| Admin | Full CRUD | View, export | Full CRUD | View |
| Data Analyst | Read | View, export | - | - |
| Data Viewer | Read | View only | - | - |
| Customer | Read published | Submit only | - | - |

## Project Structure

```
config/                 # Django project configuration
  settings/             # Split settings: base, dev, prod, test
apps/
  accounts/             # Custom User model (email-based), JWT auth, RBAC
  surveys/              # Survey -> Section -> Field hierarchy, conditional rules
  responses/            # Survey submissions, validation, Fernet encryption
  audit/                # Audit logging via signals + Celery
common/                 # Custom DRF exception handler
```
