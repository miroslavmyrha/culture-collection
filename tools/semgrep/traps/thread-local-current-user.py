import threading

from crum import get_current_user

_state = threading.local()


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ruleid: thread-local-current-user
        _state.user = request.user
        return self.get_response(request)


def audit(sample):
    # ruleid: thread-local-current-user
    actor = get_current_user()
    return actor


def audit_explicit(sample, actor):
    # ok: thread-local-current-user
    return {"sample": sample.pk, "actor": actor.pk}
