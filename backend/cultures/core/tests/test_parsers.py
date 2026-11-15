"""LimitedJSONParser: the JSON body limit as a second line behind Django's.

Through a view the parser never sees an oversized body: DRF >= 3.17.2 parses
JSON from request.body (rest_framework/request.py, DRF 3.18.3), and Django
refuses a body over DATA_UPLOAD_MAX_MEMORY_SIZE there first. Only a direct call
reaches the parser's own cap, so it is tested here and not through a view.
"""

import io
import json

import pytest
from django.test import Client, override_settings
from rest_framework.exceptions import ParseError

from cultures.core.parsers import MAX_DEPTH, LimitedJSONParser, RequestTooLarge
from cultures.core.testing import assert_problem

LIMIT = 1024


def body_of(size: int) -> bytes:
    body = json.dumps({"name": "x" * (size - len('{"name": ""}'))}).encode()
    assert len(body) == size
    return body


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=LIMIT)
def test_a_stream_over_the_limit_is_refused_without_a_declared_length() -> None:
    with pytest.raises(RequestTooLarge):
        LimitedJSONParser().parse(io.BytesIO(body_of(LIMIT + 1)), "application/json", {})


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=LIMIT)
def test_a_body_at_the_limit_is_parsed() -> None:
    parsed = LimitedJSONParser().parse(io.BytesIO(body_of(LIMIT)), "application/json", {})
    assert parsed == json.loads(body_of(LIMIT))


def nested(depth: int) -> bytes:
    """A JSON body of arrays inside arrays, `depth` levels deep."""
    return b"[" * depth + b"]" * depth


@pytest.mark.django_db
@pytest.mark.parametrize("depth", [MAX_DEPTH + 1, 500, 100_000])
def test_a_body_nested_too_deep_is_a_bad_request_not_a_server_error(depth: int) -> None:
    # The sign-in reads the body before anyone is known, so it is the first door to try.
    client = Client(raise_request_exception=False)
    response = client.post("/api/v1/auth/login/", nested(depth), content_type="application/json")
    body = assert_problem(response, 400, "parse_error")
    assert "nested" in body["detail"]


def test_a_body_at_the_depth_limit_is_parsed() -> None:
    parsed = LimitedJSONParser().parse(io.BytesIO(nested(MAX_DEPTH)), "application/json", {})
    depth = 0
    while isinstance(parsed, list) and parsed:
        parsed, depth = parsed[0], depth + 1
    assert depth == MAX_DEPTH - 1  # the innermost array is empty


def test_objects_count_towards_the_depth_as_arrays_do() -> None:
    body = b'{"a":' * MAX_DEPTH + b"1" + b"}" * MAX_DEPTH
    LimitedJSONParser().parse(io.BytesIO(body), "application/json", {})
    deeper = b'{"a":[' + body + b"]}"
    with pytest.raises(ParseError, match="nested"):
        LimitedJSONParser().parse(io.BytesIO(deeper), "application/json", {})
