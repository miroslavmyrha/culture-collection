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
    """JSONParser that enforces DATA_UPLOAD_MAX_MEMORY_SIZE on its own.

    A second line: DRF >= 3.17.2 hands JSON parsers a stream over request.body,
    where Django already refuses a body over the limit (rest_framework/request.py,
    DRF 3.18.3). Older DRF read the raw stream and skipped Django's check. This
    reads at most the limit plus one byte, so a declared or a chunked oversized
    body is refused with 413 before it is decoded, whatever DRF does upstream.
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
