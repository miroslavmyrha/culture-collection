"""gunicorn's access log as JSON lines (LOG_FORMAT=json), like the app's own (core/logging.py).

gunicorn fills a %-format string with its atoms and would put a quote of a request line into
the JSON unescaped, so the line is built here and dumped by json. No client address: behind
the proxy it is the proxy's, and the app's logs name an address bucket, never an address
(#42, ADR 0007). The request id joins it to the app's lines.
"""

import json
from datetime import UTC, datetime
from typing import Any

from gunicorn.glogging import Logger


def access_entry(atoms: dict[str, Any]) -> dict[str, object]:
    """The fields of one access line, from gunicorn's atoms."""
    return {
        "time": datetime.now(tz=UTC).isoformat(),
        "level": "INFO",
        "logger": "gunicorn.access",
        "request": atoms.get("r"),
        "status": atoms.get("s"),
        "bytes": atoms.get("B"),
        "duration_ms": atoms.get("M"),
        "request_id": atoms.get("{x-request-id}o") or None,
    }


class JsonAccessLogger(Logger):  # type: ignore[misc]  # gunicorn ships no types
    def access(self, resp: Any, req: Any, environ: Any, request_time: Any) -> None:
        if not self.access_log_enabled:
            return
        entry = access_entry(self.atoms(resp, req, environ, request_time))
        self.access_log.info(json.dumps(entry, default=str))
