from django.urls import path

from board import views

app_name = "board"

urlpatterns = [
    path("api/board/", views.board_data, name="data"),
]
