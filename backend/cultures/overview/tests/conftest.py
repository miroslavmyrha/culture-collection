"""The overview tests' fixtures: the labs, people and taxa of the strains tests, deposits and the
MTA of the deposits tests, the storage tree of the storage tests, and the supplied strains,
requesters and regulated requests of the distribution tests. Helpers: support.py."""

from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.deposits.tests.fixtures import depositor, make_deposit, make_depositor, mta  # noqa: F401
from cultures.distribution.tests.fixtures import (  # noqa: F401 (fixtures)
    approver,
    make_requester,
    regulated,
    requester,
    supply,
)
from cultures.storage.tests.conftest import box_9x9, box_10x10, make_unit, tree  # noqa: F401
from cultures.strains.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    curator,
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
