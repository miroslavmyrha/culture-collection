"""Fixtures named after who acts: staff in admin, an operator running a command, a member."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.core.testing import logged_in
from cultures.users.models import User

PASSWORD = "correct horse battery staple"  # noqa: S105 (a test password)


def make_user(username: str, **fields: Any) -> User:
    user: User = baker.make(User, username=username, email=f"{username}@example.org", **fields)
    return user


@pytest.fixture
def staff() -> User:
    """A staff superuser: the person who uses Django admin."""
    user = make_user("staff", is_staff=True, is_superuser=True)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def admin_client(staff: User) -> Client:
    return logged_in(staff)


@pytest.fixture
def member() -> User:
    """The user staff act on."""
    return make_user("member", first_name="Ada", last_name="Lovelace")


@pytest.fixture
def audited(staff: User) -> Iterator[AuditContext]:
    """Service tests run outside a request: a command run by staff."""
    with audit_context(channel=Channel.COMMAND, actor=staff, request_id="cmd-1") as context:
        yield context


def trail() -> tuple[int, int]:
    """How many audit rows exist: a refused write must not add any."""
    return AuditEvent.objects.count(), RowChange.objects.count()
