from collections.abc import Mapping
from io import BytesIO
from typing import Any

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser

# No body this API takes nests deeper than a few levels (a request's lines and their terms). A
# deeper one is refused before a serializer walks it; one deep enough to exhaust the decoder's
# recursion would otherwise end as a server error.
MAX_DEPTH = 32
TOO_DEEP = f"JSON nested deeper than {MAX_DEPTH} levels."


class RequestTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Request body too large."
    default_code = "request_too_large"


class LimitedJSONParser(JSONParser):
    """JSONParser that enforces DATA_UPLOAD_MAX_MEMORY_SIZE on its own.

    A second line: DRF >= 3.17.2 hands JSON parsers a stream over request.body,
    where Django already refuses a body over the limit (rest_framework/request.py,
    DRF 3.18.3). Older DRF read the raw stream and skipped Django's check. This
    reads at most the limit plus one byte, so a declared or a chunked oversized
    body is refused with 413 before it is decoded, whatever DRF does upstream.
    A body nested deeper than MAX_DEPTH is refused with 400.
    """

    def parse(
        self,
        stream: Any,
        media_type: str | None = None,
        parser_context: Mapping[str, Any] | None = None,
    ) -> Any:
        stream = _capped(stream, parser_context)
        try:
            data = super().parse(stream, media_type, parser_context)
        except RecursionError as error:
            raise ParseError(TOO_DEEP) from error
        if depth(data) > MAX_DEPTH:
            raise ParseError(TOO_DEEP)
        return data


def _capped(stream: Any, parser_context: Mapping[str, Any] | None) -> Any:
    """The body read up to DATA_UPLOAD_MAX_MEMORY_SIZE, or RequestTooLarge (see the parser)."""
    limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
    if limit is None or stream is None:
        return stream
    request = (parser_context or {}).get("request")
    declared = request.META.get("CONTENT_LENGTH") if request is not None else None
    if declared and declared.isdigit() and int(declared) > limit:
        raise RequestTooLarge
    body = stream.read(limit + 1)
    if len(body) > limit:
        raise RequestTooLarge
    return BytesIO(body)


def depth(data: Any) -> int:
    """How many objects and arrays nest at the deepest point, without recursion."""
    deepest = 0
    stack = [(data, 1)]
    while stack:
        node, level = stack.pop()
        children = (
            node.values() if isinstance(node, dict) else node if isinstance(node, list) else None
        )
        if children is None:
            continue
        deepest = max(deepest, level)
        stack.extend((child, level + 1) for child in children)
    return deepest
