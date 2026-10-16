from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request

from .models import User


def current_user(request: Request) -> User:
    """The authenticated user with a precise type (request.user may be anonymous)."""
    user = request.user
    if not isinstance(user, User):
        raise NotAuthenticated
    return user
