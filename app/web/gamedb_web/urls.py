"""URL routing for GameDB."""

from django.urls import include, path


urlpatterns = [
    path("", include("app.web.browser.urls")),
]
