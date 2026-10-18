"""The client address: X-Forwarded-For only from trusted proxies, read from the right.

Also the invariant behind it: nothing but cultures/core/client_ip.py reads
REMOTE_ADDR or a forwarding header, so every throttle and login limit sees the
same client.
"""

import ast
import ipaddress
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from pytest_django.fixtures import Settings

from config.env import env_networks
from cultures.core.client_ip import client_bucket, client_ip, ip_bucket

BACKEND = Path(settings.BASE_DIR)
THE_FUNCTION = BACKEND / "cultures" / "core" / "client_ip.py"
PROXY, PROXY_2 = "10.0.0.5", "10.0.0.6"
CLIENT = "203.0.113.9"


def trust(settings: Settings, *entries: str) -> None:
    settings.TRUSTED_PROXIES = tuple(ipaddress.ip_network(entry) for entry in entries)


@pytest.mark.parametrize(
    ("remote_addr", "forwarded_for", "trusted", "expected"),
    [
        # A client that reaches the app port directly chooses its header, never its address.
        pytest.param(CLIENT, "198.51.100.1", (), CLIENT, id="forged header, no proxies"),
        pytest.param(CLIENT, "198.51.100.1", (PROXY,), CLIENT, id="forged header, not a proxy"),
        pytest.param(PROXY, f"198.51.100.1, {CLIENT}", (PROXY,), CLIENT, id="one trusted proxy"),
        pytest.param(
            PROXY,
            f"198.51.100.1, {CLIENT}, {PROXY_2}",
            (PROXY, PROXY_2),
            CLIENT,
            id="two trusted hops",
        ),
        pytest.param("10.1.2.3", f"{CLIENT}, 10.9.9.9", ("10.0.0.0/8",), CLIENT, id="a CIDR"),
        pytest.param(
            "2001:db8::5", "2001:db8:aaaa::1", ("2001:db8::5",), "2001:db8:aaaa::1", id="IPv6"
        ),
        pytest.param(
            "2001:db8::1", "198.51.100.1", ("10.0.0.0/8",), "2001:db8::1", id="IPv6 not trusted"
        ),
        pytest.param(f"::ffff:{PROXY}", CLIENT, (PROXY,), CLIENT, id="IPv4-mapped proxy"),
        pytest.param(PROXY, f"::ffff:{CLIENT}", (PROXY,), CLIENT, id="IPv4-mapped client"),
        pytest.param(
            PROXY,
            f"{CLIENT}, ::ffff:{PROXY_2}",
            (PROXY, PROXY_2),
            CLIENT,
            id="IPv4-mapped trusted hop",
        ),
        pytest.param(f"::ffff:{CLIENT}", "", (), CLIENT, id="IPv4-mapped direct client"),
        # Garbage left of the client is the client's own text and is never read.
        pytest.param(PROXY, f"garbage, {CLIENT}", (PROXY,), CLIENT, id="garbage on the left"),
        # A malformed hop ends the walk: the last trusted address seen, never a choice.
        pytest.param(PROXY, f"{CLIENT}, garbage", (PROXY,), PROXY, id="garbage on the right"),
        pytest.param(
            PROXY,
            f"198.51.100.1, garbage, {PROXY_2}",
            (PROXY, PROXY_2),
            PROXY_2,
            id="garbage between hops",
        ),
        pytest.param(PROXY, f"{CLIENT}:4711", (PROXY,), PROXY, id="a hop with a port"),
        pytest.param(PROXY, "", (PROXY,), PROXY, id="empty header"),
        pytest.param(PROXY, " , ", (PROXY,), PROXY, id="blank hops"),
        pytest.param(PROXY, PROXY_2, (PROXY, PROXY_2), PROXY_2, id="every hop trusted"),
    ],
)
def test_the_client_is_the_first_untrusted_hop_from_the_right(
    settings: Settings,
    remote_addr: str,
    forwarded_for: str,
    trusted: tuple[str, ...],
    expected: str,
) -> None:
    trust(settings, *trusted)
    request = RequestFactory().get("/", REMOTE_ADDR=remote_addr, HTTP_X_FORWARDED_FOR=forwarded_for)
    assert client_ip(request) == expected


def test_a_trusted_proxy_without_the_header_is_the_client(
    rf: RequestFactory, settings: Settings
) -> None:
    trust(settings, PROXY)
    assert client_ip(rf.get("/", REMOTE_ADDR=PROXY)) == PROXY


@pytest.mark.parametrize("remote_addr", ["", "unix-socket"])
def test_a_remote_addr_that_is_no_address_is_kept_and_never_trusted(
    rf: RequestFactory, settings: Settings, remote_addr: str
) -> None:
    trust(settings, PROXY)
    request = rf.get("/", REMOTE_ADDR=remote_addr, HTTP_X_FORWARDED_FOR=CLIENT)
    assert client_ip(request) == remote_addr
    assert client_bucket(request) == (remote_addr or "unknown")


@pytest.mark.parametrize(
    ("address", "bucket"),
    [
        ("198.51.100.7", "198.51.100.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("not-an-ip", "not-an-ip"),
        ("", "unknown"),
    ],
)
def test_ipv6_clients_share_a_bucket_per_64(address: str, bucket: str) -> None:
    assert ip_bucket(address) == bucket


class TestTrustedProxiesSetting:
    def test_addresses_and_networks_are_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("X_PROXIES", " 10.0.0.5 , 10.1.0.0/16,, 2001:db8::/64 ")
        assert [str(n) for n in env_networks("X_PROXIES")] == [
            "10.0.0.5/32",
            "10.1.0.0/16",
            "2001:db8::/64",
        ]

    def test_unset_means_no_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("X_PROXIES", raising=False)
        assert env_networks("X_PROXIES") == ()

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("proxy.internal", "not an IP address or network"),
            ("10.0.0.5/24", "not an IP address or network"),  # host bits: gunicorn refuses it too
            ("*", "not an IP address or network"),
            ("0.0.0.0/0", "would trust every client"),
            ("::/0", "would trust every client"),
        ],
    )
    def test_anything_else_stops_startup(
        self, monkeypatch: pytest.MonkeyPatch, value: str, message: str
    ) -> None:
        monkeypatch.setenv("X_PROXIES", value)
        with pytest.raises(ImproperlyConfigured, match=message):
            env_networks("X_PROXIES")


# The invariant: one function reads the client address.
# X-Forwarded-Proto (the scheme, SECURE_PROXY_SSL_HEADER) is not an address and passes.
ADDRESS_SOURCES = (
    "REMOTE_ADDR",
    "FORWARDED_FOR",
    "FORWARDED-FOR",
    "HTTP_FORWARDED",
    "REAL_IP",
    "REAL-IP",
)


def _names_an_address(text: str) -> bool:
    upper = text.upper()
    return upper == "FORWARDED" or any(source in upper for source in ADDRESS_SOURCES)


def _docstrings(tree: ast.AST) -> set[int]:
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


def client_address_reads(path: Path) -> list[str]:
    """String literals in code (not docstrings) that name REMOTE_ADDR or a forwarding header."""
    tree = ast.parse(path.read_text())
    docstrings = _docstrings(tree)
    return [
        f"{path.name}:{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _names_an_address(node.value)
    ]


def test_only_the_client_ip_module_reads_the_client_address() -> None:
    sources = [
        path
        for path in [*BACKEND.glob("config/**/*.py"), *BACKEND.glob("cultures/**/*.py")]
        if not {"tests", "testing", "migrations"} & set(path.parts)
    ]
    assert len(sources) > 20 and THE_FUNCTION in sources  # the walk found the code
    assert client_address_reads(THE_FUNCTION) != []  # the walk sees a real read
    reads = [
        read for path in sources if path != THE_FUNCTION for read in client_address_reads(path)
    ]
    assert reads == [], "read the client address through cultures.core.client_ip"


def test_the_walk_finds_a_header_read_and_ignores_docstrings(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""Mentions X-Forwarded-For in a docstring only."""\n'
        "def ip(request):\n"
        '    """Reads REMOTE_ADDR."""\n'
        '    return request.headers.get("X-Forwarded-For") or request.META["REMOTE_ADDR"]\n'
        'real = request.META.get("HTTP_X_REAL_IP") or request.headers["Forwarded"]\n'
        'scheme = ("HTTP_X_FORWARDED_PROTO", "https")\n'
    )
    assert sorted(client_address_reads(probe)) == [
        "probe.py:4: 'REMOTE_ADDR'",
        "probe.py:4: 'X-Forwarded-For'",
        "probe.py:5: 'Forwarded'",
        "probe.py:5: 'HTTP_X_REAL_IP'",
    ]
