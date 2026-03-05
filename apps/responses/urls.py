"""URL configuration for the responses app.

All endpoints are mounted under ``/api/v1/surveys/`` by the root URL
config (sharing the prefix with the surveys app).

Routes:
    POST   /{survey_pk}/submit/              -- Submit a survey response.
    GET    /{survey_pk}/responses/            -- List responses for a survey.
    GET    /{survey_pk}/responses/{pk}/       -- Retrieve a single response.
"""

from django.urls import path

from . import views

app_name = "responses"

urlpatterns = [
    path(
        "<int:survey_pk>/submit/",
        views.SurveySubmitView.as_view(),
        name="submit",
    ),
    path(
        "<int:survey_pk>/responses/",
        views.SurveyResponseListView.as_view(),
        name="response-list",
    ),
    path(
        "<int:survey_pk>/responses/<int:pk>/",
        views.SurveyResponseDetailView.as_view(),
        name="response-detail",
    ),
]
