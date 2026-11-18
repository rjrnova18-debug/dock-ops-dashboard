"""
The site's address map. Each app keeps its own urls.py; this file only includes them.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("board.urls")),
]
