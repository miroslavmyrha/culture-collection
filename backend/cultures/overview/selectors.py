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
    F,
    Min,
    Model,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
    Window,
)
from django.db.models.functions import Coalesce, RowNumber

from cultures.biosafety.models import LabAuthorisation
from cultures.biosafety.policy import PERMIT_TIME_ZONE, permit_today
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
from cultures.lineage.models import PASSING, Batch, BatchStatus, CheckKind, Vial, VialStatus
from cultures.lineage.selectors import latest_result
from cultures.storage.models import StorageUnit, UnitKind
from cultures.strains.models import Strain

WAITING_LIMIT = 20  # rows per kind; the group's total says how many wait
EXPIRY_DAYS = 30  # a permit that ends within this many days waits for a manager
OPEN_REQUESTS = (
    RequestStatus.SUBMITTED,
    RequestStatus.APPROVED,
    RequestStatus.AWAITING_CONFIRMATION,
)
TO_CHECK = (DepositStatus.RECEIVED, DepositStatus.CHECKING)


class Kind(StrEnum):
    """What waits, in the order Home lists the groups: intake, bench, decisions, dispatch,
    permits, destruction."""

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


# Who may act on each kind: the permission the handling page checks. The one source: every query
# below scopes its rows by these, per kind (_scoped), never by a permission of its own.
KIND_PERM: dict[Kind, Perm] = {
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
}


class Target(StrEnum):
    """The page where an item is handled; the SPA builds the URL from it and the ids."""

    DEPOSIT = "deposit"
    STRAIN = "strain"
    REQUEST = "request"
    REQUESTERS = "requesters"
    LAB = "lab"


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
        if facts["kind"] == Kind.BATCH_ON_HOLD:
            reason = _one_line(b.status_reason) or "On hold"
            since: datetime | date = b.status_changed_at or b.created_at
        elif facts["kind"] == Kind.BATCH_TO_RELEASE:
            reason = "Identity, purity and viability passed: release it or hold it"
            since = b.status_changed_at or b.created_at
        else:
            missing = [k.label.lower() for k in CheckKind if facts[f"latest_{k}"] not in PASSING]
            reason = f"No passed {_and(missing)} check yet"
            since = b.status_changed_at or b.created_at
        item = Item(
            Kind(facts["kind"]), b.lab_id, subject, reason, since, Target.STRAIN, b.strain.public_id
        )
        items.append((item, facts["total"]))
    return items


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
            Target.LAB,
            None,
            due=a.expires_on,
        )
        items.append((item, vars(a)["total"]))
    return items


def _vials_to_destroy(access: Access) -> list[tuple[Item, int]]:
    """Vials marked to destroy, one item per batch: the label, never the place. PostgreSQL has no
    window over grouped rows in one level, so the groups come back whole (one per batch with such
    vials, few) and are capped here."""
    scoped = _scoped(Vial, access, [Kind.VIALS_TO_DESTROY])
    if scoped is None:
        return []
    rows = list(
        scoped.filter(status=VialStatus.TO_DESTROY)
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
    free_positions: int = 0
    open_requests: int = 0
    # Only where the person decides on them (curators and up), else None: the lab tabs show them.
    requests_to_decide: int | None = None
    deposits_to_check: int | None = None
    actions: list[Action] = field(default_factory=list)


def _counts(rows: QuerySet[Any], key: str = "lab_id") -> dict[Any, int]:
    return {row[key]: row["n"] for row in rows}


def my_labs(*, access: Access) -> list[LabFigures]:
    """One entry per lab the person is in, by name, with the lab's figures as the person may see
    them. One grouped query per figure for all labs together."""
    labs = list(Lab.objects.for_access(access, Perm.VIEW_LAB).order_by("name", "pk"))
    if not labs:
        return []
    figures = {lab.pk: LabFigures(lab, access.roles[lab.pk]) for lab in labs}
    by_lab = ("lab_id",)
    strains = Strain.objects.for_access(access, Perm.VIEW_STRAINS).values(*by_lab)
    for lab_id, n in _counts(strains.annotate(n=Count("pk")).order_by()).items():
        figures[lab_id].strains = n
    batches = Batch.objects.for_access(access, Perm.VIEW_STRAINS).values("lab_id", "status")
    for row in batches.annotate(n=Count("pk")).order_by():
        figures[row["lab_id"]].batches[row["status"]] = row["n"]
    vials = Vial.objects.for_access(access, Perm.VIEW_STRAINS).filter(status=VialStatus.AVAILABLE)
    for lab_id, n in _counts(vials.values(*by_lab).annotate(n=Count("pk")).order_by()).items():
        figures[lab_id].vials_available = n
    for lab_id, n in _free_positions(access).items():
        figures[lab_id].free_positions = n
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
    checkers = access.labs_with(KIND_PERM[Kind.DEPOSIT_RECEIVED])
    if checkers:
        deposits = Deposit.objects.for_access(access, KIND_PERM[Kind.DEPOSIT_RECEIVED]).filter(
            status__in=TO_CHECK
        )
        counted = _counts(deposits.values(*by_lab).annotate(n=Count("pk")).order_by())
        for lab_id in checkers:
            figures[lab_id].deposits_to_check = counted.get(lab_id, 0)
    for entry in figures.values():
        entry.actions = [a for a in Action if access.can(ACTION_PERM[a], entry.lab.pk)]
    return list(figures.values())


def _free_positions(access: Access) -> dict[int, int]:
    """Free positions in the boxes that may take material now: the box and every unit above it
    active (storage.policy.may_store reads the same path facts). Positions minus open placements."""
    taken = (
        StorageUnit.objects.filter(pk=OuterRef("pk"))
        .annotate(n=Count("placements", filter=Q(placements__removed_at__isnull=True)))
        .values("n")
    )
    boxes = (
        StorageUnit.objects.for_access(access, Perm.VIEW_STORAGE)
        .filter(kind=UnitKind.BOX)
        .with_path_facts()
        .filter(Q(path_active=True))
        .values("lab_id")
        .annotate(n=Sum(F("rows") * F("cols") - Subquery(taken)))
        .order_by()
    )
    return {row["lab_id"]: row["n"] or 0 for row in boxes}


def _number(strain: Strain) -> str:
    return strain.accession_number or "A strain without a number"


def _one_line(text: str, limit: int = 120) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _and(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} or {words[-1]}"
