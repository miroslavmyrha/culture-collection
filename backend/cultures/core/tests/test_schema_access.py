import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from cultures.core.testing import with_second_factor

pytestmark = pytest.mark.django_db
SCHEMA = "/api/v1/schema/"


def test_the_schema_is_refused_to_an_anonymous_client(client: Client) -> None:
    # #41: openapi.yml in the repo is the public copy; the live endpoint needs a session.
    assert client.get(SCHEMA).status_code in {401, 403}


def test_a_signed_in_user_reads_the_schema(client: Client) -> None:
    client.force_login(get_user_model().objects.create_user(username="reader", password="x" * 16))
    with_second_factor(client)
    response = client.get(SCHEMA)
    assert response.status_code == 200
    assert b"openapi" in response.content
