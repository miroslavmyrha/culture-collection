"""run_job.py against a Healthchecks stand-in on the loopback: what it pings, when, with what."""

from __future__ import annotations

import socket
import sys
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tools import run_job
from tools.tests.support import NO_NETWORK

PYTHON = sys.executable


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loopback stand-in only: any other host is refused, as in the other tools tests."""
    real = urllib.request.urlopen

    def loopback_only(request: Any, *args: Any, **kwargs: Any) -> Any:
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        if urllib.parse.urlsplit(url).hostname != "127.0.0.1":
            raise AssertionError(NO_NETWORK)
        return real(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", loopback_only)


class Pings:
    """Records each ping: its path (without the run id) and its body."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        self.run_ids: set[str] = set()


@pytest.fixture
def healthchecks(monkeypatch: pytest.MonkeyPatch) -> Iterator[Pings]:
    pings = Pings()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            parts = urllib.parse.urlsplit(self.path)
            pings.seen.append((parts.path, body))
            pings.run_ids.update(urllib.parse.parse_qs(parts.query).get("rid", []))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{server.server_port}/ping/key")
    monkeypatch.delenv("HEALTHCHECKS_PING_URL_FILE", raising=False)
    yield pings
    server.shutdown()


def job(code: str) -> list[str]:
    return ["--", PYTHON, "-c", code]


def test_a_job_that_succeeds_pings_start_then_success_with_its_output(healthchecks: Pings) -> None:
    assert run_job.main(["nightly", *job("print('done 42')")]) == 0
    assert [path for path, _ in healthchecks.seen] == [
        "/ping/key/nightly/start",
        "/ping/key/nightly",
    ]
    assert "done 42" in healthchecks.seen[1][1]
    assert len(healthchecks.run_ids) == 1  # start and end are one run


def test_a_job_that_fails_pings_its_exit_code_and_returns_it(healthchecks: Pings) -> None:
    code = "import sys; print('broken'); sys.exit(3)"
    assert run_job.main(["nightly", *job(code)]) == 3
    assert [path for path, _ in healthchecks.seen] == [
        "/ping/key/nightly/start",
        "/ping/key/nightly/3",
    ]
    assert "broken" in healthchecks.seen[1][1]


def test_a_job_over_its_timeout_is_killed_and_reported_as_124(healthchecks: Pings) -> None:
    code = "import time; print('started', flush=True); time.sleep(30)"
    assert run_job.main(["nightly", "--timeout", "1", *job(code)]) == run_job.TIMED_OUT
    path, body = healthchecks.seen[-1]
    assert path == "/ping/key/nightly/124"
    assert "started" in body
    assert "killed after 1 s" in body


def test_without_a_url_the_job_runs_and_one_warning_says_nothing_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_PING_URL_FILE", raising=False)
    marker = tmp_path / "ran"
    code = f"import sys; open({str(marker)!r}, 'w').close(); sys.exit(5)"
    assert run_job.main(["nightly", *job(code)]) == 5
    assert marker.exists()
    assert capsys.readouterr().err.count("nothing is reported") == 1


def test_an_empty_url_file_means_not_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # deploy.sh secrets writes the file empty: the jobs run until the operator fills it in.
    empty = tmp_path / "healthchecks_ping_url"
    empty.write_text("\n")
    monkeypatch.setenv("HEALTHCHECKS_PING_URL_FILE", str(empty))
    assert run_job.main(["nightly", *job("pass")]) == 0
    assert "nothing is reported" in capsys.readouterr().err


def test_the_url_comes_from_the_file_before_the_environment(
    healthchecks: Pings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    url = run_job.ping_base()
    secret = tmp_path / "healthchecks_ping_url"
    secret.write_text(f"{url}/\n")  # a trailing slash and newline, as an editor leaves them
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "http://127.0.0.1:9/ping/wrong")
    monkeypatch.setenv("HEALTHCHECKS_PING_URL_FILE", str(secret))
    assert run_job.main(["nightly", *job("pass")]) == 0
    assert [path for path, _ in healthchecks.seen] == [
        "/ping/key/nightly/start",
        "/ping/key/nightly",
    ]


def test_an_unreachable_healthchecks_never_changes_the_jobs_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with socket.socket() as probe:  # a port nobody listens on
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/key")
    monkeypatch.setattr(run_job, "PING_PAUSE", 0.0)
    marker = tmp_path / "ran"
    assert run_job.main(["nightly", *job(f"open({str(marker)!r}, 'w').close()")]) == 0
    assert marker.exists()
    err = capsys.readouterr().err
    assert err.count("ping failed") == 2  # start and success, each after its attempts
    assert "/ping/key/" not in err  # the log names the check, never the key


def test_a_ping_body_carries_no_credentials(healthchecks: Pings) -> None:
    code = "print('postgres://cultures_app:s3cret@db:5432/cultures'); print('DB_PASSWORD=hunter2')"
    assert run_job.main(["nightly", *job(code)]) == 0
    body = healthchecks.seen[-1][1]
    assert "s3cret" not in body
    assert "hunter2" not in body
    assert "postgres://[redacted]@db:5432/cultures" in body


def test_the_body_is_the_tail_of_a_long_output(healthchecks: Pings) -> None:
    code = "[print(f'line {n:06}') for n in range(5000)]"
    assert run_job.main(["nightly", *job(code)]) == 0
    body = healthchecks.seen[-1][1]
    assert len(body.encode()) <= run_job.TAIL_BYTES
    assert "line 004999" in body
    assert "line 000000" not in body


def test_a_check_name_is_a_slug(healthchecks: Pings) -> None:
    with pytest.raises(SystemExit):
        run_job.main(["../other", *job("pass")])
    assert healthchecks.seen == []
