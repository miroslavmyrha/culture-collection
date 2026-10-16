from rest_framework import authentication
from rest_framework.request import Request


class SessionAuthentication(authentication.SessionAuthentication):
    """Session auth that answers anonymous requests with 401, not 403.

    DRF sends 401 only when the first authentication class names a
    WWW-Authenticate challenge; the stock SessionAuthentication names none, so
    "not logged in" and "not allowed" were both 403. Now 401 means "log in",
    403 means "logged in but not allowed" (or a CSRF failure).
    The scheme name is not Basic, so browsers never show a login dialog.
    """

    def authenticate_header(self, request: Request) -> str:
        return 'Session realm="api"'
