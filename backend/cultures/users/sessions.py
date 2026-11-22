"""Ending a user's sessions: erasure (services) and a second factor reset (factors)."""

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session

from .models import User


def end_sessions(user: User) -> int:
    """Delete the user's sessions. The store has no index by user, so this reads them all.

    Erasure and a second factor reset are rare, and the table holds live sessions
    (clearsessions removes old ones). For an erasure the unusable password alone would end
    them at the next request (the session hash no longer matches), but the rows would stay.
    """
    mine = [
        session.pk
        for session in Session.objects.iterator()
        if session.get_decoded().get(SESSION_KEY) == str(user.pk)
    ]
    deleted, _ = Session.objects.filter(pk__in=mine).delete()
    return deleted
