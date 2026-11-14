from contextvars import ContextVar

current_scope: ContextVar[str | None] = ContextVar("current_scope", default=None)
current_actor = ContextVar("current_actor", default=None)


class ScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ruleid: contextvar-set-without-reset
        current_actor.set(request.user)
        return self.get_response(request)


def push_scope(scope):
    # ok: contextvar-set-without-reset
    token = current_scope.set(scope)
    return token


def clear_scope():
    # ok: contextvar-set-without-reset
    current_scope.set(None)


def with_scope(scope, work):
    old = current_scope.get()
    current_scope.set(scope)
    try:
        return work()
    finally:
        # ok: contextvar-set-without-reset
        current_scope.set(old)


class SafeScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ok: contextvar-set-without-reset
        token = current_actor.set(request.user)
        try:
            return self.get_response(request)
        finally:
            current_actor.reset(token)
