"""Throttles keyed on the real client address.

The client address comes from REMOTE_ADDR, or from X-Forwarded-For only as far
as NUM_PROXIES trusted proxies vouch for it (the hop the nearest proxy saw).
IPv6 clients are bucketed by /64, the block a single host usually controls.
Counters live in the default cache, which must be shared between workers.
"""

import ipaddress

from django.http import HttpRequest
from rest_framework import throttling
from rest_framework.request import Request
from rest_framework.settings import api_settings

IPV6_BUCKET_PREFIX = 64


def client_ip(request: HttpRequest | Request) -> str:
    """The client address as seen by the outermost trusted proxy."""
    remote_addr: str = request.META.get("REMOTE_ADDR", "")
    num_proxies: int = api_settings.NUM_PROXIES or 0
    xff: str = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if num_proxies == 0 or not xff:
        return remote_addr
    hops = [hop.strip() for hop in xff.split(",")]
    return hops[-min(num_proxies, len(hops))]


def ip_bucket(address: str) -> str:
    """IPv4 as is, IPv4-mapped IPv6 unwrapped, other IPv6 cut to its /64 network."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address or "unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, IPV6_BUCKET_PREFIX), strict=False))
    return str(ip)


class ClientIdentMixin:
    def get_ident(self, request: Request) -> str:
        return ip_bucket(client_ip(request))


class AnonRateThrottle(ClientIdentMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(ClientIdentMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(ClientIdentMixin, throttling.ScopedRateThrottle):
    pass
