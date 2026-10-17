"""Fixtures named after who acts: an admin who deactivates, the members it acts on."""

from collections.abc import Iterator

import pytest
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.users.models import User


def make_user(username: str) -> User:
    user: User = baker.make(User, username=username, email=f"{username}@example.org")
    return user


@pytest.fixture
def admin() -> User:
    """The person who changes other users."""
    return make_user("admin")


@pytest.fixture
def member() -> User:
    return make_user("member")


@pytest.fixture
def audited(admin: User) -> Iterator[AuditContext]:
    """Service tests run outside a request: a command run by the admin, with a reason."""
    with audit_context(
        channel=Channel.COMMAND, actor=admin, reason="left the lab", request_id="cmd-1"
    ) as context:
        yield context
