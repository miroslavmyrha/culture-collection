"""The distribution tests' fixtures. The labs, people and taxa are the strains tests'
(strains/tests/conftest.py), deposits and the MTA the deposits tests'. Data and helpers:
support.py."""

from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.deposits.tests.fixtures import depositor, make_deposit, make_depositor, mta  # noqa: F401
from cultures.strains.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    as_curator,
    curator,
    curator_access,
    exempli,
    lab,
    manager,
    mockia,
    other_lab,
    outsider,
    team,
    technician,
    testella,
    viewer,
)

from .fixtures import make_requester, requester, supply, world  # noqa: F401 (fixtures)
