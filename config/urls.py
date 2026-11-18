"""
The site's address map. Each app keeps its own urls.py; this file only includes them.
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path("admin/", admin.site.urls),
    # Sign in and out with Django's own views; only the templates are ours.
    path("accounts/login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),     # POST only
    # The translated texts used by the JavaScript (gettext() in the browser).
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("history.urls")),
    path("", include("board.urls")),
]

handler404 = "config.views.not_found"
