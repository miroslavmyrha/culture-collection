import pytest
from django.test import Client, RequestFactory
from rest_framework.settings import api_settings

from cultures.core.throttling import client_ip, ip_bucket
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
