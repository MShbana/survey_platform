"""URL configuration for the surveys app.

All endpoints are mounted under ``/api/v1/surveys/`` by the root URL config.

Nested resource routes follow the multi-step survey builder pattern:
    Survey → Section → Field, with conditional rules and dependencies
    scoped to a survey.

Routes:
    Surveys (via DRF router):
        GET    /                            -- list surveys
        POST   /                            -- create survey
        GET    /{id}/                       -- retrieve survey (cached)
        PUT    /{id}/                       -- update survey
        PATCH  /{id}/                       -- partial update
        DELETE /{id}/                       -- delete survey

    Sections:
        GET/POST   /{survey_pk}/sections/             -- list / create
        GET/PUT/PATCH/DELETE  /{survey_pk}/sections/{pk}/  -- detail

    Fields:
        GET/POST   /{survey_pk}/sections/{section_pk}/fields/
        GET/PUT/PATCH/DELETE  .../{pk}/

    Conditional Rules:
        GET/POST   /{survey_pk}/conditional-rules/
        GET/PUT/PATCH/DELETE  .../{pk}/

    Field Dependencies:
        GET/POST   /{survey_pk}/field-dependencies/
        GET/PUT/PATCH/DELETE  .../{pk}/
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = "surveys"

router = DefaultRouter()
router.register(r"", views.SurveyViewSet, basename="survey")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "<int:survey_pk>/sections/",
        views.SectionViewSet.as_view({"get": "list", "post": "create"}),
        name="section-list",
    ),
    path(
        "<int:survey_pk>/sections/<int:pk>/",
        views.SectionViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="section-detail",
    ),
    path(
        "<int:survey_pk>/sections/<int:section_pk>/fields/",
        views.FieldViewSet.as_view({"get": "list", "post": "create"}),
        name="field-list",
    ),
    path(
        "<int:survey_pk>/sections/<int:section_pk>/fields/<int:pk>/",
        views.FieldViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="field-detail",
    ),
    path(
        "<int:survey_pk>/conditional-rules/",
        views.ConditionalRuleViewSet.as_view({"get": "list", "post": "create"}),
        name="conditional-rule-list",
    ),
    path(
        "<int:survey_pk>/conditional-rules/<int:pk>/",
        views.ConditionalRuleViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="conditional-rule-detail",
    ),
    path(
        "<int:survey_pk>/field-dependencies/",
        views.FieldDependencyViewSet.as_view({"get": "list", "post": "create"}),
        name="field-dependency-list",
    ),
    path(
        "<int:survey_pk>/field-dependencies/<int:pk>/",
        views.FieldDependencyViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="field-dependency-detail",
    ),
]
