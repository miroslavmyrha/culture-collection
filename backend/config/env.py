"""Strict environment parsing for settings.

Every helper raises ImproperlyConfigured on a value it does not understand,
so a typo stops the process at startup instead of turning into the default value.
django-environ's env.bool turns unknown values into False and its file-aware
variant keeps the trailing newline of secret files, so neither is used here.
"""

import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None:
        if default is None:
            raise ImproperlyConfigured(f"Set the environment variable {name}.")
        return default
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name}={value!r} is not a boolean: use true or false.")


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        number = int(value.strip())
    except ValueError:
        raise ImproperlyConfigured(f"{name}={value!r} is not an integer.") from None
    if minimum is not None and number < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}, got {number}.")
    return number


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Comma-separated list; blanks around items are dropped."""
    value = os.environ.get(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


def env_networks(name: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Comma-separated IP addresses or networks (CIDR), as ipaddress networks.

    Strict like gunicorn's forwarded_allow_ips, which reads the same value: host
    bits set (192.0.2.1/24) are refused, and so is a /0 network, which would
    trust every client.
    """
    networks = []
    for entry in env_list(name):
        try:
            network = ipaddress.ip_network(entry)
        except ValueError:
            raise ImproperlyConfigured(
                f"{name}: {entry!r} is not an IP address or network (CIDR without host bits)."
            ) from None
        if network.prefixlen == 0:
            raise ImproperlyConfigured(f"{name}: {entry!r} would trust every client.")
        networks.append(network)
    return tuple(networks)


def env_secret(name: str, default: str | None = None) -> str:
    """A secret from NAME_FILE (a mounted secret file) or NAME.

    The file wins when NAME_FILE is set; one trailing newline is stripped.
    An unreadable or empty file stops startup and never falls back to the default.
    """
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        if name in os.environ:
            raise ImproperlyConfigured(f"Set {name} or {name}_FILE, not both.")
        try:
            value = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ImproperlyConfigured(
                f"{name}_FILE={file_path!r} is not readable: {exc}"
            ) from None
        value = value.removesuffix("\n").removesuffix("\r")
        if not value:
            raise ImproperlyConfigured(f"{name}_FILE={file_path!r} is empty.")
        return value
    return env_str(name, default)
