from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "cultures.core"
    label = "core"

    def ready(self) -> None:
        from . import checks, schema  # noqa: F401, PLC0415 (registers checks and the schema extension)
        from .error_reporting import init_error_reporting  # noqa: PLC0415

        init_error_reporting()
