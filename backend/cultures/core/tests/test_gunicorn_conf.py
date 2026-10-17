import runpy
from pathlib import Path

import pytest
from django.conf import settings

CONF = Path(settings.BASE_DIR) / "gunicorn.conf.py"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GUNICORN_WORKERS", "GUNICORN_THREADS", "GUNICORN_FORWARDED_ALLOW_IPS"):
        monkeypatch.delenv(name, raising=False)
    conf = runpy.run_path(str(CONF))
    assert conf["worker_class"] == "gthread"
    assert conf["workers"] == 2
    assert conf["max_requests"] > 0
    assert conf["max_requests_jitter"] > 0
    assert conf["forwarded_allow_ips"] == "127.0.0.1,::1"
    assert conf["worker_tmp_dir"] == "/dev/shm"
    assert conf["accesslog"] == "-"
    # No control socket: the runtime image runs read-only and nothing uses gunicornc.
    assert conf["control_socket_disable"] is True


def test_the_access_log_carries_the_request_id() -> None:
    # The proxy's or the app's X-Request-ID joins the access log to the app log.
    conf = runpy.run_path(str(CONF))
    assert "request_id=%({x-request-id}o)s" in conf["access_log_format"]


def test_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUNICORN_WORKERS", "5")
    monkeypatch.setenv("GUNICORN_TIMEOUT", "60")
    monkeypatch.setenv("GUNICORN_FORWARDED_ALLOW_IPS", "10.0.0.1")
    conf = runpy.run_path(str(CONF))
    assert (conf["workers"], conf["timeout"], conf["forwarded_allow_ips"]) == (5, 60, "10.0.0.1")


def test_a_bad_number_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUNICORN_WORKERS", "four")
    with pytest.raises(SystemExit, match="GUNICORN_WORKERS"):
        runpy.run_path(str(CONF))
