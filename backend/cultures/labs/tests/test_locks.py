"""One check of the actor's committed role, under the lab lock (#232)."""

import pytest
from django.db import transaction

from cultures.core.exceptions import Forbidden
from cultures.labs.access import access_for
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role
from cultures.users.models import User

pytestmark = pytest.mark.django_db


def test_the_role_is_read_under_the_lock_and_returned(lab: Lab, manager: User) -> None:
    with transaction.atomic():
        lock_lab(lab.pk)
        assert require_committed(access_for(manager), lab.pk, Perm.MANAGE_MEMBERS) == Role.MANAGER


def test_without_the_lab_lock_it_fails_loudly(lab: Lab, manager: User) -> None:
    with transaction.atomic(), pytest.raises(RuntimeError, match="without its lock"):
        require_committed(access_for(manager), lab.pk, Perm.MANAGE_MEMBERS)


def test_the_lock_of_another_lab_is_not_this_one(lab: Lab, other_lab: Lab, manager: User) -> None:
    with transaction.atomic(), pytest.raises(RuntimeError, match="without its lock"):
        lock_lab(other_lab.pk)
        require_committed(access_for(manager), lab.pk, Perm.MANAGE_MEMBERS)


@pytest.mark.django_db(transaction=True)  # two real transactions, not savepoints of the test's
def test_a_lock_of_an_earlier_transaction_does_not_count(lab: Lab, manager: User) -> None:
    with transaction.atomic():
        lock_lab(lab.pk)
    with transaction.atomic(), pytest.raises(RuntimeError, match="without its lock"):
        require_committed(access_for(manager), lab.pk, Perm.MANAGE_MEMBERS)


def test_the_committed_role_counts_not_the_one_the_request_began_with(
    lab: Lab, manager: User
) -> None:
    access = access_for(manager)  # built while the user is a manager
    Membership.objects.filter(user=manager, lab=lab).update(role=Role.VIEWER)
    with transaction.atomic(), pytest.raises(Forbidden):
        lock_lab(lab.pk)
        require_committed(access, lab.pk, Perm.MANAGE_MEMBERS)


def test_a_deactivated_member_is_refused_whatever_the_role(lab: Lab, manager: User) -> None:
    access = access_for(manager)
    User.objects.filter(pk=manager.pk).update(is_active=False)
    with transaction.atomic(), pytest.raises(Forbidden):
        lock_lab(lab.pk)
        require_committed(access, lab.pk, Perm.MANAGE_MEMBERS)
