"""heartbeat.py: ok only when every URL answers 2xx."""

from __future__ import annotations

import socket
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from tools import heartbeat
from tools.tests.support import NO_NETWORK


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loopback stand-in only, as in test_run_job.py."""
    real = urllib.request.urlopen

    def loopback_only(url: Any, *args: Any, **kwargs: Any) -> Any:
        if urllib.parse.urlsplit(url).hostname != "127.0.0.1":
            raise AssertionError(NO_NETWORK)
        return real(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", loopback_only)


@pytest.fixture
def stack() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response({"/readyz": 200, "/down": 503}.get(self.path, 404))
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_ok_when_every_url_answers(stack: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert heartbeat.main([f"{stack}/readyz", f"{stack}/readyz"]) == 0
    assert capsys.readouterr().out.count(": ok") == 2


def test_one_url_not_ready_fails_the_beat(stack: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert heartbeat.main([f"{stack}/readyz", f"{stack}/down"]) == 1
    assert "/down: HTTP 503" in capsys.readouterr().out


def test_nothing_listening_fails_the_beat(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert heartbeat.main([f"http://127.0.0.1:{port}/readyz"]) == 1
    assert ": ok" not in capsys.readouterr().out
