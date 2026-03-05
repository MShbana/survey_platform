# Architecture

## Overview

The Survey Platform is a Django REST Framework application that provides a multi-step survey builder with conditional logic, role-based access control (RBAC), encrypted field storage, and an asynchronous audit trail.

## Technology Stack

| Component       | Technology                          |
|-----------------|-------------------------------------|
| Framework       | Django 5.2 + Django REST Framework  |
| Database        | PostgreSQL 17                       |
| Cache           | Redis 8 (via django-redis)          |
| Task Queue      | Celery with Redis broker            |
| Authentication  | JWT (djangorestframework-simplejwt) |
| Encryption      | Fernet symmetric encryption         |
| API Docs        | drf-spectacular (OpenAPI 3)         |
| Containerization| Docker + Docker Compose             |

## Project Layout

```
survey_platform/
  config/                   # Django project configuration
    settings/
      base.py               # Shared settings (DRF, JWT, Celery, logging)
      dev.py                # DEBUG=True, local PostgreSQL + Redis, CORS open
      prod.py               # DEBUG=False, env-only config, security hardening
      test.py               # In-memory SQLite, LocMemCache, eager Celery
    urls.py                 # Root URL configuration
    celery.py               # Celery application
    wsgi.py / asgi.py       # WSGI/ASGI entry points
  apps/
    accounts/               # Custom User model, JWT auth, RBAC permissions
    surveys/                # Survey -> Section -> Field, rules, dependencies
    responses/              # Submission, validation, encryption
    audit/                  # Audit logging via signals + Celery
    common/                 # Custom DRF exception handler
  conftest.py               # Global pytest fixtures
  manage.py                 # Django management (defaults to dev settings)
```

## Application Architecture

### Layered Design

Each app follows a consistent layered pattern:

```
Views (API layer)
  |
  v
Serializers (validation + representation)
  |
  v
Services (business logic — pure functions)
  |
  v
Models (data layer)
```

- **Views** handle HTTP concerns: authentication, permissions, response codes, caching.
- **Serializers** are split by action: list, detail, and write serializers. Views select the appropriate serializer via `get_serializer_class()`.
- **Services** (`services.py`) contain all business logic as pure functions. This keeps views thin and logic testable in isolation.
- **Models** define the data schema and relationships only.

### Data Model

```
Survey (title, description, status, created_by)
  |
  |-- Section (title, description, order)  [ordered, unique per survey]
  |     |
  |     |-- Field (label, field_type, required, order, options, validation_rules, is_encrypted)
  |
  |-- ConditionalRule (depends_on_field -> target_section | target_field, operator, value)
  |
  |-- FieldDependency (depends_on_field -> dependent_field, operator, value, action, action_value)

SurveyResponse (survey, user, submitted_at)
  |
  |-- FieldResponse (field, value)

AuditLog (user, action, model_name, object_id, details, ip_address, timestamp)
```

### Key Design Decisions

**Survey status machine**: Surveys follow a forward-only state machine: `draft -> published -> archived`. Only draft surveys can have their structure modified. Publishing requires at least one section with at least one field.

**Conditional rules use OR logic**: If multiple rules target the same section or field, the target is shown when ANY rule is satisfied. Sections/fields without rules are always visible.

**Field dependencies modify behavior, not visibility**: Unlike conditional rules (which show/hide), field dependencies alter options (`show_options`, `hide_options`) or set values (`set_value`) on other fields.

**Denormalized survey FK on rules/dependencies**: `ConditionalRule` and `FieldDependency` have a direct `survey` FK for efficient querying, even though the relationship can be derived through the field chain.

## Request Flow

### Survey Submission Pipeline

```
POST /api/v1/surveys/{id}/submit/
  |
  v
SurveySubmitView.post()
  |-- Verify survey exists and is published
  |-- Deserialize + validate field IDs exist
  |-- Verify all field IDs belong to this survey
  |
  v
validate_submission()  (services layer, ~5 queries)
  |-- prefetch_survey_structure() — load all survey data
  |-- get_visible_sections() — evaluate section conditional rules
  |-- get_visible_fields() — evaluate field conditional rules
  |-- resolve_dependencies() — compute option modifications
  |-- For each visible field:
  |     |-- Required check
  |     |-- Type validation (number, email, date, dropdown, checkbox)
  |     |-- Custom rules (min, max, min_length, max_length, regex)
  |     |-- Dependency constraint check (allowed/hidden options)
  |
  v
create_submission()  (atomic transaction)
  |-- Create SurveyResponse
  |-- Encrypt values for is_encrypted fields
  |-- Bulk-create FieldResponse records
  |
  v
201 Created  {"id": <response_id>, "message": "..."}
```

### Caching Strategy

- **Scope**: Survey detail (`retrieve`) action only, key pattern `survey:{pk}:structure`.
- **TTL**: 15 minutes (`SURVEY_CACHE_TIMEOUT`).
- **Invalidation**: All mutating operations (create, update, delete) on surveys, sections, fields, rules, and dependencies call `SurveyCacheService.invalidate_structure()`.
- **Role-aware**: Cache is only used for admin detail views. Non-admin users get role-filtered sections (empty sections are hidden).

### Audit Trail

```
Model save/delete
  |
  v
Django post_save / post_delete signal
  |-- Check if sender is a tracked model
  |-- Read user + IP from thread-local storage (set by AuditIPMiddleware)
  |
  v
create_audit_log.delay()  (Celery async task)
  |
  v
AuditLog.objects.create()
```

Tracked models: `Survey`, `Section`, `Field`, `ConditionalRule`, `FieldDependency`, `SurveyResponse`.

Additional manual audit logging occurs in response list, detail, and export views.

## Settings Strategy

| Setting File  | `DJANGO_SETTINGS_MODULE` Used By       | Database     | Cache        | Debug |
|---------------|----------------------------------------|--------------|--------------|-------|
| `dev.py`      | `manage.py`                            | PostgreSQL   | Redis        | True  |
| `prod.py`     | `wsgi.py`, `asgi.py`, `celery.py`, Docker | PostgreSQL   | Redis        | False |
| `test.py`     | `setup.cfg` (pytest)                   | SQLite :memory: | LocMemCache  | False |

Production adds: HSTS, SSL redirect, secure cookies, rotating file logging, `CONN_MAX_AGE=60`.

## Rate Limiting

Default throttle rates configured in DRF:

| Scope       | Rate           |
|-------------|----------------|
| Anonymous   | 30/minute      |
| Authenticated | 120/minute   |
