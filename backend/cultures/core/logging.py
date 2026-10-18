"""JSON log lines (LOG_FORMAT=json) with the standard library only.

A structured line passes its fields as extra={"fields": {...}}: they become keys of
the JSON object, after the standard keys, which they never replace. The message
repeats them as key=value for the plain format.
"""

import json
import logging
from datetime import UTC, datetime

from .request_id import current_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or current_request_id(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                entry.setdefault(str(key), value)
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(entry, default=str)
