"""Throttles keyed on the real client address (cultures.core.client_ip).

IPv6 clients are bucketed by /64, the block a single host usually controls.
Counters live in the default cache, which must be shared between workers.
Every throttle the project uses extends ClientIdentMixin: DRF's own get_ident
reads X-Forwarded-For by hop count, from any client (core/tests/test_throttling.py).
"""

from rest_framework import throttling
from rest_framework.request import Request

from .client_ip import client_bucket


class ClientIdentMixin:
    def get_ident(self, request: Request) -> str:
        return client_bucket(request)


class AnonRateThrottle(ClientIdentMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(ClientIdentMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(ClientIdentMixin, throttling.ScopedRateThrottle):
    pass
