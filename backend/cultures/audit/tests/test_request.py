"""A request is its own audit context: its X-Request-ID and its signed-in user.

No routed API view writes audited data yet, so a test-only view routed with
pytest.mark.urls stands in for one. The contract coverage meta-test walks the
project's URLconf, which does not contain this view.
"""

from typing import cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.signals import request_finished
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.audit import context as audit
from cultures.audit.context import AuditRequestMiddleware, MissingAuditContext, audit_context
from cultures.audit.events import Change, record_event
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.audit.registry import USER_DEACTIVATED
from cultures.core.request_id import RequestIdMiddleware
from cultures.core.testing import logged_in
from cultures.users.models import User
from cultures.users.services import user_deactivate

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]


@api_view(["POST"])
def deactivate(request: Request, public_id: str) -> Response:
    reason = cast(dict[str, str], request.data)["reason"]
    user_deactivate(user=User.objects.get(public_id=public_id), reason=reason)
    return Response(status=204)


urlpatterns = [path("users/<uuid:public_id>/deactivate/", deactivate)]


def test_an_api_write_carries_the_request_id_and_the_signed_in_user(
    admin: User, member: User
) -> None:
    response = logged_in(admin).post(
        f"/users/{member.public_id}/deactivate/",
        {"reason": "left the lab"},
        content_type="application/json",
        headers={"X-Request-ID": "req-123"},
    )

    assert response.status_code == 204
    event = AuditEvent.objects.get()
    assert (event.channel, event.request_id, event.actor, event.actor_kind) == (
        "api",
        "req-123",
        admin,
        "user",
    )
    assert event.reason == "left the lab"


def test_the_row_change_of_an_api_write_joins_its_event_by_request_id(
    admin: User, member: User
) -> None:
    logged_in(admin).post(
        f"/users/{member.public_id}/deactivate/",
        {"reason": "left the lab"},
        content_type="application/json",
        headers={"X-Request-ID": "req-456"},
    )

    event = AuditEvent.objects.get()
    row = RowChange.objects.get(request_id=event.request_id)
    assert (row.table_label, row.row_pk, row.op) == ("users.user", str(member.pk), "UPDATE")
    assert (row.old, row.new) == ({"is_active": True}, {"is_active": False})
    assert (row.actor_id, row.occurred_at) == (admin.pk, event.occurred_at)


def test_no_context_is_left_after_the_request(admin: User, member: User) -> None:
    logged_in(admin).post(
        f"/users/{member.public_id}/deactivate/",
        {"reason": "left the lab"},
        content_type="application/json",
    )
    with pytest.raises(MissingAuditContext):
        audit.current_context()


def run_in_request(request: HttpRequest) -> list[object]:
    """Runs the middleware around a view that records what the audit context says."""
    seen: list[object] = []
    subject_id = User().public_id

    def view(request: HttpRequest) -> HttpResponse:
        seen.append(audit.current_context())
        try:
            record_event(USER_DEACTIVATED, Change("user", subject_id, {}), reason="x")
        except MissingAuditContext as error:
            seen.append(error)
        return HttpResponse()

    AuditRequestMiddleware(view)(request)
    return seen


def test_an_anonymous_request_has_a_context_but_no_actor_so_writes_fail() -> None:
    request = RequestFactory().post("/")
    request.user = AnonymousUser()

    context, error = run_in_request(request)

    assert isinstance(context, audit.AuditContext)
    assert (context.channel, context.actor) == ("api", None)
    assert isinstance(error, MissingAuditContext)
    assert not AuditEvent.objects.exists()


def test_a_context_entered_inside_a_request_keeps_the_request_id() -> None:
    """A task or a reason entered during a request still joins the request's rows."""
    seen: list[str] = []

    def view(request: HttpRequest) -> HttpResponse:
        with audit_context(channel=Channel.TASK, actor_kind=ActorKind.SYSTEM):
            seen.append(audit.current_context().request_id)
        return HttpResponse()

    request = RequestFactory().get("/", headers={"X-Request-ID": "req-789"})
    try:
        RequestIdMiddleware(view)(request)
    finally:
        request_finished.send(sender=None)  # clears the request id, as Django does
    assert seen == ["req-789"]
