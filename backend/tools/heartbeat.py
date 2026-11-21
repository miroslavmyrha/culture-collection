"""The stack answers: each URL gives 2xx within a few seconds (#180).

    python tools/heartbeat.py http://backend:8000/readyz https://proxy:8443/

The scheduler runs it every five minutes through run_job.py, so the heartbeat check in
Healthchecks alerts when the API is not ready, the proxy does not serve the app, or the
scheduler or the whole host is down (no ping arrives). The proxy's certificate is for the
public name, not for "proxy" on the internal network: --insecure-internal-tls skips its
check, for these internal URLs only. Standard library only.
"""

from __future__ import annotations

import argparse
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from http import HTTPStatus

TIMEOUT = 5.0


def probe(url: str, context: ssl.SSLContext | None) -> str | None:
    """None when the URL answers 2xx, else what went wrong."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=context) as response:  # noqa: S310
            if HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
                return None
            return f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return str(getattr(error, "reason", error))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument(
        "--insecure-internal-tls",
        action="store_true",
        help="do not check certificates (internal URLs whose name the certificate does not carry)",
    )
    args = parser.parse_args(argv)
    context = None
    if args.insecure_internal_tls:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    failed = 0
    for url in args.urls:
        problem = probe(url, context)
        sys.stdout.write(f"{url}: {problem or 'ok'}\n")
        failed += problem is not None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
