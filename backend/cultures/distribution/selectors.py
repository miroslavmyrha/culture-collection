"""Reads of distribution. Every one takes the access object, so the lab scope is in the signature.

Requests are read with distribution.view (viewers and up): what is asked for, what was decided,
which vials are reserved (labels, never a place: ADR 0009). Requesters, their permits, the
signers of MTAs and every document reach a person, so they need distribution.view_requesters
(curators and up), as deposits do.
"""

import re

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet, Sum

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains.selectors import regulating_restrictions

from .models import (
    DistributionRequest,
    Document,
    LinePermit,
    MtaAcceptance,
    RecipientPermit,
    Requester,
    RequestLine,
    ShipmentDocument,
    ShipmentPreparation,
    ShipmentVial,
    VialReservation,
)

# "2026/7" or "7": a year of the request counter and a number within it.
REQUEST_NUMBER = re.compile(r"(?:(?P<year>\d{1,4})/)?(?P<number>\d{1,9})")


def requester_list(*, access: Access, lab: Lab) -> QuerySet[Requester]:
    """By institution; with their permits, ended ones last."""
    return (
        Requester.objects.for_access(access, Perm.VIEW_REQUESTERS)
        .filter(lab=lab)
        .select_related("contact")
        .prefetch_related(
            Prefetch(
                "permits",
                queryset=RecipientPermit.objects.select_related("document").order_by(
                    "ended_on", "kind", "valid_from", "pk"
                ),
                to_attr="permit_list",
            )
        )
        .order_by("institution", "pk")
    )


def requester_matching(requesters: QuerySet[Requester], text: str) -> QuerySet[Requester]:
    text = " ".join(text.split())
    if not text:
        return requesters
    return requesters.filter(Q(institution__icontains=text) | Q(contact__name__icontains=text))


def permit_list(*, access: Access, lab: Lab) -> QuerySet[RecipientPermit]:
    return (
        RecipientPermit.objects.for_access(access, Perm.VIEW_REQUESTERS)
        .filter(lab=lab)
        .select_related("document", "requester")
        .order_by("requester_id", "ended_on", "kind", "valid_from", "pk")
    )


def document_list(*, access: Access, lab: Lab) -> QuerySet[Document]:
    """The documents of the lab, without their content: the view reads it for one."""
    return Document.objects.for_access(access, Perm.VIEW_REQUESTERS).filter(lab=lab).order_by("pk")


def shipment_document_list(*, access: Access, lab: Lab) -> QuerySet[ShipmentDocument]:
    """The documents of the lab's shipments, with their text: they name the responsible person,
    so they need distribution.view_requesters like every document (#90). A request's detail
    lists them without the text for every reader."""
    return (
        ShipmentDocument.objects.for_access(access, Perm.VIEW_REQUESTERS)
        .filter(lab=lab)
        .select_related("shipment__request", "line__strain")
        .order_by("pk")
    )


def regulated_line() -> Exists:
    """A line of the request is of a regulated strain: a manager approves it (ADR 0009). The
    request list shows it, and Home (#69) flags the request by it."""
    return Exists(
        regulating_restrictions().filter(strain__request_lines__request_id=OuterRef("pk"))
    )


def request_list(*, access: Access, lab: Lab) -> QuerySet[DistributionRequest]:
    """Newest first, each with its requester, how many strains and vials it asks for and
    whether a line is of a regulated strain."""
    return (
        DistributionRequest.objects.for_access(access, Perm.VIEW_DISTRIBUTION)
        .filter(lab=lab)
        .select_related("requester")
        .annotate(
            line_count=Count("lines", distinct=True),
            vial_count=Sum("lines__quantity"),
            regulated=regulated_line(),
        )
        .order_by("-year", "-number", "-pk")
    )


def request_matching(
    requests: QuerySet[DistributionRequest], text: str
) -> QuerySet[DistributionRequest]:
    """The number ("2026/7" or "7"), the institution, or a strain's accession number."""
    text = " ".join(text.split())
    if not text:
        return requests
    match = Q(requester__institution__icontains=text) | Q(
        lines__strain__accession_number__icontains=text
    )
    number = request_number(text)
    if number is not None:
        match |= number
    return requests.filter(pk__in=requests.filter(match).values("pk"))


def request_number(text: str) -> Q | None:
    """A request's number as people write it, "2026/7" or "7", or None for other text. The
    request list and the top bar's search (#76) read it the same way."""
    found = REQUEST_NUMBER.fullmatch("".join(text.split()))
    if found is None:
        return None
    by_number = Q(number=int(found["number"]))
    return by_number & Q(year=int(found["year"])) if found["year"] else by_number


def request_detail(*, access: Access, lab: Lab) -> QuerySet[DistributionRequest]:
    """The same rows with their lines (strain, terms and MTA version, open reservations with
    their vials, the vials shipped, the permits approved against), the MTA acceptances, the
    shipment with its responsible person and its documents (#90), and the prepared shipments,
    newest first (#89)."""
    lines: QuerySet[RequestLine] = RequestLine.objects.select_related(
        "strain__taxon", "terms", "mta"
    ).prefetch_related(
        Prefetch(
            "reservations",
            queryset=VialReservation.objects.filter(ended_at__isnull=True)
            .select_related("vial__batch__strain")
            .order_by("vial__batch__number", "vial__seq", "pk"),
            to_attr="open_reservations",
        ),
        Prefetch(
            "permits",
            queryset=LinePermit.objects.select_related("permit").order_by("pk"),
            to_attr="approved_permits",
        ),
        Prefetch(
            "shipped_vials",
            queryset=ShipmentVial.objects.select_related("vial__batch__strain").order_by(
                "vial__batch__number", "vial__seq", "pk"
            ),
            to_attr="shipped_vial_list",
        ),
    )
    return (
        request_list(access=access, lab=lab)
        .select_related(
            "requester__contact",
            "submitted_by",
            "decided_by",
            "cancelled_by",
            "shipment__responsible",
            "shipment__classified_by",
            "shipment__shipped_by",
            "shipment__preparation",
        )
        .prefetch_related(
            Prefetch("lines", queryset=lines.order_by("pk"), to_attr="line_list"),
            Prefetch(
                "acceptances",
                queryset=MtaAcceptance.objects.select_related("mta", "signer").order_by("pk"),
                to_attr="acceptance_list",
            ),
            # The shipment's documents without their text: a viewer sees the list (#90).
            Prefetch(
                "shipment__documents",
                queryset=ShipmentDocument.objects.defer("text")
                .select_related("line__strain")
                .order_by("pk"),
                to_attr="document_list",
            ),
            Prefetch(
                "preparations",
                queryset=ShipmentPreparation.objects.select_related(
                    "responsible", "prepared_by", "withdrawn_by"
                ).order_by("-prepared_at", "-pk"),
                to_attr="preparation_list",
            ),
        )
    )


# Inputs resolve through these (ScopedRelatedField): the same scope as the reads.


def requesters_to_use(access: Access) -> QuerySet[Requester]:
    return Requester.objects.for_access(access, Perm.MANAGE_DISTRIBUTION)
