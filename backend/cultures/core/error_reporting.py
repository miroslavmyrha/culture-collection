"""Optional error reporting through a Sentry-compatible SDK (Sentry, GlitchTip).

Off unless ERROR_REPORTING_DSN is set; then nothing is imported at all. The SDK
ships with the production dependencies (#180): setting the DSN enables it. Events
never carry personal data: send_default_pii is off and scrub_event replaces
values under sensitive keys before anything is sent.
"""

import re
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

FILTERED = "[Filtered]"
SENSITIVE_KEY = re.compile(
    r"pass(word)?|secret|token|api[-_]?key|auth|cookie|csrf|session|"
    r"e-?mail|phone|address|birth|ssn|iban|card",
    re.IGNORECASE,
)


def scrub(value: Any) -> Any:
    """A copy of value with every entry under a sensitive key replaced."""
    if isinstance(value, dict):
        return {
            key: FILTERED if isinstance(key, str) and SENSITIVE_KEY.search(key) else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """before_send hook: drop the user except its id, scrub request and extra data."""
    event = scrub(event)
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)  # bodies may hold anything; keep method, url, headers (scrubbed)
        request.pop("cookies", None)
        request.pop("query_string", None)
    return event


def _before_send(event: "Event", hint: "Hint") -> "Event":
    # The SDK's types for scrub_event, which works on plain dicts.
    return cast("Event", scrub_event(dict(event), hint))


def init_error_reporting() -> bool:
    """Start the SDK when a DSN is configured. Returns whether it started."""
    dsn = settings.ERROR_REPORTING_DSN
    if not dsn:
        return False
    try:
        import sentry_sdk  # noqa: PLC0415 (optional dependency, imported only when enabled)
    except ImportError:
        raise ImproperlyConfigured(
            "ERROR_REPORTING_DSN is set but sentry-sdk is not installed: uv add sentry-sdk"
        ) from None
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.ERROR_REPORTING_ENVIRONMENT,
        send_default_pii=False,
        before_send=_before_send,
        traces_sample_rate=0.0,
    )
    return True
