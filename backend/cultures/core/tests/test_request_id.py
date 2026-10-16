import json
import logging
import re
import sys

import pytest
from django.test import Client

from cultures.core.logging import JsonFormatter
from cultures.core.request_id import NO_REQUEST, RequestIdFilter, current_request_id

pytestmark = pytest.mark.django_db
GENERATED = re.compile(r"^[0-9a-f]{32}$")


def test_valid_inbound_request_id_is_kept_and_logged(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.WARNING, logger="django.request"):
        response = client.get("/api/v1/auth/me/", HTTP_X_REQUEST_ID="proxy-1234")
    assert response["X-Request-ID"] == "proxy-1234"
    # django.request logs the 401; the record carries the same id.
    records = [r for r in caplog.records if r.name == "django.request"]
    assert records
    assert {r.request_id for r in records} == {"proxy-1234"}  # type: ignore[attr-defined]


@pytest.mark.parametrize("inbound", ["bad id", "x" * 65, "a\nb", "<script>"])
def test_invalid_inbound_request_id_is_replaced(client: Client, inbound: str) -> None:
    response = client.get("/api/v1/auth/csrf/", HTTP_X_REQUEST_ID=inbound)
    assert response["X-Request-ID"] != inbound
    assert GENERATED.match(response["X-Request-ID"])


def test_each_request_gets_its_own_id_and_none_leaks(client: Client) -> None:
    first = client.get("/api/v1/auth/csrf/")["X-Request-ID"]
    second = client.get("/api/v1/auth/csrf/")["X-Request-ID"]
    assert first != second
    assert current_request_id() == NO_REQUEST  # reset after the request


def test_json_formatter_writes_one_json_object_per_record() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord("app", logging.ERROR, __file__, 1, "failed %s", ("x",), exc_info)
    record.request_id = "abc"
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "failed x"
    assert line["level"] == "ERROR"
    assert line["request_id"] == "abc"
    assert "ValueError: boom" in line["exc_info"]
