"""Vials in the top bar's search (#76): found by barcode exactly or by label, the box scan's rule,
and where a regulated strain's vial is stored never in the answer (ADR 0009), for every role,
a manager and a holder of the location grant included. A vial of a strain without restrictions
shows its place, as the strain's vial list does."""

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.testing import logged_in
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import ROLES, Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.storage.tests.conftest import Tree
from cultures.strains.tests.conftest import end_restriction
from cultures.users.models import User

from .fixtures import Stock
from .support import SEARCH_URL, groups, ids

pytestmark = pytest.mark.django_db


def test_a_barcode_is_found_exactly(stock: Stock, technician: User) -> None:
    vial = str(stock.vials[0].public_id)
    assert ids(technician, "TUBE-1") == {"vial": {vial}}
    # A scanner may send spaces around the code; the code itself has none.
    assert ids(technician, "  TUBE-1 ") == {"vial": {vial}}
    for near in ("TUBE", "TUBE-", "UBE-1", "tube-1", "TUBE-10"):
        assert "vial" not in ids(technician, near), near


def test_a_label_is_found_with_the_number_in_any_case_and_any_spacing(
    stock: Stock, technician: User
) -> None:
    number = stock.strain.accession_number
    assert number is not None
    second = str(stock.vials[1].public_id)
    for text in (f"{number} / 1 / 2", f"{number.lower()}/1/2", f"  {number}  /1 /  2"):
        assert ids(technician, text).get("vial") == {second}, text
    # Another seq, batch or number is another vial or none.
    assert "vial" not in ids(technician, f"{number} / 1 / 3")
    assert "vial" not in ids(technician, f"{number} / 2 / 2")


def test_a_vial_of_a_strain_without_restrictions_shows_its_place(
    stock: Stock, viewer: User, tree: Tree
) -> None:
    hit = groups(viewer, "TUBE-1")["vial"]["hits"][0]
    assert hit["location_masked"] is False
    assert hit["location"] == {
        "box": str(tree.box.public_id),
        "box_name": "Box 1",
        "path": ["Freezer A", "Rack 1", "Box 1"],
        "row": 1,
        "col": 1,
        "label": "A1",
    }


def test_an_unplaced_vial_has_no_place_and_nothing_masked(stock: Stock, other_lab: Lab) -> None:
    hit = groups(stock.other_curator, "TUBE-1")["vial"]["hits"][0]
    assert (hit["location"], hit["location_masked"]) == (None, False)


def _grant(lab: Lab, manager: User, user: User) -> None:
    with audit_context(channel=Channel.API, actor=manager, request_id="req-grant"):
        labs.location_grant_add(
            access=access_for(manager), lab=lab, membership=membership(user, lab), reason="register"
        )


@pytest.mark.parametrize("granted", [False, True], ids=["without", "with the grant"])
@pytest.mark.parametrize("role", ROLES)
def test_a_regulated_vial_never_carries_its_place(
    role: Role, granted: bool, stock: Stock, lab: Lab, manager: User
) -> None:
    reader = manager if role == Role.MANAGER else member_of(lab, role, f"reader-{role}")
    if granted:
        _grant(lab, manager, reader)
    number = stock.regulated.accession_number
    for text in ("TUBE-R", f"{number} / 1 / 1", "Mockia vulgaris R1", f"{number}"):
        response = logged_in(reader).get(SEARCH_URL, {"q": text})
        assert response.status_code == 200
        body = response.content.decode()
        box = stock.secret_box
        assert str(box.public_id) not in body, text
        assert box.name not in body, text
        assert "Box Hidden" not in body and "A1" not in body, text
    hit = groups(reader, "TUBE-R")["vial"]["hits"][0]
    assert hit["location"] is None
    assert hit["location_masked"] is True
    # It says which strain and lab it belongs to, and nothing of a place.
    assert hit["strain"] == str(stock.regulated.public_id)
    assert (hit["lab_code"], hit["identifier"]) == ("MYC", f"{number} / 1 / 1")
    assert hit["detail"] == "Barcode TUBE-R"


def test_an_ended_restriction_shows_the_place_again(
    stock: Stock, curator: User, manager: User, viewer: User
) -> None:
    # The curator proposes each end, a manager confirms it (#105).
    for restriction in stock.regulated.restrictions.filter(ended_at__isnull=True):
        end_restriction(restriction, proposer=curator, confirmer=manager, reason="delisted")
    hit = groups(viewer, "TUBE-R")["vial"]["hits"][0]
    assert hit["location_masked"] is False
    assert hit["location"]["path"] == ["Freezer A", "Rack 1", "Box Hidden"]
