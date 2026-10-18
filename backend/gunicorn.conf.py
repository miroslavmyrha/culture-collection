"""gunicorn settings, all from the environment (GUNICORN_*), read at startup.

Threads per worker (gthread) suit a Django app that waits on PostgreSQL.
Workers restart after max_requests (with jitter, so not all at once) to cap
slow memory growth. Logs go to stdout; the access log carries the request id.
"""

import os


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    if not value.isdigit():
        raise SystemExit(f"{name}={value!r} is not a non-negative integer")
    return int(value)


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = _int("GUNICORN_WORKERS", 2)
worker_class = "gthread"
threads = _int("GUNICORN_THREADS", 4)
timeout = _int("GUNICORN_TIMEOUT", 30)
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int("GUNICORN_KEEPALIVE", 5)
max_requests = _int("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 100)
# Addresses allowed to set X-Forwarded-Proto and friends: the proxy, never "*"
# unless the network guarantees that only the proxy reaches the app.
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
# Heartbeat files in memory: works with a read-only root filesystem.
worker_tmp_dir = os.environ.get("GUNICORN_WORKER_TMP_DIR", "/dev/shm")  # noqa: S108
# gunicorn 25.1+ opens a control socket in $HOME/.gunicorn by default (gunicorn/config.py,
# ControlSocket). Under --read-only it logs an ERROR on every start, and nothing here uses it.
control_socket_disable = True
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms request_id=%({x-request-id}o)s'
