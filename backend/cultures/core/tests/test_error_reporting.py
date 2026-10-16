import builtins
import sys
import types

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from cultures.core.error_reporting import FILTERED, init_error_reporting, scrub_event

DSN = "https://key@errors.example.com/1"


@override_settings(ERROR_REPORTING_DSN="")
def test_without_a_dsn_the_sdk_is_never_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    # Recording imports, not blocking them: an import inside try/except ImportError
    # would pass a test that only sets sys.modules["sentry_sdk"] = None.
    imported: list[str] = []
    real_import = builtins.__import__

    def recording_import(name: str, *args: object, **kwargs: object) -> object:
        imported.append(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", recording_import)
    assert init_error_reporting() is False
    assert "sentry_sdk" not in imported


@override_settings(ERROR_REPORTING_DSN=DSN)
def test_the_sdk_starts_without_personal_data_and_with_the_scrubber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    sdk = types.ModuleType("sentry_sdk")
    sdk.init = lambda **kwargs: calls.append(kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", sdk)
    assert init_error_reporting() is True
    assert len(calls) == 1
    assert calls[0]["dsn"] == DSN
    assert calls[0]["send_default_pii"] is False
    assert calls[0]["before_send"] is scrub_event


@override_settings(ERROR_REPORTING_DSN=DSN)
def test_a_dsn_without_the_sdk_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    with pytest.raises(ImproperlyConfigured, match="sentry-sdk"):
        init_error_reporting()


def test_events_are_scrubbed_of_personal_data() -> None:
    event = {
        "user": {"id": 7, "email": "a@example.com", "username": "alice"},
        "request": {
            "url": "https://app/api/v1/auth/login/",
            "data": {"password": "hunter2"},
            "cookies": {"sessionid": "s"},
            "headers": {"Authorization": "Bearer t", "X-CSRFToken": "c", "Accept": "json"},
        },
        "extra": {"api_key": "k", "nested": [{"token": "t", "count": 3}]},
    }
    clean = scrub_event(event)
    assert clean["user"] == {"id": 7}
    assert "data" not in clean["request"]
    assert "cookies" not in clean["request"]
    assert clean["request"]["headers"] == {
        "Authorization": FILTERED,
        "X-CSRFToken": FILTERED,
        "Accept": "json",
    }
    assert clean["extra"] == {"api_key": FILTERED, "nested": [{"token": FILTERED, "count": 3}]}


@pytest.mark.parametrize("key", ["email", "contact_email", "e-mail", "phone", "address"])
def test_personal_data_outside_the_user_is_filtered(key: str) -> None:
    clean = scrub_event({"extra": {key: "a@example.com", "count": 3}})
    assert clean["extra"] == {key: FILTERED, "count": 3}


def test_the_query_string_is_dropped() -> None:
    clean = scrub_event({"request": {"query_string": "email=a@example.com", "method": "GET"}})
    assert clean["request"] == {"method": "GET"}
