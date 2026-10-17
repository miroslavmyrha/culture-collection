"""Request id: one id per request in the logs and the X-Request-ID response header.

An inbound X-Request-ID (from the proxy) is kept only when it is a short token
of letters, digits and hyphens; anything else is replaced, so a client cannot
inject text into the logs. The id lives in a ContextVar. It is cleared on
request_finished, not when the middleware returns, because Django logs 4xx and
5xx responses (django.request) after the middleware chain; a reused worker
thread still never carries an old id into the next request.
"""

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from django.core.signals import request_finished
from django.dispatch import receiver
from django.http import HttpRequest, HttpResponse

HEADER = "X-Request-ID"
_VALID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
NO_REQUEST = "-"  # current_request_id() outside a request: compare against this, not "-"

request_id_var: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST)


def current_request_id() -> str:
    """The id of the request being handled, or NO_REQUEST outside a request."""
    return request_id_var.get()


def is_valid_request_id(value: str) -> bool:
    """1 to 64 letters, digits and hyphens: what the header accepts and audit rows store."""
    return _VALID.fullmatch(value) is not None


def accept_or_generate(inbound: str | None) -> str:
    if inbound and is_valid_request_id(inbound):
        return inbound
    return uuid.uuid4().hex


class RequestIdMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = accept_or_generate(request.headers.get(HEADER))
        request_id_var.set(request_id)
        response = self.get_response(request)
        response[HEADER] = request_id
        return response


@receiver(request_finished, dispatch_uid="cultures.core.request_id.clear")
def _clear_request_id(**kwargs: object) -> None:
    request_id_var.set(NO_REQUEST)


class RequestIdFilter(logging.Filter):
    """Adds record.request_id for formatters (configured on the handlers in LOGGING)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = current_request_id()
        return True
