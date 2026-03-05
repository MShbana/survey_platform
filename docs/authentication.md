# Authentication & Authorization

## JWT Authentication

The platform uses JSON Web Tokens (JWT) via `djangorestframework-simplejwt`. All API requests (except registration and login) require a valid access token in the `Authorization` header.

### Token Lifecycle

```
1. POST /api/v1/auth/login/    -> { access, refresh }
2. Use access token in header:  Authorization: Bearer <access_token>
3. When access expires:
   POST /api/v1/auth/refresh/  -> { access }    (using refresh token)
4. When refresh expires:       -> re-login required
```

### Token Lifetimes

| Token   | Lifetime     |
|---------|-------------|
| Access  | 30 minutes |
| Refresh | 1 day       |

### Header Format

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### JWT Signing Key

By default, tokens are signed with Django's `SECRET_KEY`. For production, set `JWT_SECRET_KEY` in the environment to use a separate signing key.

## Role-Based Access Control (RBAC)

The platform has four roles, assigned at registration via the `role` field on the User model.

### Roles

| Role           | Value           | Description                          |
|----------------|-----------------|--------------------------------------|
| Admin          | `admin`         | Full platform access                 |
| Data Analyst   | `data_analyst`  | Read surveys + view/export responses |
| Data Viewer    | `data_viewer`   | Read surveys + view responses        |
| Customer       | `customer`      | View published surveys + submit      |

### Permission Matrix

| Resource              | Admin | Data Analyst | Data Viewer | Customer |
|-----------------------|-------|--------------|-------------|----------|
| Register              | -     | -            | -           | Public   |
| Login / Refresh       | -     | -            | -           | Public   |
| View own profile      | Yes   | Yes          | Yes         | Yes      |
| Manage users          | Yes   | No           | No          | No       |
| Create/update surveys | Yes   | No           | No          | No       |
| Read surveys          | Yes   | Yes          | Yes         | Published only |
| Create sections/fields| Yes   | No           | No          | No       |
| Manage rules/deps     | Yes   | No           | No          | No       |
| Submit responses      | No    | No           | No          | Yes      |
| View responses        | Yes   | Yes          | Yes         | No       |
| View audit logs       | Yes   | No           | No          | No       |

### Permission Classes

Defined in `apps/accounts/permissions.py`:

| Class              | Logic                                            |
|--------------------|--------------------------------------------------|
| `IsAdmin`          | User is authenticated with `admin` role          |
| `IsAdminOrReadOnly`| Any authenticated user can read; writes need admin |
| `IsCustomer`       | User is authenticated with `customer` role       |
| `CanViewResponses` | Admin, Data Analyst, or Data Viewer              |
| `IsDataAnalyst`    | User is authenticated with `data_analyst` role   |
| `IsDataViewer`     | User is authenticated with `data_viewer` role    |

### User Registration Rules

- **Public registration** creates users with the `customer` role only.
- **Admin-created users** can have any role. The admin must be authenticated and send a valid JWT.
- Attempting to register with a non-customer role without admin authentication returns `400 Bad Request`.

### Custom User Model

The platform uses a custom User model (`apps.accounts.models.User`) with:

- **Email-based authentication** -- no username field. `email` is the `USERNAME_FIELD`.
- `first_name`, `last_name` -- optional.
- `role` -- one of the four RBAC roles (default: `customer`).
- `is_active` -- account active flag.
- `date_joined` -- auto-set on creation.

## Rate Limiting

API throttling is enforced globally via DRF:

| Scope          | Rate           |
|----------------|----------------|
| Anonymous      | 30 req/minute  |
| Authenticated  | 120 req/minute |
