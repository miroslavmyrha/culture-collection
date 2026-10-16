from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


def enforce_csrf(request: Request) -> None:
    """Require a valid CSRF token on an anonymous, state-changing endpoint.

    DRF marks its views csrf_exempt and SessionAuthentication checks CSRF only
    once a session user exists, so login and other anonymous writes are open to
    cross-site requests. Django's csrf_protect decorator does not help either:
    it sees the inner view's csrf_exempt flag and skips the check.
    Raises PermissionDenied (403) when the token is missing or wrong.
    """
    SessionAuthentication().enforce_csrf(request)
