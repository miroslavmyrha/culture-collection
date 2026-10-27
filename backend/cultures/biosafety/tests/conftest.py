"""The labs and people of the labs tests (labs/tests/conftest.py: Mycology with one member of
every role, Bacteriology managed by `outsider`), and staff acting outside a request. Helpers:
support.py."""

from collections.abc import Iterator

import pytest
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.labs.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    curator,
    lab,
    manager,
    other_lab,
    outsider,
    team,
    technician,
    viewer,
)
from cultures.users.models import User


@pytest.fixture
def staff() -> User:
    user: User = baker.make(User, username="staff", is_staff=True, is_superuser=True)
    return user


@pytest.fixture
def as_staff(staff: User) -> Iterator[AuditContext]:
    with audit_context(channel=Channel.COMMAND, actor=staff, request_id="cmd-1") as context:
        yield context
