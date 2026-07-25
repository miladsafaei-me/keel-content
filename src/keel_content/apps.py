from django.apps import AppConfig


class KeelContentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "keel_content"
    verbose_name = "Keel Content — pipeline"

    def ready(self):
        # Register the host-model resolution system check (fails `manage.py check`
        # loud when a host's KEEL_CONTENT model wiring points at a missing model).
        from . import checks  # noqa: F401
