"""The client address: the one function every throttle and login limit reads it through.

settings.TRUSTED_PROXIES lists the proxies in front of the app as addresses or
networks (DJANGO_TRUSTED_PROXIES; gunicorn.conf.py gives gunicorn the same list
as forwarded_allow_ips).
- REMOTE_ADDR is not a trusted proxy: the client connected directly. It is the
  client, and X-Forwarded-For is ignored, because any client can send it.
- REMOTE_ADDR is a trusted proxy: walk X-Forwarded-For from the right (each
  proxy appends the address it saw), skip trusted hops and return the first
  hop that is not trusted. Hops further left were written by the client.
- A hop that is not an IP address (garbage, an address with a port) ends the
  walk, and the last trusted address seen is the answer, so a malformed header
  cannot choose the address. An empty header leaves REMOTE_ADDR, the proxy.
A hop count (DRF's NUM_PROXIES) would trust the header from any client that
reaches the app port directly, which is why there is none.

IPv4-mapped IPv6 addresses (::ffff:192.0.2.1) count as their IPv4 address,
both against the list and in the result.
"""

import ipaddress

from django.conf import settings
from django.http import HttpRequest
from rest_framework.request import Request

IPV6_BUCKET_PREFIX = 64
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _address(text: str) -> IPAddress | None:
    try:
        ip = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _trusted(ip: IPAddress) -> bool:
    # An address of the other IP version is in no network of the list (`in` is False).
    return any(ip in network for network in settings.TRUSTED_PROXIES)


def client_ip(request: HttpRequest | Request) -> str:
    """The address of the client as the nearest proxy we trust saw it."""
    remote_addr: str = request.META.get("REMOTE_ADDR", "")
    current = _address(remote_addr)
    if current is None:
        return remote_addr
    if not _trusted(current):
        return str(current)
    hops: str = request.META.get("HTTP_X_FORWARDED_FOR", "")
    for hop in reversed(hops.split(",")):
        ip = _address(hop)
        if ip is None:
            break
        current = ip
        if not _trusted(ip):
            break
    return str(current)


def ip_bucket(address: str) -> str:
    """IPv4 as is, IPv4-mapped IPv6 unwrapped, other IPv6 cut to its /64 network."""
    ip = _address(address)
    if ip is None:
        return address or "unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((ip, IPV6_BUCKET_PREFIX), strict=False))
    return str(ip)


def client_bucket(request: HttpRequest | Request) -> str:
    """The client's bucket: what throttles and login limits count per address."""
    return ip_bucket(client_ip(request))
