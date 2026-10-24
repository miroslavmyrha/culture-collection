from django.apps import AppConfig


class SearchConfig(AppConfig):
    """The top bar's search (#76): strains, vials, deposits and requests across the person's
    labs. Reads only, no tables of its own."""

    name = "cultures.search"
    label = "search"
