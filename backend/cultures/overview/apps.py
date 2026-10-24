from django.apps import AppConfig


class OverviewConfig(AppConfig):
    """Home (#69): what waits for the signed-in person, their labs' figures and the latest
    activity. Reads only, no tables of its own."""

    name = "cultures.overview"
    label = "overview"
