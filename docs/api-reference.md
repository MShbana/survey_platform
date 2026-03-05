# API Reference

All endpoints are under the `/api/v1/` prefix. Authentication is via JWT Bearer tokens unless noted otherwise.

## Authentication

### Register

```
POST /api/v1/auth/register/
```

No authentication required. Creates a new user account.

**Request body:**

| Field       | Type   | Required | Description                                      |
|-------------|--------|----------|--------------------------------------------------|
| email       | string | Yes      | Unique email address                              |
| password    | string | Yes      | Minimum 8 characters                              |
| first_name  | string | No       | First name                                        |
| last_name   | string | No       | Last name                                         |
| role        | string | No       | `customer` (default), `admin`, `data_analyst`, `data_viewer` |

Only admins can create users with non-customer roles. Unauthenticated callers can only register as `customer`.

**Response:** `201 Created`

```json
{
    "id": 2,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "role": "customer"
}
```

### Login

```
POST /api/v1/auth/login/
```

No authentication required. Returns a JWT access + refresh token pair.

**Request body:**

| Field    | Type   | Required |
|----------|--------|----------|
| email    | string | Yes      |
| password | string | Yes      |

**Response:** `200 OK`

```json
{
    "access": "eyJ...",
    "refresh": "eyJ..."
}
```

Token lifetimes: access = 200 minutes, refresh = 1 day.

### Refresh Token

```
POST /api/v1/auth/refresh/
```

**Request body:**

| Field   | Type   | Required |
|---------|--------|----------|
| refresh | string | Yes      |

**Response:** `200 OK`

```json
{
    "access": "eyJ..."
}
```

### Me (Current User)

```
GET /api/v1/auth/me/
```

Returns the authenticated user's profile.

**Response:** `200 OK`

```json
{
    "id": 1,
    "email": "admin@example.com",
    "first_name": "Admin",
    "last_name": "User",
    "role": "admin",
    "is_active": true,
    "date_joined": "2026-01-15T10:30:00Z"
}
```

### List Users (Admin)

```
GET /api/v1/auth/users/
```

Admin only. Paginated list with filtering and search.

**Query parameters:**

| Param     | Description                                 |
|-----------|---------------------------------------------|
| role      | Filter: `admin`, `data_analyst`, `data_viewer`, `customer` |
| is_active | Filter: `true` or `false`                   |
| search    | Search across email, first_name, last_name  |

### Retrieve / Update User (Admin)

```
GET    /api/v1/auth/users/{id}/
PUT    /api/v1/auth/users/{id}/
PATCH  /api/v1/auth/users/{id}/
```

Admin only. PUT requires all fields; PATCH accepts partial updates.

**Writable fields:** `email`, `first_name`, `last_name`, `role`, `is_active`.

---

## Surveys

### List / Create Surveys

```
GET  /api/v1/surveys/
POST /api/v1/surveys/
```

- **GET**: Any authenticated user. Customers only see published surveys.
- **POST**: Admin only. New surveys must be created with `draft` status.

**Query parameters (GET):**

| Param    | Description                                          |
|----------|------------------------------------------------------|
| status   | Filter: `draft`, `published`, `archived`             |
| search   | Full-text search on title and description            |
| ordering | Sort by `created_at` or `title` (prefix `-` for desc)|

**Request body (POST):**

```json
{
    "title": "Customer Satisfaction Survey",
    "description": "Annual feedback form",
    "status": "draft"
}
```

### Retrieve / Update / Delete Survey

```
GET    /api/v1/surveys/{id}/
PUT    /api/v1/surveys/{id}/
PATCH  /api/v1/surveys/{id}/
DELETE /api/v1/surveys/{id}/
```

- **GET**: Returns the full survey structure (sections, fields, conditional rules, field dependencies). Cached for 15 minutes. Non-admin users see only sections with fields.
- **PUT/PATCH**: Admin only. Status transitions: `draft -> published -> archived`. Publishing requires at least one section with fields.
- **DELETE**: Admin only. Cascades to all related data.

---

## Sections

All section endpoints require admin role. Survey must be in `draft` status for write operations.

### List / Create Sections

```
GET  /api/v1/surveys/{survey_id}/sections/
POST /api/v1/surveys/{survey_id}/sections/
```

**Request body (POST):**

```json
{
    "title": "Personal Information",
    "description": "Basic details",
    "order": 1
}
```

If `order` is omitted, auto-assigns the next available value.

### Retrieve / Update / Delete Section

```
GET    /api/v1/surveys/{survey_id}/sections/{id}/
PUT    /api/v1/surveys/{survey_id}/sections/{id}/
PATCH  /api/v1/surveys/{survey_id}/sections/{id}/
DELETE /api/v1/surveys/{survey_id}/sections/{id}/
```

---

## Fields

All field endpoints require admin role. Survey must be in `draft` status for write operations.

### List / Create Fields

```
GET  /api/v1/surveys/{survey_id}/sections/{section_id}/fields/
POST /api/v1/surveys/{survey_id}/sections/{section_id}/fields/
```

**Field types:** `text`, `number`, `date`, `dropdown`, `checkbox`, `radio`, `textarea`, `email`

**Request body (POST):**

```json
{
    "label": "Country",
    "field_type": "dropdown",
    "required": true,
    "order": 1,
    "options": ["Kuwait", "UAE", "Saudi Arabia"],
    "is_encrypted": false,
    "validation_rules": {}
}
```

**Options:** Required for `dropdown`, `radio`, and `checkbox` types. Must be an array of strings.

**Validation rules** (JSON object, all optional):

| Key        | Applies to        | Description              |
|------------|-------------------|--------------------------|
| min        | number            | Minimum numeric value    |
| max        | number            | Maximum numeric value    |
| min_length | text, textarea, email | Minimum string length |
| max_length | text, textarea, email | Maximum string length |
| regex      | text, textarea, email | Regex pattern to match |

**Encryption:** Set `is_encrypted: true` to encrypt response values at rest using Fernet.

### Retrieve / Update / Delete Field

```
GET    /api/v1/surveys/{survey_id}/sections/{section_id}/fields/{id}/
PUT    /api/v1/surveys/{survey_id}/sections/{section_id}/fields/{id}/
PATCH  /api/v1/surveys/{survey_id}/sections/{section_id}/fields/{id}/
DELETE /api/v1/surveys/{survey_id}/sections/{section_id}/fields/{id}/
```

---

## Conditional Rules

Control visibility of sections or fields based on another field's answer. Admin only. Survey must be in `draft` status.

### List / Create Rules

```
GET  /api/v1/surveys/{survey_id}/conditional-rules/
POST /api/v1/surveys/{survey_id}/conditional-rules/
```

**Request body (POST):**

```json
{
    "target_section": 2,
    "target_field": null,
    "depends_on_field": 1,
    "operator": "equals",
    "value": "Yes"
}
```

**Constraints:**
- Exactly one of `target_section` or `target_field` must be set (the other must be `null`).
- All referenced objects must belong to the same survey.
- No self-reference or circular dependencies allowed.

**Operators:** `equals`, `not_equals`, `contains`, `greater_than`, `less_than`, `in`

The `in` operator expects `value` to be a JSON array. The `greater_than` and `less_than` operators coerce values to floats.

**OR logic:** If multiple rules target the same section/field, the target is shown when ANY rule is satisfied.

### Retrieve / Update / Delete Rule

```
GET    /api/v1/surveys/{survey_id}/conditional-rules/{id}/
PUT    /api/v1/surveys/{survey_id}/conditional-rules/{id}/
PATCH  /api/v1/surveys/{survey_id}/conditional-rules/{id}/
DELETE /api/v1/surveys/{survey_id}/conditional-rules/{id}/
```

---

## Field Dependencies

Modify a field's options or value based on another field's answer. Admin only. Survey must be in `draft` status.

### List / Create Dependencies

```
GET  /api/v1/surveys/{survey_id}/field-dependencies/
POST /api/v1/surveys/{survey_id}/field-dependencies/
```

**Request body (POST):**

```json
{
    "dependent_field": 4,
    "depends_on_field": 3,
    "operator": "equals",
    "value": "Kuwait",
    "action": "show_options",
    "action_value": ["Kuwait City", "Hawalli", "Ahmadi"]
}
```

**Actions:**

| Action        | Description                                              | action_value type |
|---------------|----------------------------------------------------------|-------------------|
| show_options  | Show only these options on the dependent field           | array of strings  |
| hide_options  | Hide these options from the dependent field              | array of strings  |
| set_value     | Set the dependent field's value                          | any JSON value    |

**Operators:** Same as conditional rules.

### Retrieve / Update / Delete Dependency

```
GET    /api/v1/surveys/{survey_id}/field-dependencies/{id}/
PUT    /api/v1/surveys/{survey_id}/field-dependencies/{id}/
PATCH  /api/v1/surveys/{survey_id}/field-dependencies/{id}/
DELETE /api/v1/surveys/{survey_id}/field-dependencies/{id}/
```

---

## Responses

### Submit a Survey Response

```
POST /api/v1/surveys/{survey_id}/submit/
```

Customer role only. Survey must be published. Each user can submit only once per survey.

**Request body:**

```json
{
    "answers": [
        {"field_id": 1, "value": "John Doe"},
        {"field_id": 2, "value": 25},
        {"field_id": 3, "value": "Excellent"},
        {"field_id": 4, "value": ["Option A", "Option B"]}
    ]
}
```

**Value types by field type:**

| Field Type | Value Type             | Example                |
|------------|------------------------|------------------------|
| text       | string                 | `"John Doe"`           |
| textarea   | string                 | `"Long text..."`       |
| email      | string                 | `"user@example.com"`   |
| number     | number                 | `25`                   |
| date       | string (YYYY-MM-DD)    | `"2026-03-01"`         |
| dropdown   | string (from options)  | `"Kuwait"`             |
| radio      | string (from options)  | `"Male"`               |
| checkbox   | array of strings       | `["A", "B"]`           |

**Response:** `201 Created`

```json
{
    "id": 1,
    "message": "Response submitted successfully."
}
```

**Error response:** `400 Bad Request`

```json
{
    "errors": {
        "1": "This field is required.",
        "6": "Value must be at least 18."
    }
}
```

### List Survey Responses

```
GET /api/v1/surveys/{survey_id}/responses/
```

Admin, Data Analyst, and Data Viewer roles. Paginated. Audit-logged.

### Retrieve a Survey Response

```
GET /api/v1/surveys/{survey_id}/responses/{id}/
```

Admin, Data Analyst, and Data Viewer roles. Returns all field answers with labels and types. Encrypted values are transparently decrypted. Audit-logged.

---

## Audit Logs

```
GET /api/v1/audit/logs/
```

Admin only. Paginated list of all audit trail entries.

**Query parameters:**

| Param      | Description                                                |
|------------|------------------------------------------------------------|
| action     | Filter: `create`, `update`, `delete`, `view`               |
| model_name | Filter: `Survey`, `Section`, `Field`, `ConditionalRule`, `FieldDependency`, `SurveyResponse` |
| user       | Filter by user ID                                          |
| search     | Search across model_name and object_id                     |
| ordering   | Sort by `timestamp` (prefix `-` for descending)            |

---

## Pagination

All list endpoints use page number pagination:

```json
{
    "count": 50,
    "next": "http://localhost:8000/api/v1/surveys/?page=2",
    "previous": null,
    "results": [...]
}
```

Default page size: 20.

## API Documentation (Interactive)

| Endpoint              | Description         |
|-----------------------|---------------------|
| `/api/v1/schema/`     | OpenAPI 3 schema    |
| `/api/v1/docs/`       | Swagger UI          |
| `/api/v1/redoc/`      | ReDoc               |
