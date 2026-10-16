import pytest
from django.test import Client, RequestFactory
from rest_framework.permissions import AllowAny
from rest_framework.settings import api_settings

from config.settings import base
from cultures.core.testing.contract import routed_api_views
from cultures.core.throttling import ClientIdentMixin, client_ip, ip_bucket
from cultures.users.api.views import LoginThrottle

pytestmark = pytest.mark.django_db
LOGIN = "/api/v1/auth/login/"


def test_rotating_x_forwarded_for_does_not_escape_the_login_throttle(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LoginThrottle, "rate", "3/min", raising=False)
    statuses = [
        client.post(
            LOGIN,
            {"username": f"user{n}", "password": "wrong"},  # new name: the account limit is not hit
            content_type="application/json",
            HTTP_X_FORWARDED_FOR=f"203.0.113.{n}",
        ).status_code
        for n in range(4)
    ]
    assert statuses == [400, 400, 400, 429]


def test_without_proxies_the_header_is_ignored(rf: RequestFactory) -> None:
    request = rf.get("/", HTTP_X_FORWARDED_FOR="198.51.100.7", REMOTE_ADDR="10.0.0.2")
    assert api_settings.NUM_PROXIES == 0
    assert client_ip(request) == "10.0.0.2"


def test_with_one_proxy_the_hop_it_saw_is_the_client(
    rf: RequestFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_settings, "NUM_PROXIES", 1)
    # The client forged the first value; the proxy appended the real address.
    request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.7", REMOTE_ADDR="10.0.0.2")
    assert client_ip(request) == "198.51.100.7"


@pytest.mark.parametrize(
    ("address", "bucket"),
    [
        ("198.51.100.7", "198.51.100.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("not-an-ip", "not-an-ip"),
    ],
)
def test_ipv6_clients_share_a_bucket_per_64(address: str, bucket: str) -> None:
    assert ip_bucket(address) == bucket


def test_neighbouring_ipv6_addresses_share_the_login_limit(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LoginThrottle, "rate", "2/min", raising=False)
    statuses = [
        client.post(
            LOGIN,
            {"username": f"user{n}", "password": "wrong"},
            content_type="application/json",
            REMOTE_ADDR=f"2001:db8:1:2::{n + 1}",
        ).status_code
        for n in range(3)
    ]
    assert statuses == [400, 400, 429]


def login_status(client: Client, username: str, address: str) -> int:
    return client.post(
        LOGIN,
        {"username": username, "password": "wrong"},
        content_type="application/json",
        REMOTE_ADDR=address,
    ).status_code


def test_another_client_keeps_its_own_login_budget(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One attacker must not lock everyone out: the bucket is per address (IPv6 per /64).
    monkeypatch.setattr(LoginThrottle, "rate", "1/min", raising=False)
    assert login_status(client, "a", "198.51.100.7") == 400
    assert login_status(client, "b", "198.51.100.7") == 429
    assert login_status(client, "c", "198.51.100.8") == 400
    assert login_status(client, "d", "2001:db8:1:3::1") == 400


UNSAFE_METHODS = {"post", "put", "patch", "delete"}
SHARED_SCOPES = {"anon", "user", None}


def test_every_anonymous_write_has_its_own_throttle_scope() -> None:
    """An AllowAny view with an unsafe method (login, signup, a public form) gets a
    throttle keyed on the client address with its own scope and rate, not only the
    shared anon budget that every other anonymous request uses up too."""
    anonymous_writes = {
        name: cls
        for name, cls in routed_api_views().items()
        if AllowAny in cls.permission_classes and UNSAFE_METHODS & set(dir(cls))
    }
    assert anonymous_writes  # login is one: an empty walk must not pass
    rates = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    without_own_scope = sorted(
        name
        for name, cls in anonymous_writes.items()
        if not any(
            issubclass(throttle, ClientIdentMixin)
            and getattr(throttle, "scope", None) not in SHARED_SCOPES
            and rates.get(getattr(throttle, "scope", None))
            for throttle in cls.throttle_classes
        )
    )
    assert without_own_scope == []
