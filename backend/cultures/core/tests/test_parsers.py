"""LimitedJSONParser: the JSON body limit as a second line behind Django's.

Through a view the parser never sees an oversized body: DRF >= 3.17.2 parses
JSON from request.body (rest_framework/request.py, DRF 3.18.3), and Django
refuses a body over DATA_UPLOAD_MAX_MEMORY_SIZE there first. Only a direct call
reaches the parser's own cap, so it is tested here and not through a view.
"""

import io
import json

import pytest
from django.test import override_settings

from cultures.core.parsers import LimitedJSONParser, RequestTooLarge

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
