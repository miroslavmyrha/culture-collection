"""Who finds what (#76): each kind only from the labs where the person holds the permission of
that kind's own list (KIND_PERM), never from a lab they are not in, and in a lab only what
their role there may read. A person in two labs with two roles gets each lab by its role."""

import pytest

from cultures.deposits.models import Depositor
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import RANK, ROLES, Role, role_has
from cultures.labs.tests.conftest import member_of
from cultures.search.selectors import KIND_PERM, Kind
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .fixtures import Stock, batch_of, intake
from .support import groups, ids

pytestmark = pytest.mark.django_db


def test_every_kind_has_a_permission() -> None:
    assert set(KIND_PERM) == set(Kind)


# The lowest role that finds each kind, as the owner decided it (#76): what that role's own
# list shows. Spelled out, so a change of KIND_PERM that lets another role find a kind fails here.
LOWEST: dict[Kind, Role] = {
    Kind.STRAIN: Role.VIEWER,
    Kind.VIAL: Role.VIEWER,
    Kind.DEPOSIT: Role.CURATOR,
    Kind.REQUEST: Role.VIEWER,
}


def _text(kind: Kind, stock: Stock) -> str:
    """A text that finds exactly the stock's row of the kind in `lab`."""
    if kind == Kind.STRAIN:
        return "Testella exempli S1"
    if kind == Kind.VIAL:
        return "TUBE-R"
    if kind == Kind.DEPOSIT:
        return "Testella exempli Q7"
    return stock.request.label


def _row(kind: Kind, stock: Stock) -> str:
    row = {
        Kind.STRAIN: stock.strain,
        Kind.VIAL: stock.masked,
        Kind.DEPOSIT: stock.received,
        Kind.REQUEST: stock.request,
    }[kind]
    return str(row.public_id)


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("role", ROLES)
def test_a_role_finds_a_kind_exactly_when_it_holds_the_kinds_permission(
    role: Role, kind: Kind, stock: Stock, lab: Lab
) -> None:
    person = member_of(lab, role, f"searcher-{role}")
    hits = ids(person, _text(kind, stock)).get(kind.value, set())
    if role_has(role, KIND_PERM[kind]):
        assert hits == {_row(kind, stock)}
    else:
        assert hits == set()
    assert (RANK[role] >= RANK[LOWEST[kind]]) == bool(hits)


@pytest.mark.parametrize("kind", list(Kind))
def test_a_manager_of_another_lab_finds_nothing_of_this_one(
    kind: Kind, stock: Stock, outsider: User
) -> None:
    assert _row(kind, stock) not in ids(outsider, _text(kind, stock)).get(kind.value, set())


def test_the_same_barcode_in_two_labs_is_found_in_the_labs_of_the_person(
    stock: Stock, curator: User, lab: Lab, other_lab: Lab
) -> None:
    # The curator is in lab only: TUBE-1 of the other lab is not theirs.
    assert ids(curator, "TUBE-1") == {"vial": {str(stock.vials[0].public_id)}}
    assert ids(stock.other_curator, "TUBE-1") == {"vial": {str(stock.other_vial.public_id)}}
    both = member_of(lab, Role.VIEWER, "both")
    Membership.objects.create(user=both, lab=other_lab, role=Role.VIEWER)
    group = groups(both, "TUBE-1")["vial"]
    assert {hit["public_id"] for hit in group["hits"]} == {
        str(stock.vials[0].public_id),
        str(stock.other_vial.public_id),
    }
    assert [(entry["lab_code"], entry["total"]) for entry in group["labs"]] == [
        ("BAC", 1),
        ("MYC", 1),
    ]
    assert group["total"] == 2


def test_a_person_in_two_labs_gets_each_lab_by_the_role_there(
    stock: Stock, lab: Lab, other_lab: Lab
) -> None:
    """Curator of lab (MYC), viewer of other_lab (BAC): strains from both, deposits only from
    the lab where they are a curator."""
    person = member_of(lab, Role.CURATOR, "two-labs")
    Membership.objects.create(user=person, lab=other_lab, role=Role.VIEWER)
    found_now = groups(person, "Testella exempli")
    strain_labs = {hit["lab_code"] for hit in found_now["strain"]["hits"]}
    assert strain_labs == {"MYC", "BAC"}
    deposit_titles = {hit["title"] for hit in found_now["deposit"]["hits"]}
    assert "Testella exempli Q7" in deposit_titles
    assert "Testella exempli Q8" not in deposit_titles
    assert "Testella exempli B1" not in deposit_titles
    assert {entry["lab_code"] for entry in found_now["deposit"]["labs"]} == {"MYC"}
    # The other way round, the deposits of BAC appear and those of MYC are gone.
    Membership.objects.filter(user=person, lab=lab).update(role=Role.VIEWER)
    Membership.objects.filter(user=person, lab=other_lab).update(role=Role.CURATOR)
    deposits = groups(person, "Testella exempli Q")["deposit"]
    assert [hit["title"] for hit in deposits["hits"]] == ["Testella exempli Q8"]


def test_the_number_itself_comes_first_and_only_it_is_exact(
    stock: Stock, lab: Lab, curator: User, depositor: Depositor, exempli: Taxon
) -> None:
    # Ten more strains: MYC 1 is followed by MYC 10 and up, which start with its number.
    for i in range(10):
        intake(lab, curator, depositor, f"Fictivibrio more {i}", exempli)
    number = stock.strain.accession_number
    assert number is not None
    strains = groups(curator, number)["strain"]
    assert strains["hits"][0]["identifier"] == number
    assert [hit["exact"] for hit in strains["hits"]] == [True] + [False] * (
        len(strains["hits"]) - 1
    )


def test_each_kind_lists_five_with_the_total_of_every_lab(
    stock: Stock, lab: Lab, curator: User, depositor: Depositor, exempli: Taxon
) -> None:
    for i in range(6):
        intake(lab, curator, depositor, f"Fictivibrio many {i}", exempli)
    strains = groups(curator, "Fictivibrio many")["strain"]
    assert len(strains["hits"]) == 5
    assert strains["total"] == 6
    assert [(entry["lab_code"], entry["total"]) for entry in strains["labs"]] == [("MYC", 6)]
    deposits = groups(curator, "Fictivibrio many")["deposit"]
    assert (len(deposits["hits"]), deposits["total"]) == (5, 6)


def test_a_request_is_found_by_its_number_alone_and_by_no_other_text(
    stock: Stock, viewer: User
) -> None:
    request = stock.request
    assert ids(viewer, request.label) == {"request": {str(request.public_id)}}
    exact = groups(viewer, request.label)["request"]["hits"][0]["exact"]
    assert exact is True
    # Another year is another request: none here.
    assert "request" not in groups(viewer, f"{request.year - 1}/{request.number}")
    # The number without its year finds it in every year, but names no single request.
    alone = groups(viewer, f"{request.number:02}")
    assert str(request.public_id) in {hit["public_id"] for hit in alone["request"]["hits"]}
    assert alone["request"]["hits"][0]["exact"] is False
    # The institution finds no request here: the request list searches it, the top bar does not.
    assert "request" not in groups(viewer, request.requester.institution)


def test_a_vial_names_its_strain_and_lab(stock: Stock, viewer: User) -> None:
    hit = groups(viewer, "TUBE-1")["vial"]["hits"][0]
    assert hit["strain"] == str(stock.strain.public_id)
    assert hit["lab_code"] == "MYC"
    assert hit["identifier"] == f"{stock.strain.accession_number} / 1 / 1"
    assert hit["title"] == "Testella exempli"


def test_a_deposit_names_the_strain_it_became(stock: Stock, curator: User) -> None:
    hits = groups(curator, "Testella exempli S1")["deposit"]["hits"]
    assert [(hit["identifier"], hit["strain"], hit["exact"]) for hit in hits] == [
        (stock.strain.accession_number, str(stock.strain.public_id), False)
    ]
    received = groups(curator, "Testella exempli Q7")["deposit"]["hits"][0]
    assert (received["identifier"], received["strain"], received["status"]) == (
        None,
        None,
        "received",
    )


def test_a_vial_of_a_new_batch_is_found_by_its_label(
    stock: Stock, curator: User, viewer: User
) -> None:
    batch_of(curator, stock.strain, 1)
    assert set(groups(viewer, f"{stock.strain.accession_number} / 2 / 1")) == {"vial"}


def test_five_in_all_across_two_labs_with_each_labs_total(
    *, stock: Stock, lab: Lab, other_lab: Lab, curator: User, depositor: Depositor, exempli: Taxon
) -> None:
    """Each lab gives at most five, and the group shows five of them all together."""
    other_depositor = Depositor.objects.filter(lab=other_lab).get()
    for i in range(3):
        intake(lab, curator, depositor, f"Fictivibrio spread {i}", exempli)
        intake(other_lab, stock.other_curator, other_depositor, f"Fictivibrio spread {i}", exempli)
    both = member_of(lab, Role.VIEWER, "spread")
    Membership.objects.create(user=both, lab=other_lab, role=Role.VIEWER)
    strains = groups(both, "Fictivibrio spread")["strain"]
    assert len(strains["hits"]) == 5
    assert strains["total"] == 6
    assert [(entry["lab_code"], entry["total"]) for entry in strains["labs"]] == [
        ("BAC", 3),
        ("MYC", 3),
    ]
