"""The growth tests' fixtures are the strains tests' (labs, people, taxa, strains), plus media."""

from collections.abc import Callable
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.growth import services
from cultures.growth.models import GrowthMedium
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.strains.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    as_curator,
    curator,
    curator_access,
    exempli,
    lab,
    make_strain,
    manager,
    other_lab,
    outsider,
    team,
    technician,
    testella,
    viewer,
)
from cultures.users.models import User

MakeMedium = Callable[..., GrowthMedium]


@pytest.fixture
def make_medium(lab: Lab, curator: User) -> MakeMedium:  # noqa: F811
    """A medium made by the curator through the service, in its own audit context."""

    def make(
        name: str = "Testella broth", lab: Lab = lab, actor: User = curator, **changes: Any
    ) -> GrowthMedium:
        with audit_context(channel=Channel.API, actor=actor, request_id="req-setup"):
            return services.medium_create(access=access_for(actor), lab=lab, name=name, **changes)

    return make
