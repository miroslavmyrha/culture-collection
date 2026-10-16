from collections.abc import Mapping
from io import BytesIO
from typing import Any

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.parsers import JSONParser


class RequestTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Request body too large."
    default_code = "request_too_large"


class LimitedJSONParser(JSONParser):
    """JSONParser that enforces DATA_UPLOAD_MAX_MEMORY_SIZE.

    DRF reads JSON from the request stream, which skips Django's body limit
    (Django checks it only in request.body and the form parsers). This reads at
    most the limit plus one byte, so a declared or a chunked oversized body is
    refused with 413 before it is decoded.
    """

    def parse(
        self,
        stream: Any,
        media_type: str | None = None,
        parser_context: Mapping[str, Any] | None = None,
    ) -> Any:
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        if limit is not None and stream is not None:
            request = (parser_context or {}).get("request")
            declared = request.META.get("CONTENT_LENGTH") if request is not None else None
            if declared and declared.isdigit() and int(declared) > limit:
                raise RequestTooLarge
            body = stream.read(limit + 1)
            if len(body) > limit:
                raise RequestTooLarge
            stream = BytesIO(body)
        return super().parse(stream, media_type, parser_context)
