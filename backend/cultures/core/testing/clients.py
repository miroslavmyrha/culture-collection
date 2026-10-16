from django.test import Client

from cultures.users.models import User


def logged_in(user: User | None) -> Client:
    """A client with the user's real session; None gives an anonymous client."""
    client = Client()
    if user is not None:
        client.force_login(user)
    return client
