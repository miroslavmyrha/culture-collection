import time

from django.test import Client

from cultures.users.models import User
from cultures.users.signin import VERIFIED_AT


def with_second_factor(client: Client) -> Client:
    """Marks the client's signed-in session as signed in with a second factor (#176), as the
    sign-in steps do: SecondFactorMiddleware signs out a session without the mark."""
    session = client.session
    session[VERIFIED_AT] = time.time()
    session.save()
    return client


def logged_in(user: User | None) -> Client:
    """A client with the user's real session, signed in with a second factor; None gives an
    anonymous client."""
    client = Client()
    if user is not None:
        client.force_login(user)
        with_second_factor(client)
    return client
