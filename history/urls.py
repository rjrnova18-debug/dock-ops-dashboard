from django.urls import path

from history import views

app_name = "history"

urlpatterns = [
    path("api/history/", views.history_data, name="data"),
]
