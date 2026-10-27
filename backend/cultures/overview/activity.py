"""Recent activity on Home (#69): the latest audit events of the person's labs, one line each.

Who reads which event: an event is shown in a lab only to a person who may read its subject
there, with the permission the subject's own page checks (SHOWN). A deposit event needs
deposits.view like the deposit, a requester's event distribution.view_requesters like the
requester. Events with no lab (users, taxa, box types) are never shown, and every event type the
audit registry holds is either in SHOWN or in HIDDEN with the reason, so a new type needs that
decision (tests/test_activity.py).

What a line says: the type's phrase with the subject's label (an accession number, a batch, a
vial label, a request number), the new status for a status change, and the actor's label as the
audit stores it (`user:<public_id>`, ADR 0005), or "you". It never reads the event's `changes`
beyond that status: a placement event holds the box and position, and a line must not show
where a regulated strain is (ADR 0009). The labels come from the subjects' own rows in the same
lab, in the one query that reads the events.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import (
    Case,
    CharField,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    UUIDField,
    Value,
    When,
)
from django.db.models.functions import Cast, Concat

from cultures.audit.events import BATCH_SUBJECT
from cultures.audit.models import AuditEvent
from cultures.deposits.models import Deposit, MtaTemplate
from cultures.distribution.models import DistributionRequest, MtaAcceptance, RequestLine
from cultures.labs.access import Access
from cultures.labs.permissions import Perm
from cultures.lineage.models import Batch, BatchCheck, BatchStatus, Vial, VialStatus
from cultures.storage.models import StorageUnit, UnitStatus
from cultures.strains.models import Strain

ACTIVITY_LIMIT = 20


@dataclass(frozen=True)
class Shown:
    perm: Perm  # what the reader needs in the event's lab
    phrase: str  # "{subject}" and "{status}" are filled from the subjects' rows
    subject: str | None  # how the subject is labelled and linked; None: no label, no link


# How a subject is labelled, and the page it links to.
STRAIN, BATCH, VIAL, REQUEST, DEPOSIT, UNIT, MTA, LAB, REQUESTERS = (
    "strain",
    "batch",
    "vial",
    "request",
    "deposit",
    "storage_unit",
    "mta_template",
    "lab",
    "requesters",
)

# Short names for the table below.
V, S, D, R = Perm.VIEW_LAB, Perm.VIEW_STRAINS, Perm.VIEW_DEPOSITS, Perm.VIEW_DISTRIBUTION
RQ = Perm.VIEW_REQUESTERS

SHOWN: dict[str, Shown] = {
    "lab_created": Shown(V, "created the lab", LAB),
    "lab_updated": Shown(V, "changed the lab", LAB),
    "member_added": Shown(Perm.VIEW_MEMBERS, "added a member", LAB),
    "member_role_changed": Shown(Perm.VIEW_MEMBERS, "changed a member's role", LAB),
    "member_removed": Shown(Perm.VIEW_MEMBERS, "removed a member", LAB),
    # The list of who may find regulated agents is kept to the managers (labs.LocationGrantViewSet).
    "location_grant_added": Shown(Perm.MANAGE_MEMBERS, "let a member see regulated locations", LAB),
    "location_grant_revoked": Shown(
        Perm.MANAGE_MEMBERS, "revoked a member's regulated locations", LAB
    ),
    # Lab permits are recorded by staff; a manager answers for them.
    "lab_authorisation_added": Shown(Perm.APPROVE_REGULATED, "recorded a lab permit", LAB),
    "lab_authorisation_ended": Shown(Perm.APPROVE_REGULATED, "ended a lab permit", LAB),
    "strain_created": Shown(S, "accessioned {subject}", STRAIN),
    "strain_reclassified": Shown(S, "identified {subject} anew", STRAIN),
    "strain_risk_group_changed": Shown(S, "changed the risk group of {subject}", STRAIN),
    "strain_restriction_added": Shown(S, "added a restriction to {subject}", STRAIN),
    "strain_restriction_end_proposed": Shown(
        S, "proposed to end a restriction of {subject}", STRAIN
    ),
    "strain_restriction_end_withdrawn": Shown(
        S, "withdrew a proposal to end a restriction of {subject}", STRAIN
    ),
    "strain_restriction_ended": Shown(S, "ended a restriction of {subject}", STRAIN),
    "strain_growth_changed": Shown(S, "changed how {subject} is grown", STRAIN),
    "strain_deaccessioned": Shown(S, "deaccessioned {subject}", STRAIN),
    "strain_deaccession_proposed": Shown(S, "proposed to deaccession {subject}", STRAIN),
    "strain_deaccession_withdrawn": Shown(
        S, "withdrew a proposal to deaccession {subject}", STRAIN
    ),
    "medium_created": Shown(S, "added a growth medium", None),
    "medium_changed": Shown(S, "changed a growth medium", None),
    "medium_retired": Shown(S, "retired a growth medium", None),
    "depositor_created": Shown(D, "added a depositor", None),
    "depositor_changed": Shown(D, "changed a depositor", None),
    "mta_template_published": Shown(D, "published {subject}", MTA),
    "deposit_received": Shown(D, "received {subject}", DEPOSIT),
    "deposit_terms_replaced": Shown(D, "changed the terms of {subject}", DEPOSIT),
    "deposit_check_started": Shown(D, "started checking {subject}", DEPOSIT),
    "deposit_accepted": Shown(D, "accepted {subject}", DEPOSIT),
    "deposit_rejected": Shown(D, "rejected {subject}", DEPOSIT),
    "passage_created": Shown(S, "recorded a passage of {subject}", STRAIN),
    "storage_unit_created": Shown(Perm.VIEW_STORAGE, "added {subject}", UNIT),
    "storage_unit_changed": Shown(Perm.VIEW_STORAGE, "changed {subject}", UNIT),
    "storage_unit_moved": Shown(Perm.VIEW_STORAGE, "moved {subject}", UNIT),
    "storage_unit_status_changed": Shown(Perm.VIEW_STORAGE, "set {subject} to {status}", UNIT),
    "batch_created": Shown(S, "preserved {subject}", BATCH),
    "vial_created": Shown(S, "added vial {subject}", VIAL),
    # A write of many objects is one line: its summary event (audit.events.record_batch).
    "vials_created": Shown(S, "added {count} vials of {subject}", STRAIN),
    # Where it went is in the event, never on the line (ADR 0009).
    "vial_placed": Shown(S, "placed vial {subject}", VIAL),
    "vials_placed": Shown(S, "placed {count} vials of {subject}", STRAIN),
    "vials_marked_for_destruction": Shown(
        S, "marked {count} vials of {subject} for destruction", STRAIN
    ),
    "vial_moved": Shown(S, "moved vial {subject}", VIAL),
    "vial_status_changed": Shown(S, "set vial {subject} to {status}", VIAL),
    "vial_barcode_set": Shown(S, "set the barcode of vial {subject}", VIAL),
    "batch_check_recorded": Shown(S, "recorded a check of {subject}", BATCH),
    "batch_check_entered_in_error": Shown(S, "entered a check of {subject} in error", BATCH),
    "batch_status_changed": Shown(S, "set {subject} to {status}", BATCH),
    "requester_created": Shown(RQ, "added a requester", REQUESTERS),
    "requester_changed": Shown(RQ, "changed a requester", REQUESTERS),
    "recipient_permit_added": Shown(RQ, "recorded a recipient's permit", REQUESTERS),
    "recipient_permit_ended": Shown(RQ, "ended a recipient's permit", REQUESTERS),
    "request_submitted": Shown(R, "entered {subject}", REQUEST),
    "request_line_added": Shown(R, "asked for vials in {subject}", REQUEST),
    # The acceptance names its signer: like the requester, for those who read requesters.
    "mta_acceptance_recorded": Shown(
        RQ, "recorded an acceptance of the MTA for {subject}", REQUEST
    ),
    "request_approved": Shown(R, "approved {subject}", REQUEST),
    "request_line_reserved": Shown(R, "reserved vials for {subject}", REQUEST),
    "request_rejected": Shown(R, "rejected {subject}", REQUEST),
    "request_cancelled": Shown(R, "cancelled {subject}", REQUEST),
    "request_line_released": Shown(R, "released the vials of {subject}", REQUEST),
    "request_shipped": Shown(R, "shipped {subject}", REQUEST),
    "request_line_shipped": Shown(R, "shipped the vials of {subject}", REQUEST),
    "request_shipment_prepared": Shown(R, "prepared the shipment of {subject}", REQUEST),
    "request_shipment_withdrawn": Shown(R, "withdrew the prepared shipment of {subject}", REQUEST),
    # The document's text names the responsible person: opened by those who read requesters.
    "shipment_document_generated": Shown(RQ, "generated a shipment document", None),
}

HIDDEN: dict[str, str] = {
    "user_deactivated": "about a user account, no lab",
    "users_deactivated": "about user accounts, no lab",
    "user_created": "about a user account, no lab",
    "user_changed": "about a user account, no lab",
    "user_activated": "about a user account, no lab",
    "user_staff_changed": "about a user account, no lab",
    "user_superuser_changed": "about a user account, no lab",
    "user_password_changed": "about a user account, no lab",
    "login_account_under_attack": "about a user account, no lab",
    "user_login_limits_cleared": "about a user account, no lab",
    "user_erased": "about a user account, no lab",
    "taxon_created": "global reference data, no lab",
    "taxon_changed": "global reference data, no lab",
    "taxon_identifier_added": "global reference data, no lab",
    "taxon_identifier_removed": "global reference data, no lab",
    "box_type_created": "global reference data, no lab",
    "box_type_changed": "global reference data, no lab",
    "contact_erased": "an erasure is about a person: the line would point at them",
    "vial_location_revealed": (
        "the trail of reveals is read only by those who read the audit trail (ADR 0009), and no"
        " lab role does yet"
    ),
}

# The status a line may show, by event type: an enum value, never free text, mapped to its label.
# The only other value read from `changes` is the count of a summary event, an integer.
STATUS_LABELS: dict[str, dict[str, str]] = {
    "batch_status_changed": dict(BatchStatus.choices),
    "vial_status_changed": dict(VialStatus.choices),
    "storage_unit_status_changed": dict(UnitStatus.choices),
}

FALLBACK = {
    STRAIN: "a strain",
    BATCH: "a batch",
    VIAL: "a vial",
    REQUEST: "a request",
    DEPOSIT: "a deposit",
    UNIT: "a storage unit",
    MTA: "an MTA",
}


@dataclass(frozen=True)
class Line:
    occurred_at: datetime
    lab_public_id: UUID
    lab_code: str
    actor: str  # "you", or the audit's label
    summary: str
    target: str | None  # LAB, STRAIN, ... or None
    target_id: UUID | None


def _of_subject(model: type[Any], subject_type: str, values: str) -> Case:
    """A column of the event's subject row in the same lab, or null for other subject types."""
    row = model.objects.filter(public_id=OuterRef("subject_id"), lab_id=OuterRef("lab_id"))
    return Case(
        When(subject_type=subject_type, then=Subquery(row.values(values)[:1])), default=None
    )


def events(*, access: Access) -> QuerySet[AuditEvent]:
    """The events the person may read, each type in the labs where they hold its permission."""
    scope = Q(pk__in=[])
    for perm in {shown.perm for shown in SHOWN.values()}:
        codes = [code for code, shown in SHOWN.items() if shown.perm == perm]
        labs = access.labs_with(perm)
        if labs:
            scope |= Q(lab_id__in=labs, event_type__in=codes)
    # The events of a write of many objects show as their one summary event.
    one_line = Q(batch_id__isnull=True) | Q(subject_type=BATCH_SUBJECT)
    return AuditEvent.objects.for_access(access, Perm.VIEW_LAB).filter(scope).filter(one_line)


def _with_labels(rows: QuerySet[AuditEvent]) -> QuerySet[AuditEvent]:
    """The events with what their lines need: the labels of their subjects, from the subjects'
    own rows in the event's lab, as subqueries of the one query that reads the events."""
    request_of_line = RequestLine.objects.filter(public_id=OuterRef("subject_id")).values(
        "request__public_id"
    )[:1]
    request_of_acceptance = MtaAcceptance.objects.filter(public_id=OuterRef("subject_id")).values(
        "request__public_id"
    )[:1]
    asked_in = Case(
        When(subject_type="distribution_request", then=F("subject_id")),
        When(subject_type="request_line", then=Subquery(request_of_line)),
        When(subject_type="mta_acceptance", then=Subquery(request_of_acceptance)),
        default=None,
        output_field=UUIDField(),
    )
    request = DistributionRequest.objects.filter(
        public_id=OuterRef("asked_in"), lab_id=OuterRef("lab_id")
    )
    request_label = request.annotate(
        text=Concat(
            Cast("year", CharField()),
            Value("/"),
            Cast("number", CharField()),
            output_field=CharField(),
        )
    ).values("text")[:1]
    strain = Strain.objects.filter(public_id=OuterRef("strain_id"), lab_id=OuterRef("lab_id"))
    batch_number = Case(
        When(
            subject_type="batch",
            then=Subquery(
                Batch.objects.filter(public_id=OuterRef("subject_id")).values("number")[:1]
            ),
        ),
        When(
            subject_type="vial",
            then=Subquery(
                Vial.objects.filter(public_id=OuterRef("subject_id")).values("batch__number")[:1]
            ),
        ),
        When(
            subject_type="check",
            then=Subquery(
                BatchCheck.objects.filter(public_id=OuterRef("subject_id")).values("batch__number")[
                    :1
                ]
            ),
        ),
        default=None,
        output_field=IntegerField(),
    )
    return rows.annotate(
        lab_public_id=F("lab__public_id"),
        lab_code=F("lab__code"),
        asked_in=asked_in,
        request_label=Subquery(request_label),
        strain_number=Subquery(strain.values("accession_number")[:1]),
        batch_number=batch_number,
        vial_seq=_of_subject(Vial, "vial", "seq"),
        deposit_name=_of_subject(Deposit, "deposit", "name_as_received"),
        unit_name=_of_subject(StorageUnit, "storage_unit", "name"),
        mta_code=_of_subject(MtaTemplate, "mta_template", "code"),
        mta_version=_of_subject(MtaTemplate, "mta_template", "version"),
    )


def recent(*, access: Access, limit: int = ACTIVITY_LIMIT) -> list[Line]:
    """The latest events, newest first, with what each line needs, in one query."""
    if not access.roles:
        return []
    rows = _with_labels(events(access=access)).order_by("-occurred_at", "-pk")[:limit]
    return lines(rows, access=access)


def strain_history(*, access: Access, strain: Strain) -> QuerySet[AuditEvent]:
    """Everything that happened to one strain that the person may read, newest first (#19):
    the events whose timeline root is the strain (ADR 0008, D13), under the same rules as the
    activity on Home, so the strain's page never shows an event Home would hide. Ordered for a
    page of it; `lines` turns the page into lines."""
    rows = events(access=access).filter(lab_id=strain.lab_id, strain_id=strain.public_id)
    return _with_labels(rows).order_by("-occurred_at", "-pk")


def lines(rows: Iterable[AuditEvent], *, access: Access) -> list[Line]:
    """Events read by `_with_labels`, as the lines a person reads."""
    return [_line(event, access) for event in rows]


def _label(kind: str | None, facts: dict[str, Any]) -> str | None:
    """The subject as people read it, or None when its row is not there (or not in the lab)."""
    number, batch, seq = facts["strain_number"], facts["batch_number"], facts["vial_seq"]
    labels: dict[str | None, str | None] = {
        STRAIN: number,
        BATCH: f"{number} batch {batch}" if number and batch else None,
        VIAL: f"{number} / {batch} / {seq}" if number and batch and seq else None,
        REQUEST: f"request {facts['request_label']}" if facts["request_label"] else None,
        DEPOSIT: f"deposit {facts['deposit_name']}" if facts["deposit_name"] else None,
        UNIT: facts["unit_name"],
        MTA: f"MTA {facts['mta_code']} version {facts['mta_version']}"
        if facts["mta_code"]
        else None,
    }
    return labels.get(kind)


def _new_value(changes: dict[str, Any], key: str) -> object:
    """The new value of a change stored as [old, new], else None."""
    pair = changes.get(key)
    return pair[-1] if isinstance(pair, list) and pair else None


def _target(
    kind: str | None, event: AuditEvent, facts: dict[str, Any]
) -> tuple[str | None, UUID | None]:
    if kind in (STRAIN, BATCH, VIAL):
        return (STRAIN, event.strain_id) if event.strain_id else (None, None)
    if kind == REQUEST:
        return (REQUEST, facts["asked_in"]) if facts["request_label"] else (None, None)
    if kind in (DEPOSIT, UNIT, MTA):
        return kind, event.subject_id
    if kind in (LAB, REQUESTERS):
        return kind, None
    return None, None


def _line(event: AuditEvent, access: Access) -> Line:
    shown = SHOWN[event.event_type]
    facts = vars(event)
    label = _label(shown.subject, facts)
    labels = STATUS_LABELS.get(event.event_type, {})
    status = labels.get(str(_new_value(event.changes, "status")), "a new status")
    count = _new_value(event.changes, "count")
    summary = shown.phrase.format(
        subject=label or FALLBACK.get(shown.subject or "", "it"),
        status=status.lower(),
        count=count if isinstance(count, int) else "the",
    )
    target, target_id = _target(shown.subject, event, facts)
    actor = "you" if event.actor_id == access.user.pk else event.actor_label
    return Line(
        event.occurred_at,
        facts["lab_public_id"],
        facts["lab_code"],
        actor,
        summary,
        target,
        target_id,
    )
