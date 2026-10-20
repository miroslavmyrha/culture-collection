"""The lineage tests' fixtures. The labs, people and taxa are the strains tests'
(strains/tests/conftest.py), deposits come from the deposits tests' fixtures, and the storage
tree from the storage tests' (built in this lab). Data and helpers: support.py."""

from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.deposits.tests.fixtures import depositor, make_deposit, make_depositor  # noqa: F401
from cultures.storage.tests.conftest import box_9x9, box_10x10, make_unit, tree  # noqa: F401
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

from .fixtures import (  # noqa: F401 (fixtures)
    as_technician,
    keeper,
    make_batch,
    passage0,
    regulated,
    strain,
    vial_edges_alone,
)
