"""Run one scheduled job and report it to Healthchecks (#180).

    python tools/run_job.py <check> [--timeout SECONDS] -- <command> [args...]

Pings <base>/<check>/start, runs the command with its output passed through, then pings
<base>/<check> on success or <base>/<check>/<exit code> on failure, with the tail of the
output as the body. <base> is the ping URL of the Healthchecks project with its ping key
(https://<healthchecks>/ping/<ping-key>), read from the file in HEALTHCHECKS_PING_URL_FILE or
from HEALTHCHECKS_PING_URL. A check is named by its slug.

Without a base the job still runs, and one warning says that nothing is reported. A ping that
fails (network, server) is logged and never changes the job's exit code: the ping that does not
arrive is what Healthchecks alerts on. A job over its timeout is killed with its process group
and ends with 124, as timeout(1) does.

Standard library only: it runs in the backend image (the scheduler service of
deploy/compose.yaml) and with the host's python3 (the backups, docs/runbook.md).
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Sequence
from http import HTTPStatus

TIMED_OUT = 124
TAIL_BYTES = 10_000  # Healthchecks keeps the first 10 kB of a ping body by default
PING_TIMEOUT = 10.0
PING_ATTEMPTS = 3
PING_PAUSE = 1.0  # seconds, times the attempt number
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")

# What must never leave the host in a ping body, whatever a job prints.
_REDACTIONS = (
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", re.IGNORECASE), r"\1[redacted]@"),
    (
        re.compile(
            r"\b(\w*(?:password|passwd|secret|token|key|dsn)\w*)(\s*[=:]\s*)\S+", re.IGNORECASE
        ),
        r"\1\2[redacted]",
    ),
)


def redact(text: str) -> str:
    """The text with credentials in URLs and values of secret-looking names replaced."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def ping_base() -> str | None:
    """The project's ping URL, or None when reporting is not configured."""
    path = os.environ.get("HEALTHCHECKS_PING_URL_FILE", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError as problem:
            log(f"cannot read HEALTHCHECKS_PING_URL_FILE ({problem}): nothing is reported")
            return None
    else:
        value = os.environ.get("HEALTHCHECKS_PING_URL", "").strip()
    return value.rstrip("/") or None


def log(message: str) -> None:
    sys.stderr.write(f"run_job: {message}\n")
    sys.stderr.flush()


def ping(url: str, body: bytes = b"") -> bool:
    """POST one ping, a few attempts. Never raises: a lost ping is Healthchecks' alarm."""
    for attempt in range(1, PING_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 (the operator's URL)
            with urllib.request.urlopen(request, timeout=PING_TIMEOUT) as response:  # noqa: S310
                if HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
                    return True
                problem = f"HTTP {response.status}"
        except (urllib.error.URLError, OSError, ValueError) as error:
            problem = str(error)
        if attempt < PING_ATTEMPTS:
            time.sleep(attempt * PING_PAUSE)
    log(f"ping failed after {PING_ATTEMPTS} attempts ({problem}): {_without_key(url)}")
    return False


def _without_key(url: str) -> str:
    # The ping key is a secret: the log names the check, not the key.
    return re.sub(r"/ping/[^/]+/", "/ping/[key]/", url)


def run(command: Sequence[str], timeout: float | None) -> tuple[int, bytes]:
    """Run the command, pass its output through, and return the exit code and the tail."""
    tail: collections.deque[bytes] = collections.deque()
    size = [0]
    process = subprocess.Popen(  # noqa: S603 (the crontab's command, not input)
        list(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True
    )
    assert process.stdout is not None  # noqa: S101 (stdout=PIPE above)
    stream = process.stdout

    def pump() -> None:
        for line in iter(stream.readline, b""):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            tail.append(line)
            size[0] += len(line)
            while size[0] > TAIL_BYTES and len(tail) > 1:
                size[0] -= len(tail.popleft())

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = process.wait(timeout=timeout)
        if code < 0:  # killed by a signal: the shell's 128 + n, an exit status Healthchecks takes
            code = 128 - code
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        code = TIMED_OUT
        tail.append(f"\nrun_job: killed after {timeout:g} s\n".encode())
    reader.join(timeout=5)
    return code, b"".join(tail)[-TAIL_BYTES:]


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        usage="run_job.py <check> [--timeout S] -- <command> ...",
    )
    parser.add_argument("check", help="the check's slug in Healthchecks")
    parser.add_argument("--timeout", type=float, default=None, help="seconds, then 124")
    # The job's own options are not ours: everything after the first "--" is the command.
    if "--" not in argv:
        parser.error("no command: run_job.py <check> -- <command> [args...]")
    split = argv.index("--")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1 :]
    if not command:
        parser.error("no command: run_job.py <check> -- <command> [args...]")
    if not _SLUG.match(args.check):
        parser.error(f"check {args.check!r}: lowercase letters, digits and hyphens")

    base = ping_base()
    if base is None:
        log(f"no Healthchecks URL: {args.check} runs, nothing is reported")
        code, _ = run(command, args.timeout)
        return code
    check = f"{base}/{args.check}"
    run_id = f"?rid={uuid.uuid4()}"
    ping(f"{check}/start{run_id}")
    code, output = run(command, args.timeout)
    body = redact(output.decode("utf-8", "replace")).encode()
    ping(f"{check}{run_id}" if code == 0 else f"{check}/{code}{run_id}", body)
    return code


if __name__ == "__main__":
    sys.exit(main())
