from django.urls import path

from history import views

app_name = "history"

urlpatterns = [
    path("api/history/", views.history_data, name="data"),
    path("history/export.csv", views.history_csv, name="csv"),
    path("history/export.xlsx", views.history_excel, name="excel"),
]
