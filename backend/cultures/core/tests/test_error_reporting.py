import sys

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from cultures.core.error_reporting import FILTERED, init_error_reporting, scrub_event


@override_settings(ERROR_REPORTING_DSN="")
def test_without_a_dsn_nothing_is_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # any import attempt would fail
    assert init_error_reporting() is False


@override_settings(ERROR_REPORTING_DSN="https://key@errors.example.com/1")
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
