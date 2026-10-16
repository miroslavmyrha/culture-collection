"""Failed-login limit per account, on top of the per-IP throttle.

The per-IP throttle alone lets a botnet try one account from many addresses.
Here failures are counted per normalized username (case, width and blanks
folded) in the shared cache. The cache key is an HMAC of the name, so neither
the cache nor its logs hold user names. Failures also count for names that do
not exist, so the limit does not reveal which accounts exist. A successful
login clears the counter. While the limit is reached even the right password
is refused until the window passes, otherwise the attacker would still win.

Counting is read-modify-write: with DatabaseCache concurrent failures can be
under-counted by a few; the per-IP throttle bounds the rest.
"""

import hashlib
import hmac
import unicodedata

from django.conf import settings
from django.core.cache import cache

_PREFIX = "login-failures:"


def normalize_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username).strip().casefold()


def account_key(username: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        b"login-limit:" + normalize_username(username).encode(),
        hashlib.sha256,
    ).hexdigest()
    return _PREFIX + digest


def is_locked(username: str) -> bool:
    failures: int = cache.get(account_key(username), 0)
    return failures >= settings.LOGIN_ACCOUNT_MAX_FAILURES


def record_failure(username: str) -> None:
    key = account_key(username)
    cache.set(key, cache.get(key, 0) + 1, timeout=settings.LOGIN_ACCOUNT_WINDOW_SECONDS)


def clear(username: str) -> None:
    cache.delete(account_key(username))
