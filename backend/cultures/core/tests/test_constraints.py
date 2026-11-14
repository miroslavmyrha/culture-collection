"""The constraints as the final arbiter of a write, and the error each one means (#232)."""

import pytest
from django.db import IntegrityError

from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict
from cultures.labs.models import LAB_NAME_UNIQUE, Lab
from cultures.labs.tests.conftest import make_lab

pytestmark = pytest.mark.django_db


class Taken(Conflict):
    default_code = "taken"


def test_a_named_constraint_raises_its_error_and_the_transaction_goes_on() -> None:
    first = make_lab(name="Alpha", code="ALP")
    twin = Lab(name="Alpha", code="ALQ")
    with pytest.raises(Taken):
        save_arbitrated(twin, {LAB_NAME_UNIQUE: Taken()})
    assert Lab.objects.filter(pk=first.pk).exists()  # a query works after: only a savepoint died


def test_a_constraint_it_does_not_name_is_raised_as_it_is() -> None:
    make_lab(name="Alpha", code="ALP")
    with pytest.raises(IntegrityError):
        save_arbitrated(Lab(name="Alpha", code="ALQ"), {})
