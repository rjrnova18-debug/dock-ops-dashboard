from django.apps import AppConfig


class BoardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "board"

    def ready(self):
        # Build the configuration once at start-up, so a wrong DOCKOPS or holiday
        # country stops the server now instead of failing on the first request.
        from board.conf import get_ops_config
        get_ops_config()
