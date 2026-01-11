"""Browser app URLs."""

from django.urls import path

from app.web.browser import views


urlpatterns = [
    path("", views.search, name="search"),
    path("systems/<int:system_id>/", views.titles, name="titles"),
    path("titles/<int:title_id>/", views.title_detail, name="title_detail"),
]
