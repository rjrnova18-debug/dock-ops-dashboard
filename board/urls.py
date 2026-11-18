from django.urls import path

from board import views

app_name = "board"

urlpatterns = [
    path("", views.board_page, name="page"),
    path("api/board/", views.board_data, name="data"),
]
