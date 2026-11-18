"""
The site's address map. Each app keeps its own urls.py; this file only includes them.
"""
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path("admin/", admin.site.urls),
    # The translated texts used by the JavaScript (gettext() in the browser).
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("board.urls")),
]
