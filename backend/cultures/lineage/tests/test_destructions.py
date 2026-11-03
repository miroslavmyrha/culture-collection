"""The destruction record (#160): what it asks per restriction kind and for a strain without one,
the two-person rule for a regulated strain, the vials it takes and leaves destroyed, being
entered in error, its events and its API. The triggers that hold the same are in
test_destruction_guards.py."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from cultures.audit.context import MissingAuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.models import AuthorisationKind, DestructionMethod, RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.core.testing import QueryBaseline, Write, assert_problem, logged_in
from cultures.core.testing.contract import ViewsetContract
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.lineage import services
from cultures.lineage.api.views import DestructionViewSet
from cultures.lineage.models import (
    DestructionRecord,
    DestructionStatus,
    Passage,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.storage.tests.conftest import Tree
from cultures.strains import services as strains
from cultures.strains.models import DeaccessionCause, Strain
from cultures.strains.services import RestrictionInput
from cultures.strains.tests.conftest import (
    DUAL_USE,
    GMO,
    QUARANTINE,
    VRAT,
    make_permit,
)
from cultures.users.models import User

from .support import (
    DESTRUCTIONS_URL,
    VERIFIED,
    MakeBatch,
    destroy,
    mark_to_destroy,
    new_destruction,
    snapshot,
    vials_of,
)
from .test_contract import Readers

pytestmark = pytest.mark.django_db

RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1")
RESTRICTIONS: dict[RestrictionKind, RestrictionInput] = {
    RestrictionKind.CZ_VRAT: VRAT,
    RestrictionKind.CZ_RAT: RAT,
    RestrictionKind.DUAL_USE: DUAL_USE,
    RestrictionKind.QUARANTINE_PEST: QUARANTINE,
    RestrictionKind.GMO: GMO,
}
# Every kind and none: "none" is a strain without an active restriction.
KINDS = ["none", *RestrictionKind.values]


def restrict(strain: Strain, curator: User, kind: str) -> None:
    """The lab's permits for VRAT and quarantine pests (the quarantine one declares autoclaving),
    then the strain's restriction of the kind, through the service."""
    make_permit(strain.lab, AuthorisationKind.CZ_VRAT)
    make_permit(strain.lab, AuthorisationKind.QUARANTINE_PEST)
    if kind == "none":
        return
    with audit_context(channel=Channel.API, actor=curator, request_id="req-restrict"):
        strains.strain_restriction_add(
            access=access_for(curator),
            strain=strain,
            restriction=RESTRICTIONS[RestrictionKind(kind)],
            reason="listed",
        )


def marked(
    make_batch: MakeBatch, passage: Passage, technician: User, count: int = 2, **batch: Any
) -> list[Vial]:
    """A new batch of the passage's strain, every vial marked to destroy by the technician."""
    return mark_to_destroy(technician, vials_of(make_batch(passage, vial_count=count, **batch)))


def refused(error: type[DomainError], code: str, call: Any, attr: str | None = None) -> DomainError:
    """Refused with the code on the field, and nothing written: no row, no event."""
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def record_as(actor: User, vials: list[Vial], **changes: Any) -> DestructionRecord:
    return destroy(actor, vials, **changes)


def confirm_as(actor: User, record: DestructionRecord) -> DestructionRecord:
    with audit_context(channel=Channel.API, actor=actor, request_id="req-confirm"):
        return services.destruction_confirm(access=access_for(actor), record=record)


def in_error_as(actor: User, record: DestructionRecord, reason: str = "Wrong vials.") -> Any:
    with audit_context(channel=Channel.API, actor=actor, request_id="req-error"):
        return services.destruction_enter_in_error(
            access=access_for(actor), record=record, reason=reason
        )


def statuses(vials: list[Vial]) -> set[str]:
    return set(Vial.objects.filter(pk__in=[v.pk for v in vials]).values_list("status", flat=True))


@pytest.fixture
def witness(lab: Lab) -> User:
    """A technician of the lab, present at the destruction."""
    return member_of(lab, Role.TECHNICIAN, "present-member")


@pytest.fixture
def second_manager(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "second-manager")


# A strain without restrictions: one person, destroyed at once.


@pytest.mark.rule("R-END-03", "R-END-05")
def test_a_strain_without_restrictions_is_destroyed_at_once_and_leaves_its_places(
    *, passage0: Passage, make_batch: MakeBatch, technician: User, tree: Tree
) -> None:
    vials = marked(make_batch, passage0, technician, box=tree.box)
    start = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    made = record_as(technician, vials, run="Cycle 2026-118", method_detail="121 °C, 20 min")
    made.refresh_from_db()
    assert made.completed_at == made.recorded_at
    assert (made.confirmed_by, made.status, made.label) == (
        None,
        DestructionStatus.VALID,
        f"{permit_today().year}/1",
    )
    assert statuses(vials) == {VialStatus.DESTROYED}
    assert {v.status_changed_at for v in Vial.objects.filter(pk__in=[v.pk for v in vials])} == {
        made.completed_at
    }
    # The placements closed in the same transaction, with destroyed as the reason.
    placements = VialPlacement.objects.filter(vial__in=vials)
    assert {(p.removed_at, p.removal_reason, p.removed_by_id) for p in placements} == {
        (made.completed_at, "destroyed", technician.pk)
    }
    strain = passage0.strain
    events = list(AuditEvent.objects.filter(pk__gt=start).order_by("pk"))
    assert [e.event_type for e in events] == [
        "destruction_recorded",
        "vial_status_changed",
        "vial_status_changed",
        "vials_destroyed",
    ]
    assert {(e.strain_id, e.lab_id, e.reason) for e in events} == {
        (strain.public_id, strain.lab_id, "Contaminated on every plate.")
    }
    assert events[0].changes == {
        "destruction": [
            None,
            {
                "public_id": str(made.public_id),
                "number": made.label,
                "destroyed_on": permit_today().isoformat(),
                "method": "autoclave",
                "method_detail": "121 °C, 20 min",
                "verification": VERIFIED,
                "outside_firm": False,
                "handover_document": "",
                "inactivated_in_lab": True,
                "run": "Cycle 2026-118",
                "witness": None,
                "authorisation": None,
                "vials": [str(v.public_id) for v in vials],
            },
        ],
        "awaits_confirmation": [None, False],
    }
    first = vials[0]
    placed = VialPlacement.objects.get(vial=first)
    assert events[1].changes == {
        "status": ["to_destroy", "destroyed"],
        "location": [{"box": str(tree.box.public_id), "row": placed.row, "col": placed.col}, None],
        "destruction": [None, str(made.public_id)],
    }
    assert events[-1].changes == {"count": [None, 2]}
    # Numbered per lab and year.
    assert record_as(technician, marked(make_batch, passage0, technician)).number == 2


# The rules per kind, spelled out (decisions Q2, Q4, Q5, Q6 and Q9 of the destruction study), so a
# change of services.destructions.Required fails here too.
NEEDS_CONFIRMATION = {"cz_vrat", "cz_rat", "dual_use", "quarantine_pest", "gmo"}
NEEDS_VERIFICATION = NEEDS_CONFIRMATION
NEEDS_WITNESS = {"cz_vrat"}
INACTIVATED_BEFORE_HANDOVER = {"cz_vrat", "cz_rat"}
DECLARED_METHOD = {"quarantine_pest"}


@pytest.mark.rule("R-END-06", "R-END-08", "R-END-09", "R-END-10")
@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_asks_exactly_its_rules(
    *,
    kind: str,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
    witness: User,
) -> None:
    restrict(strain, curator, kind)
    full = {"witness": witness}
    access = access_for(technician)

    def outcome(**changes: Any) -> str | None:
        """The refusal's code for fresh vials, or None when it was recorded."""
        vials = marked(make_batch, passage0, technician, count=1)
        before = snapshot()
        try:
            with audit_context(channel=Channel.API, actor=technician, request_id="req-try"):
                services.destruction_record(
                    access=access, strain=strain, data=new_destruction(vials, **{**full, **changes})
                )
        except DomainError as error:
            assert snapshot() == before
            return error.code
        return None

    # A method on every record (Q5): input without one is refused for every kind.
    assert outcome(method="") == "invalid"
    assert outcome(verification="") == ("required" if kind in NEEDS_VERIFICATION else None)
    assert outcome(witness=None) == ("required" if kind in NEEDS_WITNESS else None)
    alive = {"contractor": "Firm s.r.o., IČO 12345678", "handover_document": "PP-7"}
    assert outcome(**alive, inactivated_in_lab=False) == (
        "inactivate_before_handover" if kind in INACTIVATED_BEFORE_HANDOVER else None
    )
    assert outcome(method=DestructionMethod.CHEMICAL) == (
        "method_not_authorised" if kind in DECLARED_METHOD else None
    )
    # Destroyed at once, or waiting for a second person (Q2).
    vials = marked(make_batch, passage0, technician, count=1)
    with audit_context(channel=Channel.API, actor=technician, request_id="req-last"):
        made = services.destruction_record(
            access=access, strain=strain, data=new_destruction(vials, **full)
        )
    waits = kind in NEEDS_CONFIRMATION
    assert (made.completed_at is None) == waits
    assert statuses(vials) == {VialStatus.TO_DESTROY if waits else VialStatus.DESTROYED}
    assert services.required_for(strain).confirmation == waits


@pytest.mark.rule("R-END-05")
def test_input_is_checked_before_anything(
    passage0: Passage, make_batch: MakeBatch, technician: User, as_technician: Any
) -> None:
    vials = marked(make_batch, passage0, technician, count=1)
    access = access_for(technician)
    strain = passage0.strain

    def call(**changes: Any) -> Any:
        data = new_destruction(changes.pop("vials", vials), **changes)
        return lambda: services.destruction_record(access=access, strain=strain, data=data)

    tomorrow = permit_today() + timedelta(days=1)
    refused(services.InvalidDestruction, "invalid", call(destroyed_on=tomorrow), "destroyed_on")
    refused(RuleViolation, "reason_required", call(reason="  "), "reason")
    other = DestructionMethod.OTHER
    refused(services.InvalidDestruction, "required", call(method=other), "method_detail")
    refused(
        services.InvalidDestruction,
        "required",
        call(contractor="Firm s.r.o."),
        "handover_document",
    )
    refused(services.InvalidDestruction, "required", call(handover_document="PP-1"), "contractor")
    refused(
        services.InvalidDestruction, "invalid", call(inactivated_in_lab=False), "inactivated_in_lab"
    )
    refused(services.InvalidDestruction, "required", call(vials=[]), "vials")
    refused(services.InvalidDestruction, "duplicate", call(vials=vials * 2), "vials.1")
    refused(services.InvalidDestruction, "max_length", call(run="x" * 101), "run")


@pytest.mark.rule("R-END-05")
def test_the_vials_are_of_the_strain_to_destroy_and_in_no_waiting_record(
    *,
    passage0: Passage,
    regulated: Strain,
    make_batch: MakeBatch,
    technician: User,
    as_technician: Any,
) -> None:
    access = access_for(technician)
    strain = passage0.strain
    held = vials_of(make_batch(passage0, vial_count=1))
    other = marked(make_batch, Passage.objects.get(strain=regulated, number=0), technician, 1)

    def call(vials: list[Vial], on_strain: Strain = strain, **changes: Any) -> Any:
        return lambda: services.destruction_record(
            access=access, strain=on_strain, data=new_destruction(vials, **changes)
        )

    refused(services.VialNotToDestroy, "vial_not_to_destroy", call(held), "vials.0")
    refused(services.InvalidDestruction, "does_not_exist", call(other), "vials.0")
    yesterday = permit_today() - timedelta(days=1)
    mine = marked(make_batch, passage0, technician, count=1)
    refused(
        services.InvalidDestruction, "invalid", call(mine, destroyed_on=yesterday), "destroyed_on"
    )
    # The regulated strain's vial waits in a record: no second record takes it.
    services.destruction_record(access=access, strain=regulated, data=new_destruction(other))
    refused(services.VialInDestruction, "vial_in_destruction", call(other, regulated), "vials.0")


def test_a_viewer_records_nothing_and_a_member_demoted_meanwhile_neither(
    *,
    passage0: Passage,
    make_batch: MakeBatch,
    technician: User,
    viewer: User,
    lab: Lab,
) -> None:
    vials = marked(make_batch, passage0, technician, count=1)
    strain = passage0.strain

    def attempt(actor: User, access: Any) -> Any:
        with audit_context(channel=Channel.API, actor=actor, request_id="req-r"):
            return services.destruction_record(
                access=access, strain=strain, data=new_destruction(vials)
            )

    refused(Forbidden, "permission_denied", lambda: attempt(viewer, access_for(viewer)))
    access = access_for(technician)  # built before the demotion
    Membership.objects.filter(user=technician, lab=lab).update(role=Role.VIEWER)
    refused(Forbidden, "permission_denied", lambda: attempt(technician, access))


def test_every_service_needs_an_audit_context(
    passage0: Passage, make_batch: MakeBatch, technician: User
) -> None:
    vials = marked(make_batch, passage0, technician, count=1)
    with pytest.raises(MissingAuditContext):
        services.destruction_record(
            access=access_for(technician), strain=passage0.strain, data=new_destruction(vials)
        )
    assert statuses(vials) == {VialStatus.TO_DESTROY}


# The two-person rule (ADR 0009, decision Q2).


@pytest.fixture
def waiting_record(
    strain: Strain, passage0: Passage, make_batch: MakeBatch, curator: User, technician: User
) -> DestructionRecord:
    """A RAT's two vials, recorded by the technician: waiting for a manager."""
    restrict(strain, curator, "cz_rat")
    return record_as(technician, marked(make_batch, passage0, technician))


@pytest.mark.rule("R-END-06")
def test_a_manager_other_than_the_recorder_confirms_and_the_vials_go_then(
    waiting_record: DestructionRecord, manager: User, technician: User
) -> None:
    vials = [v.vial for v in waiting_record.vials.all()]
    assert statuses(vials) == {VialStatus.TO_DESTROY}
    start = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    done = confirm_as(manager, waiting_record)
    done.refresh_from_db()
    assert (done.confirmed_by, done.completed_at) == (manager, done.confirmed_at)
    assert statuses(vials) == {VialStatus.DESTROYED}
    events = list(AuditEvent.objects.filter(pk__gt=start).order_by("pk"))
    assert [e.event_type for e in events] == [
        "destruction_confirmed",
        "vial_status_changed",
        "vial_status_changed",
        "vials_destroyed",
    ]
    assert events[0].changes == {
        "destruction": [None, str(done.public_id)],
        "recorded_by": [None, str(technician.public_id)],
        "recorded_at": [None, done.recorded_at.isoformat()],
        "confirmed_by": [None, str(manager.public_id)],
        "confirmed_at": [None, done.confirmed_at.isoformat()],  # type: ignore[union-attr]
    }
    assert {e.actor for e in events} == {manager}
    refused(
        services.DestructionNotAwaiting,
        "destruction_not_awaiting",
        lambda: confirm_as(manager, done),
    )


@pytest.mark.rule("R-END-06")
def test_the_recorder_does_not_confirm_even_as_a_manager(
    *,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
    manager: User,
) -> None:
    restrict(strain, curator, "dual_use")
    made = record_as(manager, marked(make_batch, passage0, technician, count=1))
    refused(
        services.ConfirmOwnDestruction, "confirm_own_destruction", lambda: confirm_as(manager, made)
    )


@pytest.mark.rule("R-END-06")
@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_confirms(
    waiting_record: DestructionRecord, team: dict[Role, User], role: Role
) -> None:
    refused(Forbidden, "permission_denied", lambda: confirm_as(team[role], waiting_record))


@pytest.mark.rule("R-END-06")
def test_a_manager_demoted_since_the_request_began_is_refused(
    waiting_record: DestructionRecord, manager: User, lab: Lab
) -> None:
    access = access_for(manager)  # built while the manager was one
    Membership.objects.filter(user=manager, lab=lab).update(role=Role.CURATOR)
    with audit_context(channel=Channel.API, actor=manager, request_id="req-demoted"):
        refused(
            Forbidden,
            "permission_denied",
            lambda: services.destruction_confirm(access=access, record=waiting_record),
        )


def test_a_record_whose_strain_became_a_vrat_is_outdated(
    waiting_record: DestructionRecord, curator: User, manager: User
) -> None:
    """The RAT became a VRAT after the record: no witness, so it is recorded again."""
    with audit_context(channel=Channel.API, actor=curator, request_id="req-vrat"):
        strains.strain_restriction_add(
            access=access_for(curator), strain=waiting_record.strain, restriction=VRAT, reason="r"
        )
    refused(
        services.DestructionOutdated,
        "destruction_outdated",
        lambda: confirm_as(manager, waiting_record),
    )


# VRAT: the witness and the inactivation before an outside firm (decisions Q2 and Q9).


@pytest.fixture
def vrat_vials(
    strain: Strain, passage0: Passage, make_batch: MakeBatch, curator: User, technician: User
) -> list[Vial]:
    restrict(strain, curator, "cz_vrat")
    return marked(make_batch, passage0, technician, count=1)


def test_a_vrat_names_a_witness_other_than_the_recorder(
    *,
    vrat_vials: list[Vial],
    technician: User,
    viewer: User,
    outsider: User,
    witness: User,
    manager: User,
) -> None:
    def call(**changes: Any) -> Callable[[], DestructionRecord]:
        return lambda: record_as(technician, vrat_vials, **changes)

    refused(services.InvalidDestruction, "required", call(witness=None), "witness")
    refused(services.InvalidDestruction, "witness_is_recorder", call(witness=technician), "witness")
    # Only a member who handles vials: a viewer and an outsider are unknown alike.
    refused(services.InvalidDestruction, "does_not_exist", call(witness=viewer), "witness")
    refused(services.InvalidDestruction, "does_not_exist", call(witness=outsider), "witness")
    made = record_as(technician, vrat_vials, witness=witness)
    assert made.witness == witness
    event = AuditEvent.objects.get(event_type="destruction_recorded")
    assert event.changes["destruction"][1]["witness"] == str(witness.public_id)
    confirm_as(manager, made)
    assert statuses(vrat_vials) == {VialStatus.DESTROYED}


@pytest.mark.rule("R-END-08")
def test_a_vrat_goes_to_a_firm_only_inactivated(
    vrat_vials: list[Vial], technician: User, witness: User
) -> None:
    firm = {"contractor": "Spalovna s.r.o., IČO 12345678", "handover_document": "PP-2026-7"}
    error = refused(
        services.InvalidDestruction,
        "inactivate_before_handover",
        lambda: record_as(
            technician, vrat_vials, witness=witness, inactivated_in_lab=False, **firm
        ),
        "inactivated_in_lab",
    )
    assert "§ 13 h)" in error.detail
    made = record_as(technician, vrat_vials, witness=witness, **firm)
    assert (made.contractor, made.handover_document, made.inactivated_in_lab) == (
        firm["contractor"],
        "PP-2026-7",
        True,
    )
    # The firm's name may be a sole trader's: the event says only that there was one.
    event = AuditEvent.objects.get(event_type="destruction_recorded")
    assert event.changes["destruction"][1]["outside_firm"] is True
    assert "Spalovna" not in str(event.changes)


@pytest.mark.rule("R-END-08")
def test_a_rat_goes_to_a_firm_only_inactivated(
    *,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
    manager: User,
) -> None:
    """The owner's decision of 2026-11-03: SÚJB gives RAT only to persons who notified RAT
    handling (§ 17a), which a waste firm usually has not. No witness is asked of a RAT."""
    restrict(strain, curator, "cz_rat")
    vials = marked(make_batch, passage0, technician, count=1)
    firm = {"contractor": "Spalovna s.r.o., IČO 12345678", "handover_document": "PP-2026-8"}
    error = refused(
        services.InvalidDestruction,
        "inactivate_before_handover",
        lambda: record_as(technician, vials, inactivated_in_lab=False, **firm),
        "inactivated_in_lab",
    )
    assert "§ 17a" in error.detail
    made = record_as(technician, vials, **firm)
    assert (made.witness, made.inactivated_in_lab) == (None, True)
    confirm_as(manager, made)
    assert statuses(vials) == {VialStatus.DESTROYED}


# Quarantine pests: the method the permit declares (decision Q6).


@pytest.mark.rule("R-END-09")
def test_a_quarantine_pest_is_destroyed_by_the_method_its_permit_declares(
    *,
    quarantine_pest: Strain,
    make_batch: MakeBatch,
    technician: User,
    manager: User,
    lab: Lab,
) -> None:
    vials = marked(make_batch, Passage.objects.get(strain=quarantine_pest, number=0), technician)
    permit = lab.authorisations.get(kind=AuthorisationKind.QUARANTINE_PEST)
    error = refused(
        services.InvalidDestruction,
        "method_not_authorised",
        lambda: record_as(technician, vials, method=DestructionMethod.INCINERATION),
        "method",
    )
    assert f"permit {permit.permit_reference} declares autoclaving" in error.detail
    assert "notified to ÚKZÚZ first" in error.detail
    made = record_as(technician, vials)
    assert made.authorisation == permit
    confirm_as(manager, made)
    assert statuses(vials) == {VialStatus.DESTROYED}


@pytest.mark.rule("R-END-09")
def test_a_permit_without_a_declared_method_refuses_and_a_lab_without_one_too(
    quarantine_pest: Strain, make_batch: MakeBatch, technician: User, lab: Lab
) -> None:
    vials = marked(make_batch, Passage.objects.get(strain=quarantine_pest, number=0), technician)
    permit = lab.authorisations.get(kind=AuthorisationKind.QUARANTINE_PEST)
    # Recorded before #160: no method (the service never writes one so; the column allows it).
    type(permit).objects.filter(pk=permit.pk).update(destruction_method="")
    refused(
        services.AuthorisationMethodMissing,
        "authorisation_method_missing",
        lambda: record_as(technician, vials),
    )
    type(permit).objects.filter(pk=permit.pk).update(valid_from=permit_today() + timedelta(days=1))
    refused(
        services.InvalidDestruction,
        "lab_authorisation_required",
        lambda: record_as(technician, vials),
        "destroyed_on",
    )


# Entered in error (decree 474/2002 Sb., § 5(4)).


@pytest.mark.rule("R-END-05")
def test_a_waiting_record_entered_in_error_frees_its_vials_for_a_new_one(
    waiting_record: DestructionRecord, technician: User, manager: User
) -> None:
    vials = [v.vial for v in waiting_record.vials.all()]
    refused(
        RuleViolation,
        "reason_required",
        lambda: in_error_as(technician, waiting_record, " "),
        "reason",
    )
    gone = in_error_as(technician, waiting_record)
    assert (gone.status, gone.error_reason, gone.entered_in_error_by) == (
        DestructionStatus.ENTERED_IN_ERROR,
        "Wrong vials.",
        technician,
    )
    assert statuses(vials) == {VialStatus.TO_DESTROY}
    event = AuditEvent.objects.get(event_type="destruction_entered_in_error")
    assert (event.reason, event.changes) == (
        "Wrong vials.",
        {"destruction": [str(gone.public_id), None], "vials_destroyed": [None, False]},
    )
    refused(
        services.DestructionEnteredInError,
        "destruction_entered_in_error",
        lambda: in_error_as(technician, gone),
    )
    refused(
        services.DestructionNotAwaiting,
        "destruction_not_awaiting",
        lambda: confirm_as(manager, gone),
    )
    again = record_as(technician, vials)
    assert again.number == gone.number + 1


@pytest.mark.rule("R-END-05")
def test_a_confirmed_record_is_entered_in_error_by_a_manager_and_its_vials_stay_destroyed(
    waiting_record: DestructionRecord, technician: User, manager: User, second_manager: User
) -> None:
    done = confirm_as(manager, waiting_record)
    vials = [v.vial for v in done.vials.all()]
    refused(Forbidden, "permission_denied", lambda: in_error_as(technician, done))
    gone = in_error_as(second_manager, done)
    assert gone.status == DestructionStatus.ENTERED_IN_ERROR
    assert statuses(vials) == {VialStatus.DESTROYED}  # the material is gone


def test_a_record_of_a_strain_without_restrictions_is_entered_in_error_by_the_bench(
    passage0: Passage, make_batch: MakeBatch, technician: User
) -> None:
    made = record_as(technician, marked(make_batch, passage0, technician, count=1))
    assert in_error_as(technician, made).status == DestructionStatus.ENTERED_IN_ERROR


# A found vial of a strain whose material was destroyed (#150, decision Q11): the same record.


def test_a_found_vial_of_a_destroyed_regulated_strain_takes_the_same_two_people(
    *,
    regulated: Strain,
    make_batch: MakeBatch,
    technician: User,
    curator: User,
    manager: User,
) -> None:
    passage = Passage.objects.get(strain=regulated, number=0)
    lost, held = vials_of(make_batch(passage, vial_count=2))
    with audit_context(channel=Channel.API, actor=technician, request_id="req-lose"):
        services.vial_transition(
            access=access_for(technician), vial=lost, status=VialStatus.LOST, reason="gone"
        )
    data = strains.Deaccession(DeaccessionCause.CONTAMINATED, "Mixed culture.")
    with audit_context(channel=Channel.API, actor=curator, request_id="req-propose"):
        proposal = strains.strain_deaccession_propose(
            access=access_for(curator), strain=regulated, data=data
        )
    with audit_context(channel=Channel.API, actor=manager, request_id="req-deaccession"):
        strains.strain_deaccession_confirm(
            access=access_for(manager), strain=regulated, proposal=proposal.public_id
        )
    found = mark_to_destroy(technician, [lost])  # lost > to_destroy (EDGES_MATERIAL_DESTROYED)
    made = record_as(technician, [*found, Vial.objects.get(pk=held.pk)])
    assert made.completed_at is None  # a regulated strain waits for its second person
    confirm_as(manager, made)
    assert statuses([lost, held]) == {VialStatus.DESTROYED}


# No personal value in an event (ADR 0005).


def test_no_event_holds_a_name_or_an_address(
    *,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
    witness: User,
    manager: User,
    second_manager: User,
) -> None:
    restrict(strain, curator, "cz_vrat")
    people = (technician, witness, manager, second_manager)
    for person in people:
        type(person).objects.filter(pk=person.pk).update(
            first_name=f"First{person.pk}", last_name=f"Last{person.pk}"
        )
    made = record_as(technician, marked(make_batch, passage0, technician), witness=witness)
    confirm_as(manager, made)
    in_error_as(second_manager, made)
    personal = {
        value
        for person in User.objects.filter(pk__in=[p.pk for p in people])
        for value in (person.username, person.email, person.first_name, person.last_name)
        if value
    }
    events = AuditEvent.objects.filter(
        event_type__in=[
            "destruction_recorded",
            "destruction_confirmed",
            "destruction_entered_in_error",
            "vials_destroyed",
            "vial_status_changed",
        ]
    )
    # Two marked to destroy, the record, the confirmation with its two vials and summary, the
    # entry in error.
    assert events.count() == 8
    for event in events:
        text = f"{event.changes} {event.reason} {event.actor_label}"
        assert not {value for value in personal if value in text}, event.event_type
        assert event.actor_label.startswith("user:")


# The API.


def post(user: User, body: dict[str, Any], path: str = "") -> Any:
    return logged_in(user).post(f"{DESTRUCTIONS_URL}{path}", body, content_type="application/json")


def body_for(strain: Strain, vials: list[Vial], **changes: Any) -> dict[str, Any]:
    return {
        "strain": str(strain.public_id),
        "vials": [str(v.public_id) for v in vials],
        "destroyed_on": permit_today().isoformat(),
        "method": "autoclave",
        "verification": VERIFIED,
        "reason": "Contaminated.",
        **changes,
    }


def test_record_and_confirm_through_the_api(
    *,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
    witness: User,
    manager: User,
    lab: Lab,
    other_lab: Lab,
    outsider: User,
) -> None:
    restrict(strain, curator, "cz_vrat")
    vials = marked(make_batch, passage0, technician)
    member = str(membership(witness, lab).public_id)
    elsewhere = Membership.objects.filter(lab=other_lab).first()
    assert elsewhere is not None
    # A member of another lab is unknown, like a missing one.
    assert_problem(
        post(technician, body_for(strain, vials, witness=str(elsewhere.public_id))),
        400,
        "invalid",
        "witness",
    )
    unknown = {**body_for(strain, vials), "vials": [str(vials[0].public_id), "nope"]}
    assert_problem(post(technician, unknown), 400, "invalid", "vials.1")
    assert_problem(post(technician, body_for(strain, vials)), 400, "required", "witness")
    created = post(technician, body_for(strain, vials, witness=member))
    assert created.status_code == 201, created.json()
    row = created.json()
    assert (row["awaits_confirmation"], row["witness"], row["recorded_by"], row["status"]) == (
        True,
        "present-member",
        "technician",
        "valid",
    )
    assert [v["label"] for v in row["vials"]] == [
        f"{strain.accession_number} / 1 / 1",
        f"{strain.accession_number} / 1 / 2",
    ]
    assert "location" not in str(row)
    confirm = f"{row['public_id']}/confirm/"
    assert_problem(post(curator, {}, confirm), 403, "permission_denied")
    done = post(manager, {}, confirm)
    assert (done.status_code, done.json()["confirmed_by"], done.json()["awaits_confirmation"]) == (
        200,
        "manager",
        False,
    )
    assert_problem(post(manager, {}, confirm), 409, "destruction_not_awaiting")


@pytest.mark.parametrize("records", [1, 5])
def test_the_list_query_count_is_exact_and_flat(
    *,
    records: int,
    passage0: Passage,
    make_batch: MakeBatch,
    technician: User,
    viewer: User,
    query_baseline: QueryBaseline,
) -> None:
    for _ in range(records):
        record_as(technician, marked(make_batch, passage0, technician))
    client = logged_in(viewer)
    strain = str(passage0.strain.public_id)
    # Session, user, memberships, the lab, the count, the page with its strain and people, and
    # the vials of the page's records with their batches.
    with query_baseline("destruction_list"):
        response = client.get(DESTRUCTIONS_URL, {"strain": strain})
    assert response.json()["count"] == records


class TestDestructionContract(Readers, ViewsetContract):
    """Entering a record in error is bench work: a viewer reads it and is refused (403)."""

    viewset = DestructionViewSet
    url = DESTRUCTIONS_URL
    audit_model = AuditEvent
    writes = (
        Write(
            "enter-in-error/", {"reason": "the wrong vials"}, changes=DestructionRecord, status=200
        ),
    )

    @pytest.fixture
    def obj(self, passage0: Passage, make_batch: MakeBatch, technician: User) -> DestructionRecord:
        return record_as(technician, marked(make_batch, passage0, technician, count=1))


class TestDestructionConfirmContract(Readers, ViewsetContract):
    """Confirming is a manager's: a curator reads the record and is refused (403)."""

    viewset = DestructionViewSet
    url = DESTRUCTIONS_URL
    audit_model = AuditEvent
    writes = (Write("confirm/", {}, changes=DestructionRecord, status=200),)

    def audit_rows(self) -> int:
        """The confirmation's own event: its vials record theirs beside it."""
        return AuditEvent.objects.filter(event_type="destruction_confirmed").count()

    @pytest.fixture
    def obj(self, waiting_record: DestructionRecord) -> DestructionRecord:
        return waiting_record

    @pytest.fixture
    def reader(self, curator: User) -> User:
        return curator

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager
