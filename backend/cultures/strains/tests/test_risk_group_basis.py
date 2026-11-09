"""Every risk group states what it rests on, and a basis that names a list entry names the
right one (#169).

Government order 361/2007 Sb., Annex 7, Part A: „Biologické činitele, které nebyly zařazeny do
skupin 2 až 4 seznamu, nejsou automaticky zařazeny do skupiny 1.“ An agent the list does not
place in groups 2 to 4 is not thereby in group 1, so the words of a basis are required even
where a list entry is named, and a group never follows from a list alone.

The entries come from the data files the app holds, read by their own risk group, so no test
here states a legal fact about an organism of its own. The strains are of invented taxa.

Each rule twice: through the service, and against the database for a writer that skips it.
"""

from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.models import ListCode, RegulatoryList, RegulatoryListEntry
from cultures.biosafety.selectors import risk_group_entries, states_risk_group
from cultures.core.exceptions import RuleViolation
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab
from cultures.strains import services
from cultures.strains.models import RiskGroupProposal, Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import ACCESSION_BASIS, STRAINS_URL, MakeStrain, new_strain

pytestmark = pytest.mark.django_db

WORDS = "NV 361/2007 Sb., Příloha 7, část A, tabulka č. 1."


def an_entry(risk_group: int) -> RegulatoryListEntry:
    """An entry of the current reading of annex 7 that states this group. From the data, never
    written down here: the test needs a real entry, not a real organism."""
    found = risk_group_entries().filter(risk_group=risk_group).order_by("code").first()
    assert found is not None, f"no entry of annex 7 states group {risk_group}"
    return found


def another_list_entry() -> RegulatoryListEntry:
    """An entry of a list that states no risk group at all."""
    found = (
        RegulatoryListEntry.objects.filter(
            list__code=ListCode.EU_2021_821_ANNEX_I, list__is_current=True
        )
        .order_by("code")
        .first()
    )
    assert found is not None
    return found


def raw_strain(lab: Lab, template: Strain, **fields: Any) -> Strain:
    """A strain written straight to the table, as a writer that skips the service would."""
    values: dict[str, Any] = {
        f.attname: getattr(template, f.attname)
        for f in Strain._meta.concrete_fields
        if f.attname not in ("id", "public_id", "accession_number", "accession_seq")
    }
    values |= {"accession_number": "MYC 900", "accession_seq": None, **fields}
    return Strain.objects.create(**values)


def guarded(message: str) -> Any:
    return pytest.raises((IntegrityError, InternalError), match=message)


def accession(access: Access, lab: Lab, **changes: Any) -> Strain:
    with audit_context(channel=Channel.API, actor=access.user, request_id="req-basis"):
        return services.strain_create(
            access=access, lab=lab, data=new_strain(changes.pop("taxon"), **changes)
        )


# The basis in words, for every group (R-RISK-07).


@pytest.mark.rule("R-RISK-07")
def test_an_accession_states_what_its_risk_group_rests_on(
    make_strain: MakeStrain, curator: User
) -> None:
    strain = make_strain()
    assert strain.risk_group_basis == ACCESSION_BASIS
    assert strain.risk_group_set_at is not None
    event = AuditEvent.objects.get(event_type="strain_created")
    assert event.changes["risk_group_basis"] == [None, ACCESSION_BASIS]
    assert event.changes["risk_group_entry"] == [None, None]


@pytest.mark.rule("R-RISK-07")
def test_an_accession_without_a_basis_is_refused(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    with pytest.raises(RuleViolation) as refused:
        accession(curator_access, lab, taxon=exempli, risk_group_basis="   ")
    assert (refused.value.code, refused.value.attr) == ("basis_required", "risk_group_basis")
    assert not Strain.objects.exists()


@pytest.mark.rule("R-RISK-07")
def test_group_1_states_a_reason_too_and_never_follows_from_a_missing_entry(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    """Annex 7 says an agent it does not list is not thereby group 1, so group 1 with no entry
    is recorded with words of its own and refused without them."""
    strain = accession(
        curator_access,
        lab,
        taxon=exempli,
        risk_group=1,
        risk_group_basis=WORDS,
        risk_group_entry=None,
    )
    assert (strain.risk_group, strain.risk_group_basis) == (1, WORDS)
    assert strain.risk_group_entry_id is None


@pytest.mark.rule("R-RISK-07")
def test_the_database_asks_every_new_strain_what_its_group_rests_on(
    make_strain: MakeStrain, lab: Lab
) -> None:
    template = make_strain()
    with guarded("states what its risk group rests on"), transaction.atomic():
        raw_strain(lab, template, risk_group_basis="", risk_group_set_at=None)
    with guarded("states what its risk group rests on"), transaction.atomic():
        raw_strain(lab, template, risk_group_basis="   ", risk_group_set_at=None)
    with guarded("states what its risk group rests on"), transaction.atomic():
        raw_strain(lab, template, risk_group_basis=WORDS, risk_group_set_at=None)
    assert raw_strain(lab, template).risk_group_basis == ACCESSION_BASIS


# The basis may name an entry of annex 7, and then the right one (R-RISK-09).


@pytest.mark.rule("R-RISK-09")
def test_an_accession_may_rest_on_an_entry_of_the_annex(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    entry = an_entry(2)
    strain = accession(
        curator_access,
        lab,
        taxon=exempli,
        risk_group=2,
        risk_group_basis=WORDS,
        risk_group_entry=entry,
    )
    assert strain.risk_group_entry_id == entry.pk
    event = AuditEvent.objects.get(event_type="strain_created")
    assert event.changes["risk_group_entry"] == [None, entry.code]


@pytest.mark.rule("R-RISK-09")
def test_an_entry_that_states_another_group_is_refused(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    entry = an_entry(2)
    with pytest.raises(services.RiskGroupEntryMismatch) as refused:
        accession(
            curator_access,
            lab,
            taxon=exempli,
            risk_group=1,
            risk_group_basis=WORDS,
            risk_group_entry=entry,
        )
    assert refused.value.attr == "risk_group_basis_entry"
    assert not Strain.objects.exists()


@pytest.mark.rule("R-RISK-09")
def test_an_entry_of_another_list_is_refused(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    with pytest.raises(services.RiskGroupEntryMismatch):
        accession(
            curator_access,
            lab,
            taxon=exempli,
            risk_group=1,
            risk_group_basis=WORDS,
            risk_group_entry=another_list_entry(),
        )
    assert not Strain.objects.exists()


@pytest.mark.rule("R-RISK-09")
def test_an_entry_of_a_reading_that_was_replaced_is_refused(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    entry = an_entry(2)
    RegulatoryList.objects.filter(pk=entry.list_id).update(is_current=False)
    entry.refresh_from_db()
    entry.list.refresh_from_db()
    with pytest.raises(services.RiskGroupEntryMismatch):
        accession(
            curator_access,
            lab,
            taxon=exempli,
            risk_group=2,
            risk_group_basis=WORDS,
            risk_group_entry=entry,
        )


@pytest.mark.rule("R-RISK-09")
def test_a_raise_may_name_an_entry_and_the_event_holds_its_code(
    make_strain: MakeStrain, curator_access: Access, as_curator: AuditContext
) -> None:
    strain = make_strain()
    entry = an_entry(2)
    services.strain_set_risk_group(
        access=curator_access,
        strain=strain,
        risk_group=2,
        basis=WORDS,
        basis_entry=entry,
        reason="Read in the annex.",
    )
    strain.refresh_from_db()
    assert (strain.risk_group, strain.risk_group_entry_id) == (2, entry.pk)
    event = AuditEvent.objects.get(event_type="strain_risk_group_changed")
    assert event.changes["basis_entry"] == [None, entry.code]


@pytest.mark.rule("R-RISK-09")
def test_a_raise_on_an_entry_of_another_group_is_refused(
    make_strain: MakeStrain, curator_access: Access, as_curator: AuditContext
) -> None:
    strain = make_strain()
    with pytest.raises(services.RiskGroupEntryMismatch) as refused:
        services.strain_set_risk_group(
            access=curator_access,
            strain=strain,
            risk_group=2,
            basis=WORDS,
            basis_entry=an_entry(3),
            reason="Read in the annex.",
        )
    assert refused.value.attr == "basis_entry"
    strain.refresh_from_db()
    assert strain.risk_group == 1


@pytest.mark.rule("R-RISK-09")
def test_a_lowering_carries_the_entry_of_the_proposal_it_confirms(
    make_strain: MakeStrain, curator: User, manager: User
) -> None:
    strain = make_strain(risk_group=3)
    entry = an_entry(2)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-propose"):
        proposal = services.strain_risk_group_lower_propose(
            access=access_for(curator),
            strain=strain,
            risk_group=2,
            basis=WORDS,
            basis_entry=entry,
            reason="Read in the annex.",
        )
    assert proposal.basis_entry_id == entry.pk
    with audit_context(channel=Channel.API, actor=manager, request_id="req-confirm"):
        lowered = services.strain_risk_group_lower_confirm(
            access=access_for(manager), strain=strain, proposal=proposal.public_id
        )
    assert (lowered.risk_group, lowered.risk_group_entry_id) == (2, entry.pk)


@pytest.mark.rule("R-RISK-09")
def test_a_proposal_on_an_entry_of_another_group_is_refused(
    make_strain: MakeStrain, curator: User
) -> None:
    strain = make_strain(risk_group=3)
    with (
        audit_context(channel=Channel.API, actor=curator, request_id="req-propose"),
        pytest.raises(services.RiskGroupEntryMismatch),
    ):
        services.strain_risk_group_lower_propose(
            access=access_for(curator),
            strain=strain,
            risk_group=2,
            basis=WORDS,
            basis_entry=an_entry(3),
            reason="Read in the annex.",
        )
    assert not RiskGroupProposal.objects.exists()


# The same against the database.


@pytest.mark.rule("R-RISK-09")
def test_the_database_refuses_a_new_strain_on_an_entry_that_does_not_state_its_group(
    make_strain: MakeStrain, lab: Lab
) -> None:
    template = make_strain()
    # The id, not the object: the row copied from the template already carries the column.
    for entry in (an_entry(2), another_list_entry()):
        with guarded("rests on an entry of the current annex 7"), transaction.atomic():
            raw_strain(lab, template, risk_group=1, risk_group_entry_id=entry.pk)
    assert raw_strain(lab, template, risk_group=2, risk_group_entry_id=an_entry(2).pk).pk


@pytest.mark.rule("R-RISK-09")
def test_the_database_refuses_a_change_onto_an_entry_that_does_not_state_the_group(
    make_strain: MakeStrain,
) -> None:
    strain = make_strain()
    with guarded("rests on an entry of the current annex 7"), transaction.atomic():
        Strain.objects.filter(pk=strain.pk).update(
            risk_group=2,
            risk_group_basis=WORDS,
            risk_group_set_at=timezone.now(),
            risk_group_entry=an_entry(3),
        )
    Strain.objects.filter(pk=strain.pk).update(
        risk_group=2,
        risk_group_basis=WORDS,
        risk_group_set_at=timezone.now(),
        risk_group_entry=an_entry(2),
    )
    assert Strain.objects.get(pk=strain.pk).risk_group_entry_id == an_entry(2).pk


@pytest.mark.rule("R-RISK-09")
def test_the_database_lets_the_entry_change_only_with_the_group(make_strain: MakeStrain) -> None:
    strain = make_strain(risk_group=2)
    with guarded("changes with the group"), transaction.atomic():
        Strain.objects.filter(pk=strain.pk).update(risk_group_entry=an_entry(2))


@pytest.mark.rule("R-RISK-09")
def test_the_database_refuses_a_lowering_that_drops_the_entry_of_its_proposal(
    make_strain: MakeStrain, curator: User, manager: User
) -> None:
    """The confirmed proposal is the only way down (R-RISK-06), and the strain must land on the
    entry that proposal named, not on another one or on none."""
    strain = make_strain(risk_group=3)
    entry = an_entry(2)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-propose"):
        proposal = services.strain_risk_group_lower_propose(
            access=access_for(curator),
            strain=strain,
            risk_group=2,
            basis=WORDS,
            basis_entry=entry,
            reason="Read in the annex.",
        )
    now = timezone.now()
    RiskGroupProposal.objects.filter(pk=proposal.pk).update(confirmed_by=manager, confirmed_at=now)
    lowered = {
        "risk_group": 2,
        "risk_group_basis": WORDS,
        "risk_group_set_at": now,
    }
    with guarded("a second person confirms a proposal"), transaction.atomic():
        Strain.objects.filter(pk=strain.pk).update(**lowered, risk_group_entry=None)
    Strain.objects.filter(pk=strain.pk).update(**lowered, risk_group_entry=entry)
    assert Strain.objects.get(pk=strain.pk).risk_group_entry_id == entry.pk


@pytest.mark.rule("R-RISK-09")
def test_the_database_refuses_a_proposal_on_an_entry_that_does_not_state_its_group(
    make_strain: MakeStrain, curator: User
) -> None:
    strain = make_strain(risk_group=3)
    with guarded("rests on an entry of the current annex 7"), transaction.atomic():
        RiskGroupProposal.objects.create(
            lab_id=strain.lab_id,
            strain=strain,
            risk_group=2,
            from_risk_group=3,
            basis=WORDS,
            basis_entry=an_entry(3),
            reason="Read in the annex.",
            proposed_by=curator,
            proposed_at=timezone.now(),
        )


@pytest.mark.rule("R-RISK-09")
def test_the_python_check_and_the_trigger_agree_on_which_entry_states_a_group(
    make_strain: MakeStrain,
) -> None:
    """The one rule, both ways: `states_risk_group` in Python and the SQL function the guards
    call. Remove either and the pairs below disagree."""
    # Every entry is read while the annex is current, then the reading is replaced: all of its
    # entries go with it, so the pairs are built first.
    current, elsewhere, replaced = an_entry(2), another_list_entry(), an_entry(3)
    cases = [
        (current, 2),
        (current, 1),
        (current, 3),
        (elsewhere, 1),
        (replaced, 3),
    ]
    RegulatoryList.objects.filter(pk=replaced.list_id).update(is_current=False)
    for entry, _ in cases:
        entry.refresh_from_db()
        entry.list.refresh_from_db()
    with connection.cursor() as cursor:
        for entry, group in cases:
            cursor.execute(
                "SELECT strains_risk_group_entry_states(%s, %s, %s::smallint)",
                ["public", entry.pk, group],
            )
            (in_sql,) = cursor.fetchone()
            assert in_sql == states_risk_group(entry, group), (entry.code, group)
        cursor.execute("SELECT strains_risk_group_entry_states(%s, NULL, 1::smallint)", ["public"])
        assert cursor.fetchone()[0] is True  # no entry named, nothing to ask of the lists


# Through the API.


@pytest.mark.rule("R-RISK-09")
def test_the_api_takes_the_entry_by_public_id_and_refuses_one_of_another_list(
    make_strain: MakeStrain, curator: User
) -> None:
    strain = make_strain()
    url = f"{STRAINS_URL}{strain.public_id}/risk-group/"
    entry = an_entry(2)
    answer = logged_in(curator).post(
        url,
        {"risk_group": 2, "basis": WORDS, "basis_entry": str(entry.public_id), "reason": "Read."},
        content_type="application/json",
    )
    assert answer.status_code == 200, answer.content
    assert answer.json()["risk_group_entry"] == entry.code
    assert_problem(
        logged_in(curator).post(
            url,
            {
                "risk_group": 3,
                "basis": WORDS,
                "basis_entry": str(another_list_entry().public_id),
                "reason": "Read.",
            },
            content_type="application/json",
        ),
        400,
        "invalid",
        attr="basis_entry",
    )


@pytest.mark.rule("R-RISK-07")
def test_the_strain_page_shows_the_basis_and_the_entry_of_its_group(
    make_strain: MakeStrain, viewer: User
) -> None:
    strain = make_strain()
    body = logged_in(viewer).get(f"{STRAINS_URL}{strain.public_id}/").json()
    assert body["risk_group_basis"] == ACCESSION_BASIS
    assert body["risk_group_entry"] is None
