import runpy
from pathlib import Path

import pytest
from django.conf import settings
from gunicorn.config import validate_string_to_addr_list

CONF = Path(settings.BASE_DIR) / "gunicorn.conf.py"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GUNICORN_WORKERS", "GUNICORN_THREADS", "DJANGO_TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    conf = runpy.run_path(str(CONF))
    assert conf["worker_class"] == "gthread"
    assert conf["workers"] == 2
    assert conf["max_requests"] > 0
    assert conf["max_requests_jitter"] > 0
    assert conf["forwarded_allow_ips"] == ""  # no proxy: no peer sets X-Forwarded-Proto
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
    conf = runpy.run_path(str(CONF))
    assert (conf["workers"], conf["timeout"]) == (5, 60)


def test_gunicorn_trusts_the_proxies_django_trusts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_TRUSTED_PROXIES", " 10.0.0.5 , 10.1.0.0/16,, 2001:db8::/64 ")
    conf = runpy.run_path(str(CONF))
    assert conf["forwarded_allow_ips"] == "10.0.0.5,10.1.0.0/16,2001:db8::/64"
    # gunicorn's own parser takes it (it would stop the start otherwise).
    assert validate_string_to_addr_list(conf["forwarded_allow_ips"]) == [
        "10.0.0.5",
        "10.1.0.0/16",
        "2001:db8::/64",
    ]


def test_gunicorn_refuses_what_django_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host bits set: Django's env_networks refuses it, and so does gunicorn."""
    monkeypatch.setenv("DJANGO_TRUSTED_PROXIES", "10.0.0.5/24")
    conf = runpy.run_path(str(CONF))
    with pytest.raises(ValueError, match="host bits set"):
        validate_string_to_addr_list(conf["forwarded_allow_ips"])


def test_the_old_forwarded_allow_ips_variable_stops_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUNICORN_FORWARDED_ALLOW_IPS", "10.0.0.1")
    with pytest.raises(SystemExit, match="DJANGO_TRUSTED_PROXIES"):
        runpy.run_path(str(CONF))


def test_a_bad_number_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUNICORN_WORKERS", "four")
    with pytest.raises(SystemExit, match="GUNICORN_WORKERS"):
        runpy.run_path(str(CONF))
