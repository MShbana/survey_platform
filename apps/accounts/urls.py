"""URL configuration for the accounts (authentication) app.

All endpoints are mounted under ``/api/v1/auth/`` by the root URL config.

Routes:
    POST   /register/       -- Create a new user account.
    POST   /login/          -- Obtain a JWT access + refresh token pair.
    POST   /refresh/        -- Refresh an expired access token.
    GET    /me/             -- Retrieve the authenticated user's profile.
    GET    /users/          -- List all users (admin only).
    GET    /users/{id}/     -- Retrieve a single user (admin only).
    PUT    /users/{id}/     -- Fully update a user (admin only).
    PATCH  /users/{id}/     -- Partially update a user (admin only).
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", TokenObtainPairView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("me/", views.MeView.as_view(), name="me"),
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user-detail"),
]
