"""A passage has exactly one source and is never changed or deleted (ADR 0008, D1, D3)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.deposits.models import Deposit
from cultures.deposits.tests.support import MakeDeposit
from cultures.lineage.models import Passage
from cultures.taxonomy.models import Taxon

pytestmark = pytest.mark.django_db


@pytest.fixture
def accepted(make_deposit: MakeDeposit, exempli: Taxon) -> Deposit:
    return make_deposit("accepted", taxon=exempli)


def create(**fields: Any) -> Passage:
    with transaction.atomic():
        return Passage.objects.create(**fields)


def test_acceptance_made_passage_0_from_the_deposit(accepted: Deposit) -> None:
    passage = Passage.objects.get()
    assert (passage.number, passage.source_deposit, passage.source_passage, passage.strain) == (
        0,
        accepted,
        None,
        accepted.strain,
    )
    assert passage.lab_id == accepted.lab_id


def test_a_subculture_has_its_parent_as_its_only_source(accepted: Deposit) -> None:
    zero = Passage.objects.get()
    child = create(lab_id=zero.lab_id, strain=zero.strain, number=1, source_passage=zero)
    assert list(zero.children.all()) == [child]


Sources = Callable[[Passage, MakeDeposit], dict[str, Any]]


@pytest.mark.parametrize(
    ("number", "sources", "constraint"),
    [
        (1, lambda zero, make: {}, "lineage_passage_one_source"),
        (
            0,
            lambda zero, make: {"source_passage": zero, "source_deposit": make()},
            "lineage_passage_one_source",
        ),
        (0, lambda zero, make: {"source_passage": zero}, "lineage_passage_zero_iff_from_deposit"),
    ],
)
def test_one_source_and_zero_only_from_the_deposit(
    accepted: Deposit, make_deposit: MakeDeposit, number: int, sources: Sources, constraint: str
) -> None:
    zero = Passage.objects.get()
    with pytest.raises(IntegrityError, match=constraint):
        create(lab_id=zero.lab_id, strain=zero.strain, number=number, **sources(zero, make_deposit))


def test_a_deposit_is_the_source_of_one_passage(accepted: Deposit) -> None:
    zero = Passage.objects.get()
    with pytest.raises(IntegrityError, match="source_deposit_id"):
        create(lab_id=zero.lab_id, strain=zero.strain, number=0, source_deposit=accepted)


@pytest.mark.parametrize(
    "statement",
    ["UPDATE lineage_passage SET number = 5", "DELETE FROM lineage_passage"],
)
def test_a_passage_never_changes_and_is_never_deleted(accepted: Deposit, statement: str) -> None:
    with (
        pytest.raises(
            (IntegrityError, InternalError), match=r"a passage never changes|never deleted"
        ),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement)
