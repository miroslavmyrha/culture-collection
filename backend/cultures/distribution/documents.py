"""The documents a shipment needs (#90), rendered to plain text from the data as it is when the
shipment is written. Pure: `gather` reads, the render functions only format, and
services._write_documents stores each text once with its SHA-256. A stored document is never
rendered again: reading one returns the text as it was sent.

- The delivery note, for every shipment (s10, section 8, "Shipment"): request, recipient and
  delivery address, the package, and each vial by its label with the strain, risk group and the
  terms and MTA version the line was pinned to. A dual-use line carries the notice Art. 11(9) of
  Regulation (EU) 2021/821 asks for, a quarantine-pest line says that the Letter of Authority
  travels with the package (Regulation (EU) 2019/829, Art. 6(1)).
- The ABS sheet, for each line whose pinned terms are in scope of Regulation (EU) No 511/2014:
  the Art. 4(3) facts held on the terms version and the 20 years of Art. 4(6) (s10, section 5).
- The register entry and handover protocol, for each line of a VRAT or RAT: the data decree
  474/2002 Sb., Annex 3 asks of the sender's register, and a protocol both sides sign, as SÚJB
  asks (s10, section 3). The bound register book stays the legal register.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Prefetch

from cultures.biosafety.models import RestrictionKind
from cultures.deposits.models import AbsScope, Use
from cultures.labs.models import Lab
from cultures.lineage.models import Vial, VialStatus
from cultures.strains.models import StrainRestriction
from cultures.strains.selectors import regulating_restrictions

from .models import (
    Coolant,
    DistributionRequest,
    LinePermit,
    PackingInstruction,
    PermitKind,
    RequestLine,
    Shipment,
    ShipmentDocumentKind,
    ShipmentVial,
    TransportClass,
)

# Regulation (EU) 2021/821, Art. 11(9): "The relevant commercial documents relating to
# intra-Union transfers of dual-use items listed in Annex I shall indicate clearly that those
# items are subject to controls if exported from the customs territory of the Union. Such
# documents include, in particular, any sales contract, order confirmation, invoice or dispatch
# note." (s10, section 2). The notice repeats the regulation's words.
DUAL_USE_NOTICE = (
    "This item is subject to controls if exported from the customs territory of the Union"
    " (Regulation (EU) 2021/821, Art. 11(9))."
)
# Regulation (EU) No 511/2014, Art. 4(6) (s10, section 5).
ABS_RETENTION = (
    "Keep this information for 20 years after the end of the period of utilisation"
    " (Regulation (EU) No 511/2014, Art. 4(6))."
)
# s10, section 3: the sender's entry is a legal duty (act 281/2002 Sb., § 16; decree 474/2002
# Sb., Annex 3), the bound book is the register until SÚJB accepts an electronic one.
REGISTER_NOTE = (
    "These are the data of the entry in the sender's register (act 281/2002 Sb., § 16; decree"
    " 474/2002 Sb., Annex 3). The bound register book stays the legal register: write the entry"
    " there. This page gives its data."
)
HANDOVER_NOTE = (
    "Both sides keep a signed copy of this protocol and record the handover in their registers;"
    " the two entries must agree (SÚJB)."
)
# The vials still in the laboratory: those it holds in any state but gone (used up, destroyed,
# lost, sent away, or never real).
IN_LAB = (
    VialStatus.AVAILABLE,
    VialStatus.RESERVED,
    VialStatus.QUARANTINED,
    VialStatus.TO_DESTROY,
)
REGISTERED = (RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT)
SIGNATURE = "_" * 40


@dataclass(frozen=True)
class Facts:
    """Everything the documents print, read once in the shipping transaction."""

    lab: Lab
    request: DistributionRequest
    shipment: Shipment
    lines: Sequence[RequestLine]
    vials: dict[int, list[str]]  # line pk: the labels of the vials shipped on it
    restrictions: dict[int, list[StrainRestriction]]  # strain pk: its active restrictions
    left: dict[int, int]  # strain pk: its vials still in the lab
    day: date


def gather(request: DistributionRequest, shipment: Shipment, day: date) -> Facts:
    """The facts after the vials left: they are distributed, so `left` counts what stays."""
    lines = list(
        RequestLine.objects.filter(request=request)
        .select_related("strain__taxon", "terms__deposit__depositor", "mta")
        .prefetch_related(
            Prefetch(
                "permits",
                queryset=LinePermit.objects.select_related("permit").order_by("pk"),
                to_attr="approved_permits",
            )
        )
        .order_by("pk")
    )
    strains = [line.strain_id for line in lines]
    accession = {line.pk: line.strain.accession_number for line in lines}
    vials: dict[int, list[str]] = defaultdict(list)
    for row in (
        ShipmentVial.objects.filter(shipment=shipment)
        .select_related("vial__batch")
        .order_by("vial__batch__number", "vial__seq", "pk")
    ):
        # The label the request page shows (serializers.ReservedVialSerializer).
        vial = row.vial
        vials[row.line_id].append(f"{accession[row.line_id]} / {vial.batch.number} / {vial.seq}")
    restrictions: dict[int, list[StrainRestriction]] = defaultdict(list)
    for restriction in regulating_restrictions().filter(strain__in=strains).order_by("kind", "pk"):
        restrictions[restriction.strain_id].append(restriction)
    left = dict(
        Vial.objects.filter(batch__strain__in=strains, status__in=IN_LAB)
        .values_list("batch__strain")
        .annotate(n=Count("pk"))
        .order_by()
    )
    return Facts(
        lab=Lab.objects.get(pk=request.lab_id),
        request=DistributionRequest.objects.select_related("requester__contact").get(pk=request.pk),
        shipment=shipment,
        lines=lines,
        vials=dict(vials),
        restrictions=dict(restrictions),
        left=left,
        day=day,
    )


def needs(facts: Facts) -> list[tuple[ShipmentDocumentKind, RequestLine | None]]:
    """The documents of this shipment: the delivery note, then per line its ABS sheet and its
    register entry where the line needs them."""
    wanted: list[tuple[ShipmentDocumentKind, RequestLine | None]] = [
        (ShipmentDocumentKind.DELIVERY_NOTE, None)
    ]
    for line in facts.lines:
        if line.terms.abs_scope == AbsScope.IN_SCOPE:
            wanted.append((ShipmentDocumentKind.ABS_SHEET, line))
        if any(r.kind in REGISTERED for r in facts.restrictions.get(line.strain_id, [])):
            wanted.append((ShipmentDocumentKind.REGISTER_ENTRY, line))
    return wanted


def render(facts: Facts, kind: ShipmentDocumentKind, line: RequestLine | None) -> str:
    if kind == ShipmentDocumentKind.DELIVERY_NOTE:
        return delivery_note(facts)
    assert line is not None  # noqa: S101 (a per-line kind, the check constraint holds it)
    if kind == ShipmentDocumentKind.ABS_SHEET:
        return abs_sheet(facts, line)
    return register_entry(facts, line)


def _strain(line: RequestLine) -> str:
    return f"{line.strain.accession_number}, {line.strain.taxon.name}"


def _terms(line: RequestLine) -> str:
    mta = f"MTA {line.mta.code} version {line.mta.version}" if line.mta else "no MTA"
    return f"terms version {line.terms.version}, {mta}"


def _indent(text: str, by: str = "  ") -> list[str]:
    return [by + part for part in text.splitlines()] or [by + "(none)"]


def _header(facts: Facts, title: str) -> list[str]:
    return [
        title,
        "",
        f"Shipment: {facts.shipment.public_id}",
        f"Request: {facts.request.label}",
        f"Shipped on: {facts.day.isoformat()}",
        f"Sender: {facts.lab.name} ({facts.lab.code})",
    ]


def _recipient(facts: Facts) -> list[str]:
    requester = facts.request.requester
    return [
        f"Institution: {requester.institution}",
        f"Company number: {requester.registration_number or 'not known'}",
        f"Country: {facts.request.destination_country}",
        "Delivery address:",
        *_indent(requester.contact.postal_address),
    ]


def delivery_note(facts: Facts) -> str:
    s = facts.shipment
    coolant = Coolant(s.coolant).label if s.coolant else "none"
    if s.coolant_kg is not None:
        coolant += f", {s.coolant_kg} kg"
    lines = [
        *_header(facts, "DELIVERY NOTE"),
        "",
        "RECIPIENT",
        *_recipient(facts),
        "",
        "PACKAGE",
        f"Transport class: {TransportClass(s.transport_class).label}",
        f"Packing instruction: {PackingInstruction(s.packing_instruction).label}",
        f"Coolant: {coolant}",
        f"Carrier: {s.carrier}",
        f"Tracking number: {s.tracking_number or 'none'}",
        f"Responsible person: {s.responsible.name}, {s.responsible.phone}",
        "",
        "CONTENTS",
    ]
    for n, line in enumerate(facts.lines, start=1):
        labels = facts.vials.get(line.pk, [])
        lines += [
            "",
            f"{n}. Strain {_strain(line)}",
            f"   Risk group: {line.strain.risk_group}",
            f"   Pinned to: {_terms(line)}",
            f"   Vials ({len(labels)}):",
            *(f"     {label}" for label in labels),
        ]
        for restriction in facts.restrictions.get(line.strain_id, []):
            if restriction.kind == RestrictionKind.DUAL_USE:
                lines += [
                    f"   Dual-use item, Annex I entry {restriction.reference} (read in"
                    f" {restriction.act}). {DUAL_USE_NOTICE}"
                ]
        kinds = {r.kind for r in facts.restrictions.get(line.strain_id, [])}
        if RestrictionKind.QUARANTINE_PEST in kinds:
            letters = [
                f"{p.permit.reference} ({p.permit.issuer})"
                for p in line.approved_permits  # type: ignore[attr-defined]
                if p.permit.kind == PermitKind.PLANT_HEALTH_LOA
            ]
            lines += [
                f"   Union quarantine pest: the Letter of Authority {'; '.join(letters)} travels"
                " with the package (Regulation (EU) 2019/829, Art. 6(1))."
            ]
    return "\n".join(lines) + "\n"


def abs_sheet(facts: Facts, line: RequestLine) -> str:
    terms = line.terms
    depositor = terms.deposit.depositor.institution or "a private depositor"
    uses = ", ".join(Use(use).label for use in terms.mat_uses) or "none"
    if terms.ircc:
        basis = [
            "Art. 4(3)(a): the internationally recognised certificate of compliance and the"
            " content of the mutually agreed terms relevant for subsequent users.",
            f"Certificate (IRCC): {terms.ircc}",
        ]
    else:
        basis = [
            "Art. 4(3)(b): no internationally recognised certificate of compliance is held;"
            " the information and documents below are passed on instead.",
        ]
    lines = [
        *_header(facts, "ABS INFORMATION FOR THE RECIPIENT"),
        f"Recipient: {facts.request.requester.institution}",
        "Regulation (EU) No 511/2014, Art. 4(3)",
        "",
        f"Material: strain {_strain(line)}, {_terms(line)}",
        "",
        *basis,
        f"Date of access (collection date): {terms.collection_date or 'not recorded'}",
        f"Place of access (country of origin): {terms.country_of_origin or 'not recorded'}",
        f"Directly obtained from: {facts.lab.name}, which holds it from {depositor}",
        f"Prior informed consent: {terms.pic_reference or 'not recorded'}",
        f"Access permit: {terms.permit_reference or 'not recorded'}",
        f"Mutually agreed terms: {terms.mat_reference or 'not recorded'}",
        f"Uses by a subsequent user the mutually agreed terms cover: {uses}",
        "",
        ABS_RETENTION,
    ]
    return "\n".join(lines) + "\n"


def register_entry(facts: Facts, line: RequestLine) -> str:
    requester = facts.request.requester
    labels = facts.vials.get(line.pk, [])
    lists = [
        f"{RestrictionKind(r.kind).label}, {r.reference}"
        for r in facts.restrictions.get(line.strain_id, [])
        if r.kind in REGISTERED
    ]
    taxon = line.strain.taxon.name
    lines = [
        *_header(facts, "REGISTER ENTRY AND HANDOVER PROTOCOL"),
        *(f"List: {entry}" for entry in lists),
        "",
        REGISTER_NOTE,
        "",
        "REGISTER ENTRY (ISSUE)",
        f"Date: {facts.day.isoformat()}",
        f"Agent: {taxon} (strain {line.strain.accession_number})",
        f"Quantity issued: {len(labels)} vials",
        f"Vials of the strain left in the laboratory: {facts.left.get(line.strain_id, 0)}",
        f"Recipient: {requester.institution}",
        # The registered office, never the delivery address (that is the laboratory's).
        f"Seat: {requester.seat or 'not known'}",
        f"Company number (IČO): {requester.registration_number or 'not known'}",
        # The number people quote back: the request's, as the request page shows it.
        f"Document number: {facts.request.label}",
        "",
        "HANDOVER PROTOCOL",
        f"On {facts.day.isoformat()} {facts.lab.name} hands over to {requester.institution}"
        f" {len(labels)} vials of {taxon} (strain {line.strain.accession_number}):",
        *(f"  {label}" for label in labels),
        HANDOVER_NOTE,
        "",
        f"Handed over by (name, date, signature): {SIGNATURE}",
        "",
        f"Received by (name, date, signature): {SIGNATURE}",
    ]
    return "\n".join(lines) + "\n"
