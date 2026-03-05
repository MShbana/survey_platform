# Data Models

## Entity Relationship Diagram

```
                    ┌──────────────┐
                    │     User     │
                    │──────────────│
                    │ email (UK)   │
                    │ password     │
                    │ first_name   │
                    │ last_name    │
                    │ role         │
                    │ is_active    │
                    │ date_joined  │
                    └──────┬───────┘
                           │ created_by (FK)
                           │
                    ┌──────▼───────┐
                    │    Survey    │
                    │──────────────│
                    │ title        │
                    │ description  │
                    │ status       │
                    │ created_at   │
                    │ updated_at   │
                    └──┬───┬───┬───┘
                       │   │   │
          ┌────────────┘   │   └─────────────────┐
          │                │                     │
   ┌──────▼───────┐  ┌────▼──────────────┐  ┌───▼──────────────┐
   │   Section    │  │ ConditionalRule   │  │ FieldDependency  │
   │──────────────│  │──────────────────│  │─────────────────│
   │ title        │  │ target_section FK│  │ dependent_field FK│
   │ description  │  │ target_field   FK│  │ depends_on_field FK│
   │ order (UK)   │  │ depends_on_field FK│ │ operator         │
   └──────┬───────┘  │ operator         │  │ value            │
          │          │ value            │  │ action           │
   ┌──────▼───────┐  └─────────────────┘  │ action_value     │
   │    Field     │                       └──────────────────┘
   │──────────────│
   │ label        │
   │ field_type   │
   │ required     │
   │ order (UK)   │
   │ options      │
   │ is_encrypted │
   │ validation_rules│
   └──────┬───────┘
          │
   ┌──────▼─────────────┐
   │  SurveyResponse    │
   │────────────────────│
   │ survey FK          │
   │ user FK            │     ┌────────────────┐
   │ submitted_at       │     │  FieldResponse │
   │ (survey,user) UK   │────>│────────────────│
   └────────────────────┘     │ field FK       │
                              │ value          │
                              └────────────────┘

   ┌────────────────┐
   │   AuditLog     │
   │────────────────│
   │ user FK (null)  │
   │ action          │
   │ model_name      │
   │ object_id       │
   │ details (JSON)  │
   │ ip_address      │
   │ timestamp       │
   └────────────────┘
```

UK = unique constraint / unique together

## Models Detail

### User

| Field       | Type           | Constraints            | Notes                           |
|-------------|----------------|------------------------|---------------------------------|
| id          | BigAutoField   | PK                     |                                 |
| email       | EmailField     | unique                 | USERNAME_FIELD                  |
| password    | CharField      |                        | Hashed via `set_password()`     |
| first_name  | CharField(150) | blank                  |                                 |
| last_name   | CharField(150) | blank                  |                                 |
| role        | CharField(20)  | choices                | admin, data_analyst, data_viewer, customer |
| is_active   | BooleanField   | default=True           |                                 |
| is_staff    | BooleanField   | default=False          | Django admin access             |
| date_joined | DateTimeField  | auto_now_add           |                                 |

**Table:** `users`

### Survey

| Field       | Type           | Constraints            | Notes                           |
|-------------|----------------|------------------------|---------------------------------|
| id          | BigAutoField   | PK                     |                                 |
| title       | CharField(255) |                        |                                 |
| description | TextField      | blank, default=""      |                                 |
| created_by  | ForeignKey     | -> User, CASCADE       |                                 |
| status      | CharField(20)  | choices, default=draft | draft, published, archived      |
| created_at  | DateTimeField  | auto_now_add           |                                 |
| updated_at  | DateTimeField  | auto_now               |                                 |

**Table:** `surveys`
**Indexes:** `status`, `created_by`
**Ordering:** `-created_at`
**State machine:** draft -> published -> archived (forward-only)

### Section

| Field       | Type              | Constraints              | Notes                    |
|-------------|-------------------|--------------------------|--------------------------|
| id          | BigAutoField      | PK                       |                          |
| survey      | ForeignKey        | -> Survey, CASCADE       |                          |
| title       | CharField(255)    |                          |                          |
| description | TextField         | blank, default=""        |                          |
| order       | PositiveIntegerField |                       |                          |

**Table:** `survey_sections`
**Unique together:** `(survey, order)`
**Ordering:** `order`

### Field

| Field            | Type              | Constraints              | Notes                    |
|------------------|-------------------|--------------------------|--------------------------|
| id               | BigAutoField      | PK                       |                          |
| section          | ForeignKey        | -> Section, CASCADE      |                          |
| label            | CharField(255)    |                          |                          |
| field_type       | CharField(20)     | choices                  | text, number, date, dropdown, checkbox, radio, textarea, email |
| required         | BooleanField      | default=False            |                          |
| order            | PositiveIntegerField |                        |                          |
| options          | JSONField         | default=list             | For dropdown/radio/checkbox |
| is_encrypted     | BooleanField      | default=False            | Fernet encryption at rest |
| validation_rules | JSONField         | default=dict             | min, max, min_length, max_length, regex |

**Table:** `survey_fields`
**Unique together:** `(section, order)`
**Ordering:** `order`

### ConditionalRule

| Field            | Type           | Constraints              | Notes                    |
|------------------|----------------|--------------------------|--------------------------|
| id               | BigAutoField   | PK                       |                          |
| survey           | ForeignKey     | -> Survey, CASCADE       | Denormalized for queries |
| target_section   | ForeignKey     | -> Section, CASCADE, null | Exactly one of section/field |
| target_field     | ForeignKey     | -> Field, CASCADE, null  |                          |
| depends_on_field | ForeignKey     | -> Field, CASCADE        |                          |
| operator         | CharField(20)  | choices                  | equals, not_equals, contains, greater_than, less_than, in |
| value            | JSONField      |                          | Expected answer value    |

**Table:** `conditional_rules`

### FieldDependency

| Field            | Type           | Constraints              | Notes                    |
|------------------|----------------|--------------------------|--------------------------|
| id               | BigAutoField   | PK                       |                          |
| survey           | ForeignKey     | -> Survey, CASCADE       | Denormalized for queries |
| dependent_field  | ForeignKey     | -> Field, CASCADE        | Field being modified     |
| depends_on_field | ForeignKey     | -> Field, CASCADE        | Field being watched      |
| operator         | CharField(20)  | choices                  | Same as ConditionalRule  |
| value            | JSONField      |                          | Expected answer value    |
| action           | CharField(20)  | choices                  | show_options, hide_options, set_value |
| action_value     | JSONField      |                          | Options list or value    |

**Table:** `field_dependencies`

### SurveyResponse

| Field        | Type           | Constraints              | Notes                    |
|--------------|----------------|--------------------------|--------------------------|
| id           | BigAutoField   | PK                       |                          |
| survey       | ForeignKey     | -> Survey, CASCADE       |                          |
| user         | ForeignKey     | -> User, CASCADE         |                          |
| submitted_at | DateTimeField  | auto_now_add             |                          |

**Table:** `survey_responses`
**Unique together:** `(survey, user)` -- one submission per user per survey
**Indexes:** `submitted_at`
**Ordering:** `-submitted_at`

### FieldResponse

| Field           | Type           | Constraints              | Notes                    |
|-----------------|----------------|--------------------------|--------------------------|
| id              | BigAutoField   | PK                       |                          |
| survey_response | ForeignKey     | -> SurveyResponse, CASCADE |                        |
| field           | ForeignKey     | -> Field, CASCADE        |                          |
| value           | TextField      | blank, default=""        | Possibly Fernet-encrypted |

**Table:** `field_responses`
**Indexes:** `(survey_response, field)`

### AuditLog

| Field      | Type                    | Constraints              | Notes                    |
|------------|-------------------------|--------------------------|--------------------------|
| id         | BigAutoField            | PK                       |                          |
| user       | ForeignKey              | -> User, SET_NULL, null  | Preserved on user delete |
| action     | CharField(10)           | choices                  | create, update, delete, view |
| model_name | CharField(100)          |                          | e.g., "Survey"           |
| object_id  | CharField(100)          | blank, default=""        |                          |
| details    | JSONField               | default=dict             | Action-specific metadata |
| ip_address | GenericIPAddressField   | null                     |                          |
| timestamp  | DateTimeField           | auto_now_add             |                          |

**Table:** `audit_logs`
**Indexes:** `timestamp`, `user`, `(model_name, object_id)`
**Ordering:** `-timestamp`
