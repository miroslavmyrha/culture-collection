import runpy
from pathlib import Path

import pytest
from django.conf import settings
from gunicorn.config import Config, validate_string_to_addr_list
from gunicorn.http.errors import InvalidSchemeHeaders
from gunicorn.http.parser import RequestParser

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


def scheme(cfg: Config, *headers: str) -> str:
    """The scheme gunicorn's parser gives a request from the proxy at 10.0.0.5."""
    raw = "GET / HTTP/1.1\r\nHost: app.example.com\r\n" + "".join(f"{h}\r\n" for h in headers)
    request = next(iter(RequestParser(cfg, iter([(raw + "\r\n").encode()]), ("10.0.0.5", 4711))))
    return str(request.scheme)


def effective(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("DJANGO_TRUSTED_PROXIES", "10.0.0.5")
    conf = runpy.run_path(str(CONF))
    cfg = Config()
    for name in ("forwarded_allow_ips", "secure_scheme_headers"):
        cfg.set(name, conf[name])
    return cfg


def test_only_x_forwarded_proto_states_the_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = effective(monkeypatch)
    assert scheme(cfg, "X-Forwarded-Proto: https") == "https"
    assert scheme(cfg, "X-Forwarded-Proto: http") == "http"
    # gunicorn's default trusts these two as well; sent by a client and passed on by the
    # proxy, they would make a plain request https for Django.
    assert scheme(cfg, "X-Forwarded-Ssl: on") == "http"
    assert scheme(cfg, "X-Forwarded-Protocol: ssl") == "http"
    assert scheme(cfg) == "http"


def test_a_client_scheme_header_cannot_fail_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = ("X-Forwarded-Proto: https", "X-Forwarded-Ssl: off")
    assert scheme(effective(monkeypatch), *headers) == "https"
    # Under gunicorn's default the second header contradicts the first: a 400.
    default = Config()
    default.set("forwarded_allow_ips", "10.0.0.5")
    with pytest.raises(InvalidSchemeHeaders):
        scheme(default, *headers)
