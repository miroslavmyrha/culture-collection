"""Reads of Home (#69): what waits for the signed-in person, the figures of their labs and what
their roles may do. Every read takes the access object and goes through `for_access` with the
permission the person needs to act on the item there, the same one the page that handles it
checks. So an item appears for exactly the people who may handle it, and in the labs where they
may.

Nothing here reads a location: a vial is named by its label and found on its strain's page,
where the masking of ADR 0009 applies. Nothing names a person either: a requester is an
institution, a permit a reference.

Each kind is one query with a window over it, capped at WAITING_LIMIT rows with the total, so the
number of queries is the same for one row and for a thousand. A kind the person may act on in no
lab sends no query at all.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    Min,
    Model,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
    Window,
)
from django.db.models.functions import Coalesce, RowNumber

from cultures.biosafety.models import LabAuthorisation
from cultures.biosafety.policy import EXPIRES_SOON_DAYS, PERMIT_TIME_ZONE, permit_today
from cultures.deposits.models import Condition, Deposit, DepositStatus
from cultures.distribution.models import (
    DistributionRequest,
    RecipientPermit,
    RequestStatus,
    ShipmentPreparation,
)
from cultures.distribution.selectors import regulated_line
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm, Role
from cultures.lineage.models import (
    PASSING,
    Batch,
    BatchStatus,
    CheckKind,
    DestructionRecord,
    DestructionStatus,
    DestructionVial,
    Vial,
    VialStatus,
)
from cultures.lineage.selectors import latest_result, loss_reports_of_this_loss, reportable_loss
from cultures.storage.selectors import free_positions
from cultures.strains.models import Strain

WAITING_LIMIT = 20  # rows per kind; the group's total says how many wait
# A permit that ends within this many days waits for a manager: the window of the permits screen.
EXPIRY_DAYS = EXPIRES_SOON_DAYS
OPEN_REQUESTS = (
    RequestStatus.SUBMITTED,
    RequestStatus.APPROVED,
    RequestStatus.AWAITING_CONFIRMATION,
)
TO_CHECK = (DepositStatus.RECEIVED, DepositStatus.CHECKING)


class Kind(StrEnum):
    """What waits, in the order Home lists the groups: losses to report to the police first (the
    act asks it without undue delay), then intake, bench, decisions, dispatch, permits,
    destruction and its confirmation."""

    LOSS_TO_REPORT = "loss_to_report"
    DEPOSIT_RECEIVED = "deposit_received"
    DEPOSIT_CHECKING = "deposit_checking"
    BATCH_CHECKS_MISSING = "batch_checks_missing"
    BATCH_TO_RELEASE = "batch_to_release"
    BATCH_ON_HOLD = "batch_on_hold"
    REQUEST_TO_DECIDE = "request_to_decide"
    SHIPMENT_TO_CONFIRM = "shipment_to_confirm"
    REQUEST_TO_SHIP = "request_to_ship"
    RECIPIENT_PERMIT_EXPIRING = "recipient_permit_expiring"
    LAB_PERMIT_EXPIRING = "lab_permit_expiring"
    VIALS_TO_DESTROY = "vials_to_destroy"
    DESTRUCTION_TO_CONFIRM = "destruction_to_confirm"


# Who may act on each kind: the permission the handling page checks. The one source: every query
# below scopes its rows by these, per kind (_scoped), never by a permission of its own.
KIND_PERM: dict[Kind, Perm] = {
    # Act 281/2002 Sb., § 5(5) (#159): the managers answer to the authority, as for a permit.
    Kind.LOSS_TO_REPORT: Perm.APPROVE_REGULATED,
    Kind.DEPOSIT_RECEIVED: Perm.MANAGE_DEPOSITS,
    Kind.DEPOSIT_CHECKING: Perm.MANAGE_DEPOSITS,
    Kind.BATCH_CHECKS_MISSING: Perm.HANDLE_VIALS,
    Kind.BATCH_TO_RELEASE: Perm.RELEASE_BATCHES,
    Kind.BATCH_ON_HOLD: Perm.RELEASE_BATCHES,
    Kind.REQUEST_TO_DECIDE: Perm.MANAGE_DISTRIBUTION,
    Kind.SHIPMENT_TO_CONFIRM: Perm.MANAGE_DISTRIBUTION,
    Kind.REQUEST_TO_SHIP: Perm.MANAGE_DISTRIBUTION,
    # Renewing a permit is the managers' business: they answer to the authority.
    Kind.RECIPIENT_PERMIT_EXPIRING: Perm.APPROVE_REGULATED,
    Kind.LAB_PERMIT_EXPIRING: Perm.APPROVE_REGULATED,
    Kind.VIALS_TO_DESTROY: Perm.MANAGE_STRAINS,
    # #160, ADR 0009: a manager other than the recorder confirms a regulated strain's record.
    Kind.DESTRUCTION_TO_CONFIRM: Perm.CONFIRM_DESTRUCTION,
}


class Target(StrEnum):
    """The page where an item is handled; the SPA builds the URL from it and the ids."""

    DEPOSIT = "deposit"
    STRAIN = "strain"
    REQUEST = "request"
    REQUESTERS = "requesters"
    PERMITS = "permits"


@dataclass(frozen=True)
class Item:
    kind: Kind
    lab_id: int
    subject: str
    reason: str
    since: date  # the Czech day it started to wait
    target: Target
    target_id: UUID | None
    due: date | None = None  # the last valid day of an expiring permit
    needs_manager: bool = False
    # A vial on its strain's Material tab (target STRAIN): the page narrows to it (#159).
    vial_id: UUID | None = None

    def __post_init__(self) -> None:
        if isinstance(self.since, datetime):  # a moment becomes its Czech day
            object.__setattr__(self, "since", self.since.astimezone(PERMIT_TIME_ZONE).date())


@dataclass(frozen=True)
class Group:
    kind: Kind
    total: int
    items: list[Item]


def _capped(rows: QuerySet[Any], *, partition: list[Any], order: list[Any]) -> QuerySet[Any]:
    """At most WAITING_LIMIT rows per partition, each with `total`, the partition's size."""
    ranked: QuerySet[Any] = rows.annotate(
        rank=Window(RowNumber(), partition_by=partition, order_by=order),
        total=Window(Count("pk"), partition_by=partition),
    )
    return ranked.filter(rank__lte=WAITING_LIMIT)


def _scoped[T: Model](model: type[T], access: Access, kinds: Sequence[Kind]) -> QuerySet[T] | None:
    """The rows of the labs where the person may act on any of the kinds, each kind by its own
    permission (KIND_PERM), or None when there is no such lab. A query that tells several kinds
    apart annotates `kind` and filters by _kind_in_its_labs too."""
    if not any(access.labs_with(KIND_PERM[kind]) for kind in kinds):
        return None
    manager: Any = model._default_manager
    rows: QuerySet[T] | None = None
    for kind in kinds:
        scoped: QuerySet[T] = manager.for_access(access, KIND_PERM[kind])
        rows = scoped if rows is None else rows | scoped
    return rows


def _kind_in_its_labs(access: Access, kinds: Sequence[Kind]) -> Q:
    """Each kind only from the labs where the person holds its permission."""
    where = Q(pk__in=[])
    for kind in kinds:
        where |= Q(kind=kind.value, lab__in=access.labs_with(KIND_PERM[kind]))
    return where


def _groups(items: Iterable[tuple[Item, int]]) -> list[Group]:
    by_kind: dict[Kind, list[Item]] = defaultdict(list)
    totals: dict[Kind, int] = {}
    for item, total in items:
        by_kind[item.kind].append(item)
        totals[item.kind] = total
    return [Group(kind, totals[kind], by_kind[kind]) for kind in Kind if kind in by_kind]


DEPOSIT_KINDS = (Kind.DEPOSIT_RECEIVED, Kind.DEPOSIT_CHECKING)


def _deposits(access: Access) -> list[tuple[Item, int]]:
    scoped = _scoped(Deposit, access, DEPOSIT_KINDS)
    if scoped is None:
        return []
    received = Case(
        When(status=DepositStatus.RECEIVED, then=Value(Kind.DEPOSIT_RECEIVED.value)),
        default=Value(Kind.DEPOSIT_CHECKING.value),
        output_field=CharField(),
    )
    rows = _capped(
        scoped.filter(status__in=TO_CHECK)
        .annotate(kind=received)
        .filter(_kind_in_its_labs(access, DEPOSIT_KINDS)),
        partition=[F("kind")],
        order=[F("received_on").asc(), F("pk").asc()],
    )
    items = []
    for d in rows:
        if vars(d)["kind"] == Kind.DEPOSIT_RECEIVED:
            kind, reason = Kind.DEPOSIT_RECEIVED, "Received, not checked yet"
        else:
            kind, reason = Kind.DEPOSIT_CHECKING, "In checking: accept it as a strain or reject it"
        if d.condition != Condition.INTACT:
            reason += f". Arrived: {Condition(d.condition).label.lower()}"
        item = Item(
            kind, d.lab_id, d.name_as_received, reason, d.received_on, Target.DEPOSIT, d.public_id
        )
        items.append((item, vars(d)["total"]))
    return items


BATCH_KINDS = (Kind.BATCH_CHECKS_MISSING, Kind.BATCH_TO_RELEASE, Kind.BATCH_ON_HOLD)


def _batches(access: Access) -> list[tuple[Item, int]]:
    """Pending batches whose latest checks did not all pass wait for the bench (technicians and
    up); those whose checks passed, and batches on hold, wait for a curator's release."""
    scoped = _scoped(Batch, access, BATCH_KINDS)
    if scoped is None:
        return []
    complete = Q(**{f"latest_{kind}__in": PASSING for kind in CheckKind})
    kind = Case(
        When(status=BatchStatus.ON_HOLD, then=Value(Kind.BATCH_ON_HOLD.value)),
        When(complete, then=Value(Kind.BATCH_TO_RELEASE.value)),
        default=Value(Kind.BATCH_CHECKS_MISSING.value),
        output_field=CharField(),
    )
    rows = (
        scoped.filter(status__in=[BatchStatus.PENDING_CHECK, BatchStatus.ON_HOLD])
        .select_related("strain")
        .annotate(**{f"latest_{k}": latest_result(k) for k in CheckKind})
        .annotate(kind=kind)
        .filter(_kind_in_its_labs(access, BATCH_KINDS))
    )
    capped = _capped(
        rows,
        partition=[F("kind")],
        order=[Coalesce("status_changed_at", "created_at").asc(), F("pk").asc()],
    )
    items = []
    for b in capped:
        facts = vars(b)
        subject = f"{_number(b.strain)} batch {b.number}"
        reason, since = _batch_waits_for(b, facts)
        item = Item(
            Kind(facts["kind"]), b.lab_id, subject, reason, since, Target.STRAIN, b.strain.public_id
        )
        items.append((item, facts["total"]))
    return items


def _batch_waits_for(batch: Batch, facts: dict[str, Any]) -> tuple[str, datetime | date]:
    """Why this batch is on the list and since when: its hold reason, that its checks passed and
    it waits for a release, or which passed check it still misses."""
    since: datetime | date = batch.status_changed_at or batch.created_at
    if facts["kind"] == Kind.BATCH_ON_HOLD:
        return _one_line(batch.status_reason) or "On hold", since
    if facts["kind"] == Kind.BATCH_TO_RELEASE:
        return "Identity, purity and viability passed: release it or hold it", since
    missing = [k.label.lower() for k in CheckKind if facts[f"latest_{k}"] not in PASSING]
    return f"No passed {_and(missing)} check yet", since


REQUEST_KINDS = (Kind.REQUEST_TO_DECIDE, Kind.SHIPMENT_TO_CONFIRM, Kind.REQUEST_TO_SHIP)


def _requests(access: Access) -> list[tuple[Item, int]]:
    """Requests to decide and to ship, and prepared shipments for a second person: never for the
    one who approved the request or prepared the shipment (ADR 0009, the service refuses them)."""
    scoped = _scoped(DistributionRequest, access, REQUEST_KINDS)
    if scoped is None:
        return []
    preparation = ShipmentPreparation.objects.filter(
        request=OuterRef("pk"), withdrawn_at__isnull=True
    )
    kind = Case(
        When(status=RequestStatus.SUBMITTED, then=Value(Kind.REQUEST_TO_DECIDE.value)),
        When(status=RequestStatus.APPROVED, then=Value(Kind.REQUEST_TO_SHIP.value)),
        default=Value(Kind.SHIPMENT_TO_CONFIRM.value),
        output_field=CharField(),
    )
    user = access.user.pk
    rows = (
        scoped.filter(status__in=OPEN_REQUESTS)
        .select_related("requester")
        .annotate(
            kind=kind,
            regulated=regulated_line(),
            prepared_by_id=Subquery(preparation.values("prepared_by_id")[:1]),
            prepared_at=Subquery(preparation.values("prepared_at")[:1]),
        )
        .filter(_kind_in_its_labs(access, REQUEST_KINDS))
        .filter(
            ~Q(kind=Kind.SHIPMENT_TO_CONFIRM)
            | (Q(prepared_by_id__isnull=False) & ~Q(prepared_by_id=user) & ~Q(decided_by_id=user))
        )
    )
    capped = _capped(
        rows,
        partition=[F("kind")],
        order=[F("year").asc(), F("number").asc(), F("pk").asc()],
    )
    items = []
    for r in capped:
        facts = vars(r)
        subject = f"Request {r.label}, {r.requester.institution}"
        regulated = bool(facts["regulated"])
        if facts["kind"] == Kind.REQUEST_TO_DECIDE:
            reason = (
                "A regulated strain: a manager approves it"
                if regulated
                else "Entered: approve it or reject it"
            )
            since: datetime = r.created_at
        elif facts["kind"] == Kind.REQUEST_TO_SHIP:
            reason = (
                "Approved: prepare the shipment, a second person confirms it"
                if regulated
                else "Approved: ship the reserved vials"
            )
            since = r.decided_at or r.created_at
        else:
            reason = "Prepared: a second person confirms the shipment"
            since = facts["prepared_at"]
        needs_manager = regulated and facts["kind"] == Kind.REQUEST_TO_DECIDE
        item = Item(
            Kind(facts["kind"]),
            r.lab_id,
            subject,
            reason,
            since,
            Target.REQUEST,
            r.public_id,
            needs_manager=needs_manager,
        )
        items.append((item, facts["total"]))
    return items


def _expiring(access: Access, today: date) -> list[tuple[Item, int]]:
    """Recipient permits and lab permits still in force whose last valid day is within
    EXPIRY_DAYS (Czech days, biosafety.policy.permit_today)."""
    window = Q(
        ended_on__isnull=True,
        expires_on__gte=today,
        expires_on__lte=today + timedelta(days=EXPIRY_DAYS),
    )
    order = [F("expires_on").asc(), F("pk").asc()]
    items: list[tuple[Item, int]] = []
    recipients = _scoped(RecipientPermit, access, [Kind.RECIPIENT_PERMIT_EXPIRING])
    capped = (
        []
        if recipients is None
        else _capped(
            recipients.filter(window).select_related("requester"), partition=[], order=order
        )
    )
    for p in capped:
        item = Item(
            Kind.RECIPIENT_PERMIT_EXPIRING,
            p.lab_id,
            f"{p.reference}, {p.requester.institution}",
            f"{p.get_kind_display()}: ask the requester for the renewal",
            p.created_at,
            Target.REQUESTERS,
            None,
            due=p.expires_on,
        )
        items.append((item, vars(p)["total"]))
    lab_permits = _scoped(LabAuthorisation, access, [Kind.LAB_PERMIT_EXPIRING])
    own = (
        []
        if lab_permits is None
        else _capped(lab_permits.filter(window), partition=[], order=order)
    )
    for a in own:
        item = Item(
            Kind.LAB_PERMIT_EXPIRING,
            a.lab_id,
            f"{a.get_issuer_display()} {a.permit_reference}",
            f"{a.get_kind_display()}: staff record the renewal",
            a.created_at,
            Target.PERMITS,
            None,
            due=a.expires_on,
        )
        items.append((item, vars(a)["total"]))
    return items


def _vials_to_destroy(access: Access) -> list[tuple[Item, int]]:
    """Vials marked to destroy and in no destruction record yet, one item per batch: the label,
    never the place. A vial in a record that waits for its confirmation waits for a manager
    instead (_destructions_to_confirm). PostgreSQL has no window over grouped rows in one level,
    so the groups come back whole (one per batch with such vials, few) and are capped here."""
    scoped = _scoped(Vial, access, [Kind.VIALS_TO_DESTROY])
    if scoped is None:
        return []
    in_a_record = DestructionVial.objects.filter(
        vial=OuterRef("pk"), record__status=DestructionStatus.VALID
    )
    rows = list(
        scoped.filter(status=VialStatus.TO_DESTROY)
        .exclude(Exists(in_a_record))
        .values(
            "lab_id", "batch__number", "batch__strain__public_id", "batch__strain__accession_number"
        )
        .annotate(vials=Count("pk"), since=Min("status_changed_at"))
        .order_by("since", "batch__strain__accession_number", "batch__number")
    )
    items = []
    for row in rows[:WAITING_LIMIT]:
        number = row["batch__strain__accession_number"] or "A strain without a number"
        vials = row["vials"]
        item = Item(
            Kind.VIALS_TO_DESTROY,
            row["lab_id"],
            f"{number} batch {row['batch__number']}",
            f"{vials} vial{'s' if vials != 1 else ''} marked to destroy",
            row["since"],
            Target.STRAIN,
            row["batch__strain__public_id"],
        )
        items.append((item, len(rows)))
    return items


def _destructions_to_confirm(access: Access) -> list[tuple[Item, int]]:
    """Destruction records of regulated strains that wait for a manager's confirmation (#160),
    one item each, the oldest first. The recorder sees their own too: Home says that another
    manager confirms it, and the confirm button says so as well."""
    scoped = _scoped(DestructionRecord, access, [Kind.DESTRUCTION_TO_CONFIRM])
    if scoped is None:
        return []
    rows = _capped(
        scoped.filter(status=DestructionStatus.VALID, completed_at__isnull=True)
        .select_related("strain")
        .annotate(
            vial_count=Subquery(
                DestructionVial.objects.filter(record=OuterRef("pk"))
                .values("record")
                .annotate(n=Count("pk"))
                .values("n")[:1]
            )
        ),
        partition=[],
        order=[F("recorded_at").asc(), F("pk").asc()],
    )
    items = []
    for record in rows:
        count = vars(record)["vial_count"]
        item = Item(
            Kind.DESTRUCTION_TO_CONFIRM,
            record.lab_id,
            f"{_number(record.strain)} destruction {record.label}",
            f"{count} vial{'s' if count != 1 else ''}: a manager other than the recorder confirms",
            record.recorded_at,
            Target.STRAIN,
            record.strain.public_id,
        )
        items.append((item, vars(record)["total"]))
    return items


def _losses_to_report(access: Access) -> list[tuple[Item, int]]:
    """Vials lost while their strain was a VRAT or RAT whose report to the police is not
    recorded (#159, lineage.selectors.reportable_loss), one item each, the oldest loss first: the
    label, never the place. A found vial is not lost and drops out."""
    scoped = _scoped(Vial, access, [Kind.LOSS_TO_REPORT])
    if scoped is None:
        return []
    rows = _capped(
        scoped.filter(reportable_loss())
        .exclude(Exists(loss_reports_of_this_loss()))
        .select_related("batch__strain"),
        partition=[],
        order=[F("status_changed_at").asc(), F("pk").asc()],
    )
    items = []
    for v in rows:
        strain = v.batch.strain
        item = Item(
            Kind.LOSS_TO_REPORT,
            v.lab_id,
            f"{_number(strain)} / {v.batch.number} / {v.seq}",
            "Lost: report it to the police without undue delay (act 281/2002 Sb., § 5(5)),"
            " then record the day and the reference",
            v.status_changed_at,
            Target.STRAIN,
            strain.public_id,
            vial_id=v.public_id,
        )
        items.append((item, vars(v)["total"]))
    return items


def waiting(*, access: Access) -> list[Group]:
    """What waits for the person, by kind, oldest first in each."""
    today = permit_today()
    return _groups(
        [
            *_deposits(access),
            *_batches(access),
            *_requests(access),
            *_expiring(access, today),
            *_vials_to_destroy(access),
            *_destructions_to_confirm(access),
            *_losses_to_report(access),
        ]
    )


# My labs


class Action(StrEnum):
    """What Home offers to start, by role in the lab."""

    RECEIVE_DEPOSIT = "receive_deposit"
    RECORD_CHECK = "record_check"
    FIND_VIAL = "find_vial"
    ENTER_REQUEST = "enter_request"


ACTION_PERM: dict[Action, Perm] = {
    Action.RECEIVE_DEPOSIT: Perm.MANAGE_DEPOSITS,
    Action.RECORD_CHECK: Perm.HANDLE_VIALS,
    # Finding a vial is for taking it out of a box: bench work, like the scan on a box page.
    Action.FIND_VIAL: Perm.HANDLE_VIALS,
    Action.ENTER_REQUEST: Perm.MANAGE_DISTRIBUTION,
}


@dataclass
class LabFigures:
    lab: Lab
    role: Role
    strains: int = 0
    batches: dict[str, int] = field(default_factory=dict)
    vials_available: int = 0
    # Vials by state (#81), only where the person holds VIEW_LAB_FIGURES (managers), else None.
    vials: dict[str, int] | None = None
    free_positions: int = 0
    open_requests: int = 0
    # Only where the person decides on them (curators and up), else None: the lab tabs show them.
    requests_to_decide: int | None = None
    deposits_to_check: int | None = None
    actions: list[Action] = field(default_factory=list)


def _counts(rows: QuerySet[Any], key: str = "lab_id") -> dict[Any, int]:
    return {row[key]: row["n"] for row in rows}


def _vials_by_state(access: Access) -> dict[int, dict[str, int]]:
    """Every state with its count (0 for none) for each lab where the person holds
    VIEW_LAB_FIGURES (#81), one grouped query for all of them. A count is no location: regulated
    vials count like the others (ADR 0009 masks the place, lineage.selectors)."""
    labs = access.labs_with(Perm.VIEW_LAB_FIGURES)
    by_state = {lab_id: dict.fromkeys(VialStatus.values, 0) for lab_id in labs}
    if not by_state:
        return {}
    rows = Vial.objects.for_access(access, Perm.VIEW_LAB_FIGURES).values("lab_id", "status")
    for row in rows.annotate(n=Count("pk")).order_by():
        by_state[row["lab_id"]][row["status"]] = row["n"]
    return by_state


BY_LAB = ("lab_id",)


def _count_material(access: Access, figures: dict[int, LabFigures]) -> None:
    """The strains, the batches by status and the available vials of each lab, one grouped query
    each, as the person may see them."""
    strains = Strain.objects.for_access(access, Perm.VIEW_STRAINS).values(*BY_LAB)
    for lab_id, n in _counts(strains.annotate(n=Count("pk")).order_by()).items():
        figures[lab_id].strains = n
    batches = Batch.objects.for_access(access, Perm.VIEW_STRAINS).values("lab_id", "status")
    for row in batches.annotate(n=Count("pk")).order_by():
        figures[row["lab_id"]].batches[row["status"]] = row["n"]
    vials = Vial.objects.for_access(access, Perm.VIEW_STRAINS).filter(status=VialStatus.AVAILABLE)
    for lab_id, n in _counts(vials.values(*BY_LAB).annotate(n=Count("pk")).order_by()).items():
        figures[lab_id].vials_available = n


def _count_storage(access: Access, figures: dict[int, LabFigures]) -> None:
    """The vials by state, where the person holds VIEW_LAB_FIGURES, and the free positions."""
    for lab_id, states in _vials_by_state(access).items():
        figures[lab_id].vials = states
    for lab_id, n in free_positions(access=access).items():
        figures[lab_id].free_positions = n


def _count_requests(access: Access, figures: dict[int, LabFigures]) -> None:
    """The open requests of each lab, and the ones waiting for a decision where the person
    decides on them (else the figure stays None and the lab's tabs leave it out)."""
    requests = DistributionRequest.objects.for_access(access, Perm.VIEW_DISTRIBUTION)
    deciders = access.labs_with(KIND_PERM[Kind.REQUEST_TO_DECIDE])
    for row in (
        requests.filter(status__in=OPEN_REQUESTS)
        .values("lab_id", "status")
        .annotate(n=Count("pk"))
        .order_by()
    ):
        entry = figures[row["lab_id"]]
        entry.open_requests += row["n"]
        if row["status"] == RequestStatus.SUBMITTED and entry.lab.pk in deciders:
            entry.requests_to_decide = row["n"]
    for lab_id in deciders:
        figures[lab_id].requests_to_decide = figures[lab_id].requests_to_decide or 0


def _count_deposits(access: Access, figures: dict[int, LabFigures]) -> None:
    """The deposits still to check, where the person checks them (else the figure stays None)."""
    checkers = access.labs_with(KIND_PERM[Kind.DEPOSIT_RECEIVED])
    if not checkers:
        return
    deposits = Deposit.objects.for_access(access, KIND_PERM[Kind.DEPOSIT_RECEIVED]).filter(
        status__in=TO_CHECK
    )
    counted = _counts(deposits.values(*BY_LAB).annotate(n=Count("pk")).order_by())
    for lab_id in checkers:
        figures[lab_id].deposits_to_check = counted.get(lab_id, 0)


def _set_actions(access: Access, figures: dict[int, LabFigures]) -> None:
    """The actions the person may start in each lab: the screens show no other."""
    for entry in figures.values():
        entry.actions = [a for a in Action if access.can(ACTION_PERM[a], entry.lab.pk)]


def my_labs(*, access: Access) -> list[LabFigures]:
    """One entry per lab the person is in, by name, with the lab's figures as the person may see
    them. One step per group of figures, one grouped query per figure for all labs together."""
    labs = list(Lab.objects.for_access(access, Perm.VIEW_LAB).order_by("name", "pk"))
    if not labs:
        return []
    figures = {lab.pk: LabFigures(lab, access.roles[lab.pk]) for lab in labs}
    _count_material(access, figures)
    _count_storage(access, figures)
    _count_requests(access, figures)
    _count_deposits(access, figures)
    _set_actions(access, figures)
    return list(figures.values())


def _number(strain: Strain) -> str:
    return strain.accession_number or "A strain without a number"


def _one_line(text: str, limit: int = 120) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _and(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} or {words[-1]}"
