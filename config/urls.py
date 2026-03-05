"""Root URL configuration for the Survey Platform.

All API endpoints are grouped under the ``/api/v1/`` prefix.  The
surveys and responses apps share the ``/api/v1/surveys/`` prefix,
with responses providing nested submission and export routes.

URL structure::

    /admin/                          -- Django admin site
    /api/v1/auth/                    -- Authentication (register, login, me, users)
    /api/v1/surveys/                 -- Survey CRUD + nested sections, fields, rules
    /api/v1/surveys/{id}/submit/     -- Survey submission (responses app)
    /api/v1/surveys/{id}/responses/  -- Response list/detail/export (responses app)
    /api/v1/audit/                   -- Audit log browsing (admin only)
    /api/v1/schema/                  -- OpenAPI 3 schema (JSON/YAML)
    /api/v1/docs/                    -- Swagger UI
    /api/v1/redoc/                   -- ReDoc documentation

Static files are served by Django only when ``DEBUG=True``.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/surveys/", include("apps.surveys.urls")),
    path("api/v1/surveys/", include("apps.responses.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    # Schema & docs
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)