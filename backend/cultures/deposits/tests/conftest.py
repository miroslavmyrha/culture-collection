"""The deposits tests' fixtures. The labs, people and taxa are the strains tests'
(strains/tests/conftest.py): Mycology (MYC) with one member of every role, Bacteriology
(BAC) managed by `outsider`, and the invented taxa Testella, Mockia and Fictivibrio, so no
real organism gets a legal status it does not have. Data and helpers: support.py."""

from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.strains.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    alpha,
    as_curator,
    curator,
    curator_access,
    exempli,
    fictivibrio,
    lab,
    make_strain,
    manager,
    mockia,
    other_lab,
    outsider,
    team,
    technician,
    testella,
    viewer,
)

from .fixtures import depositor, make_deposit, make_depositor, mta  # noqa: F401 (fixtures)
