# Deployment

## Docker Compose (Recommended)

The project includes a `docker-compose.yml` that runs the full stack: PostgreSQL, Redis, Django (Gunicorn), and Celery worker.

### Setup

1. **Create environment file:**

   ```bash
   cp .env.example .env
   ```

2. **Configure `.env`:**

   ```bash
   # Required — generate unique values for production
   SECRET_KEY=<random-secret-key>
   ENCRYPTION_KEY=<generate with command below>
   REDIS_PASSWORD=<strong-password>
   DEFAULT_ADMIN_EMAIL=admin@yourdomain.com
   DEFAULT_ADMIN_PASSWORD=<strong-password>

   # Must be consistent across all Redis URLs
   REDIS_URL=redis://:<redis-password>@redis:6379/0
   CELERY_BROKER_URL=redis://:<redis-password>@redis:6379/1
   CELERY_RESULT_BACKEND=redis://:<redis-password>@redis:6379/2
   ```

   Generate an encryption key:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Start services:**

   ```bash
   docker compose up --build
   ```

4. **Verify:**

   - API: http://localhost:8000/api/v1/docs/
   - Login with `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`

### Services

| Service        | Container          | Port | Image             |
|----------------|--------------------|------|-------------------|
| PostgreSQL     | survey_db          | -    | postgres:17-alpine|
| Redis          | survey_redis       | -    | redis:8-alpine    |
| Web (Gunicorn) | survey_web         | 8000 | Custom (Dockerfile)|
| Celery Worker  | survey_celery_worker | -  | Custom (Dockerfile)|

### Volumes

| Volume          | Purpose                      |
|-----------------|------------------------------|
| postgres_data   | PostgreSQL persistent storage|
| redis_data      | Redis persistent storage     |
| static_volume   | Django collected static files|
| logs_volume     | Application log files        |

### Health Checks

- **PostgreSQL:** `psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'SELECT 1'` every 10s
- **Redis:** `redis-cli -a $REDIS_PASSWORD ping` every 5s
- **Web and Celery** wait for both to be healthy before starting.

### Dockerfile

- Base image: `python:3.14-slim`
- Installs `gcc` and `libpq-dev` for psycopg2
- `DEV=true` build arg installs dev dependencies (used by docker-compose)
- Runs `collectstatic` at build time
- Creates a non-root `appuser` for security
- Default command: Gunicorn with 4 workers

## Production Considerations

### Security Settings

The `prod.py` settings module enables:

| Setting                      | Value                  |
|------------------------------|------------------------|
| `DEBUG`                      | `False`                |
| `SECURE_SSL_REDIRECT`        | `True` (env override)  |
| `SECURE_HSTS_SECONDS`        | 31536000 (1 year)      |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True`            |
| `SECURE_HSTS_PRELOAD`        | `True`                 |
| `SESSION_COOKIE_SECURE`      | `True`                 |
| `CSRF_COOKIE_SECURE`         | `True`                 |
| `SECURE_PROXY_SSL_HEADER`    | `X-Forwarded-Proto: https` |

### Logging

Production uses two handlers:

- **Console:** WARNING level, verbose format
- **Rotating file:** INFO level, `logs/survey_platform.log`, 10MB max, 5 backups

### Database

- PostgreSQL with `CONN_MAX_AGE=60` for connection pooling
- All credentials from environment variables (no defaults)

### CORS

Production defaults to `CORS_ALLOW_ALL_ORIGINS=False`. Set `CORS_ALLOWED_ORIGINS` to your frontend domain(s).

### Environment Variables

| Variable               | Required | Description                                |
|------------------------|----------|--------------------------------------------|
| `SECRET_KEY`           | Yes      | Django secret key                          |
| `ENCRYPTION_KEY`       | Yes      | Fernet key for field encryption            |
| `POSTGRES_DB`          | Yes      | Database name                              |
| `POSTGRES_USER`        | Yes      | Database user                              |
| `POSTGRES_PASSWORD`    | Yes      | Database password                          |
| `POSTGRES_HOST`        | Yes      | Database host                              |
| `POSTGRES_PORT`        | No       | Database port (default: 5432)              |
| `REDIS_URL`            | Yes      | Redis URL for cache                        |
| `REDIS_PASSWORD`       | Yes      | Redis auth password                        |
| `CELERY_BROKER_URL`    | Yes      | Celery broker URL                          |
| `CELERY_RESULT_BACKEND`| Yes      | Celery result backend URL                  |
| `JWT_SECRET_KEY`       | No       | JWT signing key (falls back to SECRET_KEY) |
| `ALLOWED_HOSTS`        | No       | Comma-separated allowed hosts              |
| `CORS_ALLOWED_ORIGINS` | No       | Comma-separated allowed origins            |
| `DEFAULT_ADMIN_EMAIL`  | No       | Auto-created admin email (Docker startup)  |
| `DEFAULT_ADMIN_PASSWORD`| No      | Auto-created admin password                |

## Local Development (Without Docker)

### Prerequisites

- Python 3.14+
- PostgreSQL 17+
- Redis 8+

### Setup

```bash
# Virtual environment
python -m venv venv
source venv/bin/activate

# Dependencies
pip install -r requirements-dev.txt

# Environment
cp .env.example .env
# Edit .env: set POSTGRES_HOST=localhost, REDIS_URL=redis://localhost:6379/1

# Database
createdb survey_platform
python manage.py migrate

# Superuser
python manage.py createsuperuser

# Run
python manage.py runserver              # Terminal 1
celery -A config.celery worker --loglevel=info  # Terminal 2
```

### Settings Module Selection

| Entry Point       | Default Settings Module |
|-------------------|------------------------|
| `manage.py`       | `config.settings.dev`  |
| `wsgi.py`         | `config.settings.prod` |
| `asgi.py`         | `config.settings.prod` |
| `celery.py`       | `config.settings.prod` |
| Dockerfile        | `config.settings.dev`  |
| pytest (`setup.cfg`) | `config.settings.test` |
