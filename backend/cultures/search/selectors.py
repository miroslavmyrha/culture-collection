"""The top bar's search (#76): what a person types or scans, found across their labs.

Each kind is read only from the labs where the person holds the permission its own list needs
(KIND_PERM), through `for_access`, and matched the way that list matches, so a result's "all of
them" link opens a list that holds the same rows. A kind the person may read in no lab sends no
query. Each kind is one query: at most LIMIT rows per lab, best first, each with its lab's total.

Where a vial is stored is read only for a strain without active restrictions
(strains.selectors.regulating_restrictions, ADR 0009). A regulated strain's vial says that it
is masked, and names its strain and lab, never a box, for every reader: a holder of the
location grant reveals it on the strain's Material tab, never here. Nothing names a person.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    OrderBy,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Value,
    When,
    Window,
)
from django.db.models.functions import RowNumber

from cultures.deposits.models import Deposit
from cultures.deposits.selectors import deposit_matching
from cultures.distribution.models import DistributionRequest
from cultures.distribution.selectors import request_number
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.lineage.models import Vial, VialPlacement
from cultures.lineage.selectors import box_paths, vials_by_code
from cultures.lineage.services import Location
from cultures.strains.models import Strain
from cultures.strains.selectors import matching, regulating_restrictions

LIMIT = 5  # results per kind; the group's totals say how many match in each lab
SHORTEST = 2  # characters, after spaces are folded: one character finds too much to read
LONGEST = 200


class Kind(StrEnum):
    """In the order the results list them."""

    STRAIN = "strain"
    VIAL = "vial"
    DEPOSIT = "deposit"
    REQUEST = "request"


# Who finds each kind: the permission of the kind's own list, the one source for the scope.
KIND_PERM: dict[Kind, Perm] = {
    Kind.STRAIN: Perm.VIEW_STRAINS,
    Kind.VIAL: Perm.VIEW_STRAINS,
    # Deposits reach their depositors, people: curators and up (ADR 0008, 2026-10-19).
    Kind.DEPOSIT: Perm.VIEW_DEPOSITS,
    Kind.REQUEST: Perm.VIEW_DISTRIBUTION,
}


@dataclass(frozen=True)
class Hit:
    kind: Kind
    public_id: UUID
    lab: Lab
    identifier: str | None  # the number or label, None for a deposit without its strain yet
    title: str
    detail: str
    status: str
    # The text names this one row: an accession number, a vial's barcode or label, a request's
    # number with its year. A scanner's Enter opens an exact hit when it is the only one.
    exact: bool
    strain_id: UUID | None = None  # a vial's strain, an accepted deposit's strain
    location: Location | None = None  # only a placed vial of a strain without restrictions
    location_masked: bool = False  # a placed vial of a regulated strain


@dataclass(frozen=True)
class LabTotal:
    lab: Lab
    total: int


@dataclass(frozen=True)
class Group:
    kind: Kind
    total: int
    labs: list[LabTotal]  # every lab with a match, by code
    hits: list[Hit]  # at most LIMIT, best first


def search(*, access: Access, text: str) -> list[Group]:
    """The groups with a match, in Kind order. Too short a text finds nothing and reads nothing."""
    text = " ".join(text.split())
    if len(text) < SHORTEST:
        return []
    found = [_strains(access, text), _vials(access, text), _deposits(access, text)]
    found.append(_requests(access, text))
    return [group for group in found if group is not None]


def _top(rows: QuerySet[Any], order: Sequence[OrderBy]) -> list[Any]:
    """At most LIMIT rows of each lab, each with `lab_total`, the lab's matches, in `order`
    across the labs. One query: the window runs before the cap."""
    ranked = rows.annotate(
        rank=Window(RowNumber(), partition_by=[F("lab_id")], order_by=list(order)),
        lab_total=Window(Count("pk"), partition_by=[F("lab_id")]),
    )
    return list(ranked.filter(rank__lte=LIMIT).order_by(*order))


def _group(kind: Kind, rows: list[Any], hit: Callable[[Any], Hit]) -> Group | None:
    if not rows:
        return None
    totals: dict[int, LabTotal] = {}
    for row in rows:
        totals.setdefault(row.lab_id, LabTotal(row.lab, vars(row)["lab_total"]))
    labs = sorted(totals.values(), key=lambda entry: entry.lab.code)
    return Group(kind, sum(t.total for t in labs), labs, [hit(row) for row in rows[:LIMIT]])


def _scope[T: Strain | Vial | Deposit | DistributionRequest](
    model: type[T], access: Access, kind: Kind
) -> QuerySet[T] | None:
    perm = KIND_PERM[kind]
    if not access.labs_with(perm):
        return None
    manager: Any = model._default_manager  # each a LabScopedQuerySet manager
    rows: QuerySet[T] = manager.for_access(access, perm)
    return rows


def _rank(*whens: When) -> Case:
    """0 for the best kind of match; the order of the results."""
    return Case(*whens, default=Value(len(whens)), output_field=IntegerField())


def _strains(access: Access, text: str) -> Group | None:
    """By accession number, name as received or taxon name, as the strain list matches: the
    number itself first, then numbers and names that start with the text."""
    scoped = _scope(Strain, access, Kind.STRAIN)
    if scoped is None:
        return None
    rows = (
        matching(scoped, text)
        .select_related("lab", "taxon")
        .annotate(
            relevance=_rank(
                When(accession_number__iexact=text, then=Value(0)),
                When(accession_number__istartswith=text, then=Value(1)),
                When(
                    Q(name_as_received__istartswith=text) | Q(taxon__name__istartswith=text),
                    then=Value(2),
                ),
            )
        )
    )
    order = [
        F("relevance").asc(),
        F("accession_seq").asc(nulls_last=True),
        F("lab__code").asc(),
        F("pk").asc(),
    ]

    def hit(s: Strain) -> Hit:
        name = s.taxon.name
        return Hit(
            Kind.STRAIN,
            s.public_id,
            s.lab,
            s.accession_number,
            name,
            "" if s.name_as_received == name else f"Received as {s.name_as_received}",
            s.status,
            exact=vars(s)["relevance"] == 0,
        )

    return _group(Kind.STRAIN, _top(rows, order), hit)


def _vials(access: Access, text: str) -> Group | None:
    """By barcode, exactly, or by label, the box scan's rule (lineage.selectors.code_match)."""
    scoped = _scope(Vial, access, Kind.VIAL)
    if scoped is None:
        return None
    regulated = Exists(regulating_restrictions().filter(strain_id=OuterRef("batch__strain_id")))
    rows = (
        vials_by_code(scoped, text)
        .select_related("lab", "batch__strain__taxon")
        .annotate(regulated=regulated)
        .prefetch_related(
            Prefetch(
                "placements",
                queryset=VialPlacement.objects.filter(removed_at__isnull=True).select_related(
                    "box"
                ),
                to_attr="open_placements",
            )
        )
    )
    order = [
        F("batch__strain__accession_seq").asc(nulls_last=True),
        F("batch__number").asc(),
        F("seq").asc(),
        F("lab__code").asc(),
        F("pk").asc(),
    ]
    found = _top(rows, order)
    # The paths of the boxes whose place may be shown, one query for all of them: a regulated
    # vial's box is never read past its placement row.
    shown = {
        vial.pk: vars(vial)["open_placements"][0]
        for vial in found
        if not vars(vial)["regulated"] and vars(vial)["open_placements"]
    }
    paths = box_paths(placement.box for placement in shown.values()) if shown else {}

    def hit(v: Vial) -> Hit:
        strain = v.batch.strain
        placement = shown.get(v.pk)
        location = None
        if placement is not None:
            path = paths[placement.box_id]
            location = Location(box=placement.box, path=path, row=placement.row, col=placement.col)
        return Hit(
            Kind.VIAL,
            v.public_id,
            v.lab,
            f"{strain.accession_number} / {v.batch.number} / {v.seq}",
            strain.taxon.name,
            f"Barcode {v.barcode}" if v.barcode else "",
            v.status,
            exact=True,
            strain_id=strain.public_id,
            location=location,
            location_masked=bool(vars(v)["regulated"]) and bool(vars(v)["open_placements"]),
        )

    return _group(Kind.VIAL, found, hit)


def _deposits(access: Access, text: str) -> Group | None:
    """By the name as received, the depositor or the strain's number, as the deposit list
    matches. Never exact: the strain an accepted deposit became is the one thing to open."""
    scoped = _scope(Deposit, access, Kind.DEPOSIT)
    if scoped is None:
        return None
    rows = (
        deposit_matching(scoped, text)
        .select_related("lab", "strain")
        .annotate(
            relevance=_rank(
                When(strain__accession_number__iexact=text, then=Value(0)),
                When(name_as_received__istartswith=text, then=Value(1)),
            )
        )
    )
    order = [
        F("relevance").asc(),
        F("received_on").desc(),
        F("lab__code").asc(),
        F("pk").desc(),
    ]

    def hit(d: Deposit) -> Hit:
        strain = d.strain
        return Hit(
            Kind.DEPOSIT,
            d.public_id,
            d.lab,
            strain.accession_number if strain is not None else None,
            d.name_as_received,
            f"Received {d.received_on.isoformat()}",
            d.status,
            exact=False,
            strain_id=strain.public_id if strain is not None else None,
        )

    return _group(Kind.DEPOSIT, _top(rows, order), hit)


def _requests(access: Access, text: str) -> Group | None:
    """By number, "2026/7", or "7" in every year. Other text finds no request and asks nothing."""
    number = request_number(text)
    scoped = _scope(DistributionRequest, access, Kind.REQUEST)
    if number is None or scoped is None:
        return None
    rows = scoped.filter(number).select_related("lab", "requester")
    order = [F("year").desc(), F("number").asc(), F("lab__code").asc(), F("pk").asc()]
    with_year = "/" in text

    def hit(r: DistributionRequest) -> Hit:
        return Hit(
            Kind.REQUEST,
            r.public_id,
            r.lab,
            r.label,
            r.requester.institution,
            "",
            r.status,
            exact=with_year,
        )

    return _group(Kind.REQUEST, _top(rows, order), hit)
