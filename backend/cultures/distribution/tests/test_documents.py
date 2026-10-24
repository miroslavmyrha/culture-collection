"""The documents a shipment needs (#90): written in the transaction that ships, in one step and at
the confirmation, from the data as it is then; kept as sent. Regulated examples are invented
taxa (Mockia vulgaris) with invented list entries and permits."""

import hashlib
import json
from datetime import date
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.biosafety.models import RestrictionKind
from cultures.deposits.models import AbsScope, Use
from cultures.distribution import documents, services
from cultures.distribution.models import (
    DistributionRequest,
    PermitKind,
    Requester,
    Shipment,
    ShipmentDocument,
    ShipmentDocumentKind,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Vial
from cultures.strains import services as strains
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.services import RestrictionInput
from cultures.strains.tests.conftest import DUAL_USE, QUARANTINE, VRAT, end_restriction
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_taxon
from cultures.users.models import User

from .support import (
    SCIENTIST,
    SEAT,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    confirm,
    delivery_note,
    prepare,
    ship,
    submit,
)
from .test_services import events_since, last_pk

pytestmark = pytest.mark.django_db

K = ShipmentDocumentKind
RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1")
IRCC = "ABSCH-IRCC-XX-000000-1 (invented example)"
RESPONSIBLE = "Jan Odpovědný"


def docs(request: DistributionRequest) -> list[ShipmentDocument]:
    return list(
        ShipmentDocument.objects.filter(shipment__request=request)
        .select_related("line__strain")
        .order_by("pk")
    )


def kinds(request: DistributionRequest) -> list[tuple[str, str | None]]:
    return [(d.kind, d.line.strain.accession_number if d.line else None) for d in docs(request)]


def note(request: DistributionRequest) -> str:
    return ShipmentDocument.objects.get(shipment__request=request, kind=K.DELIVERY_NOTE).text


def in_scope(**changes: Any) -> dict[str, Any]:
    """Terms in scope of 511/2014 whose MAT covers the request's use (support.new_request)."""
    return {
        "abs_scope": AbsScope.IN_SCOPE,
        "country_of_origin": "CZ",
        "collection_date": "2024-05",
        "pic_reference": "PIC/DEV/7 (invented example)",
        "mat_reference": "MAT/DEV/7 (invented example)",
        "ircc": IRCC,
        "mat_uses": [Use.RESEARCH_NONCOMMERCIAL],
        **changes,
    }


@pytest.fixture
def one_step(as_curator: AuditContext, curator: User, lab: Lab, requester: Requester) -> Any:
    """A request for the strains, approved and shipped in one step by the curator."""

    def make(*strains: Strain, quantity: int = 2) -> DistributionRequest:
        request = submit(curator, lab, requester, [(s, quantity) for s in strains])
        accept_mtas(curator, request)
        approve(curator, request)
        return ship(curator, request)

    return make


@pytest.fixture
def two_step(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    approver: User,
    lab: Lab,
    requester: Requester,
) -> Any:
    """A regulated request: approved by the approver with a reason, prepared by the manager,
    confirmed by the curator."""

    def make(*strains: Strain, quantity: int = 1) -> DistributionRequest:
        request = submit(curator, lab, requester, [(s, quantity) for s in strains])
        accept_mtas(curator, request)
        approve(approver, request, "The recipient holds what the lists ask for.")
        prepare(manager, request)
        return confirm(curator, request)

    return make


# What each shipment gets.


def test_a_shipment_in_one_step_gets_its_delivery_note_with_every_vial(
    supply: Supply, one_step: Any, lab: Lab
) -> None:
    strain = supply(vials=6)
    start = last_pk()
    request = one_step(strain)
    shipment = Shipment.objects.get(request=request)
    [document] = docs(request)
    assert (document.kind, document.line) == (K.DELIVERY_NOTE, None)
    assert document.text_sha256 == hashlib.sha256(document.text.encode()).hexdigest()
    labels = [
        f"{strain.accession_number} / {v.batch.number} / {v.seq}"
        for v in Vial.objects.filter(shipment_vial__shipment=shipment)
        .select_related("batch")
        .order_by("batch__number", "seq")
    ]
    assert len(labels) == 2
    text = document.text
    for expected in (
        "DELIVERY NOTE",
        f"Shipment: {shipment.public_id}",
        f"Request: {request.label}",
        f"Sender: {lab.name} ({lab.code})",
        "Institution: Example Institute of Microbiology",
        "Company number: 00000001",
        *(f"  {part}" for part in SCIENTIST.postal_address.splitlines()),
        "Transport class: Not subject to the dangerous goods rules (exempt)",
        "Packing instruction: Basic triple packaging",
        "Carrier: Example Courier (invented example)",
        "Tracking number: EX123456789CZ",
        f"Responsible person: {RESPONSIBLE}, +420 555 000 111",
        f"1. Strain {strain.accession_number}, Testella exempli",
        "   Risk group: 1",
        f"   Pinned to: terms version 1, MTA {request.lines.get().mta.code} version 1",
        "   Vials (2):",
        *(f"     {label}" for label in labels),
    ):
        assert expected in text.splitlines(), expected
    assert "Union" not in text  # no dual-use notice, no Letter of Authority
    [event] = [e for e in events_since(start) if e.event_type == "shipment_document_generated"]
    assert event.subject_id == document.public_id
    assert event.changes == {
        "kind": [None, "delivery_note"],
        "shipment": [None, str(shipment.public_id)],
        "text_sha256": [None, document.text_sha256],
    }
    assert event.strain_id is None  # the note spans the lines


def test_the_confirmation_writes_the_documents_with_the_confirmed_facts(
    supply: Supply, two_step: Any, mockia: Taxon
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE], vials=6)
    request = two_step(strain)
    assert kinds(request) == [(K.DELIVERY_NOTE, None)]
    text = note(request)
    assert f"Responsible person: {RESPONSIBLE}, +420 555 000 111" in text
    assert f"Shipment: {Shipment.objects.get(request=request).public_id}" in text


def test_only_a_dual_use_line_carries_the_notice_of_art_11_9(
    supply: Supply, two_step: Any, mockia: Taxon, exempli: Taxon
) -> None:
    plain = supply(exempli, vials=6)
    dual = supply(mockia, restrictions=[DUAL_USE], vials=6)
    request = two_step(plain, dual)
    text = note(request)
    assert text.count(documents.DUAL_USE_NOTICE) == 1
    blocks = text.split("\n\n")
    [dual_block] = [b for b in blocks if f"Strain {dual.accession_number}," in b]
    [plain_block] = [b for b in blocks if f"Strain {plain.accession_number}," in b]
    assert (
        "   Dual-use item, Annex I entry 1C351.c (read in (EU) 2025/2003)."
        f" {documents.DUAL_USE_NOTICE}"
    ) in dual_block.splitlines()
    assert documents.DUAL_USE_NOTICE not in plain_block


def test_the_dual_use_notice_is_the_sentence_of_the_regulation() -> None:
    """Regulation (EU) 2021/821, Art. 11(9): documents "shall indicate clearly that those items
    are subject to controls if exported from the customs territory of the Union"."""
    assert documents.DUAL_USE_NOTICE == (
        "This item is subject to controls if exported from the customs territory of the Union"
        " (Regulation (EU) 2021/821, Art. 11(9))."
    )


def test_an_ended_dual_use_restriction_prints_no_notice(
    supply: Supply, one_step: Any, curator: User, manager: User, mockia: Taxon
) -> None:
    """Only an active restriction regulates (strains.selectors.regulating_restrictions)."""
    strain = supply(mockia, restrictions=[DUAL_USE], vials=6)
    restriction = StrainRestriction.objects.get(strain=strain)
    end_restriction(
        restriction, proposer=curator, confirmer=manager, reason="Removed from Annex I."
    )
    request = one_step(strain)
    assert documents.DUAL_USE_NOTICE not in note(request)


def test_a_quarantine_pest_line_says_its_letter_of_authority_travels_with_it(
    supply: Supply, two_step: Any, mockia: Taxon, curator: User, requester: Requester
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=6)
    letter = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    request = two_step(strain)
    assert (
        f"   Union quarantine pest: the Letter of Authority {letter.reference} ({letter.issuer})"
        " travels with the package (Regulation (EU) 2019/829, Art. 6(1))."
    ) in note(request).splitlines()
    assert documents.DUAL_USE_NOTICE not in note(request)


def test_an_abs_sheet_only_for_a_line_whose_pinned_terms_are_in_scope(
    supply: Supply, one_step: Any, exempli: Taxon, lab: Lab
) -> None:
    scoped = supply(exempli, vials=6, **in_scope())
    outside = supply(exempli, vials=6)
    request = one_step(scoped, outside)
    assert kinds(request) == [(K.DELIVERY_NOTE, None), (K.ABS_SHEET, scoped.accession_number)]
    sheet = docs(request)[1].text.splitlines()
    for expected in (
        "ABS INFORMATION FOR THE RECIPIENT",
        "Recipient: Example Institute of Microbiology",
        "Art. 4(3)(a): the internationally recognised certificate of compliance and the"
        " content of the mutually agreed terms relevant for subsequent users.",
        f"Certificate (IRCC): {IRCC}",
        "Date of access (collection date): 2024-05",
        "Place of access (country of origin): CZ",
        f"Directly obtained from: {lab.name}, which holds it from Example University",
        "Prior informed consent: PIC/DEV/7 (invented example)",
        "Mutually agreed terms: MAT/DEV/7 (invented example)",
        "Uses by a subsequent user the mutually agreed terms cover: Non-commercial research",
        documents.ABS_RETENTION,
    ):
        assert expected in sheet, expected
    assert "20 years after the end of the period of utilisation" in documents.ABS_RETENTION


def test_an_abs_sheet_without_a_certificate_passes_the_list_under_b(
    supply: Supply, one_step: Any, exempli: Taxon
) -> None:
    strain = supply(exempli, vials=6, **in_scope(ircc="", permit_reference="DEV/AP/3"))
    request = one_step(strain)
    sheet = docs(request)[1].text.splitlines()
    assert "Access permit: DEV/AP/3" in sheet
    assert not any("IRCC" in line for line in sheet)
    assert any(line.startswith("Art. 4(3)(b): no internationally recognised") for line in sheet)


def test_a_register_entry_and_handover_protocol_for_a_vrat_line(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    requester: Requester,
    lab: Lab,
) -> None:
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    request = two_step(strain, quantity=2)
    shipment = Shipment.objects.get(request=request)
    assert kinds(request) == [(K.DELIVERY_NOTE, None), (K.REGISTER_ENTRY, strain.accession_number)]
    left = Vial.objects.filter(batch__strain=strain, status__in=documents.IN_LAB).count()
    assert left == 6 - 2
    entry = docs(request)[1].text.splitlines()
    for expected in (
        "REGISTER ENTRY AND HANDOVER PROTOCOL",
        "List: Highly risky agent (VRAT), decree 474/2002 Sb., Annex 1, Příloha 1, bod 2",
        documents.REGISTER_NOTE,
        f"Date: {shipment.shipped_at.date().isoformat()}",
        f"Agent: Mockia vulgaris (strain {strain.accession_number})",
        "Quantity issued: 2 vials",
        f"Vials of the strain left in the laboratory: {left}",
        "Recipient: Example Institute of Microbiology",
        f"Seat: {SEAT}",
        "Company number (IČO): 00000001",
        f"Document number: {request.label}",
        "HANDOVER PROTOCOL",
        documents.HANDOVER_NOTE,
        f"Handed over by (name, date, signature): {documents.SIGNATURE}",
        f"Received by (name, date, signature): {documents.SIGNATURE}",
    ):
        assert expected in entry, expected
    assert "The bound register book stays the legal register" in documents.REGISTER_NOTE
    events = AuditEvent.objects.filter(
        event_type="shipment_document_generated", subject_id=docs(request)[1].public_id
    )
    assert [e.strain_id for e in events] == [strain.public_id]


def test_every_kind_names_the_request_by_the_number_people_read(
    *, supply: Supply, two_step: Any, mockia: Taxon, curator: User, requester: Requester
) -> None:
    """The number a reader quotes back is the request's label, as the request page shows it:
    the same on each kind, and the register entry's document number is that label."""
    strain = supply(mockia, restrictions=[VRAT], vials=6, **in_scope())
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    request = two_step(strain)
    texts = {d.kind: d.text.splitlines() for d in docs(request)}
    assert set(texts) == {K.DELIVERY_NOTE, K.ABS_SHEET, K.REGISTER_ENTRY}
    assert "/" in request.label
    for kind, lines in texts.items():
        assert f"Request: {request.label}" in lines, kind
        numbers = [line for line in lines if line.startswith("Document number:")]
        expected = [f"Document number: {request.label}"] if kind == K.REGISTER_ENTRY else []
        assert numbers == expected, kind


def test_a_rat_line_gets_a_register_entry_and_a_dual_use_line_none(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    requester: Requester,
) -> None:
    rat = supply(mockia, restrictions=[RAT], vials=6)
    other = make_taxon("Mockia altera", Rank.SPECIES, mockia.parent)
    dual = supply(other, restrictions=[DUAL_USE], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    request = two_step(rat, dual)
    assert kinds(request) == [(K.DELIVERY_NOTE, None), (K.REGISTER_ENTRY, rat.accession_number)]
    assert "List: Risky agent (RAT), decree 474/2002 Sb., Annex 2, Příloha 2, bod 1" in (
        docs(request)[1].text.splitlines()
    )


def test_an_unknown_company_number_is_said(
    supply: Supply, one_step: Any, make_requester: Any, curator: User, lab: Lab
) -> None:
    other = make_requester(institution="Example Company Laboratory", registration_number="")
    strain = supply(vials=6)
    request = submit(curator, lab, other, [(strain, 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    ship(curator, request)
    assert "Company number: not known" in note(request).splitlines()


# Kept as sent.


def test_the_stored_text_stays_after_the_strain_is_renamed_and_its_restriction_ends(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    manager: User,
    requester: Requester,
) -> None:
    """The strain is reclassified (its name changes) and its VRAT listing ends: a new rendering
    would differ, the stored documents do not."""
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    request = two_step(strain)
    before = [(d.public_id, d.text, d.text_sha256) for d in docs(request)]
    renamed = make_taxon("Mockia nova", Rank.SPECIES, mockia.parent)
    access = access_for(curator)
    strains.strain_reclassify(
        access=access,
        strain=strain,
        taxon=renamed,
        identified_on=date(2026, 10, 5),
        method="16S rRNA gene sequence",
        reason="Sequencing placed it in a new species.",
    )
    end_restriction(
        StrainRestriction.objects.get(strain=strain),
        proposer=curator,
        confirmer=manager,
        reason="Removed from Annex 1.",
    )
    assert [(d.public_id, d.text, d.text_sha256) for d in docs(request)] == before
    shipment = Shipment.objects.get(request=request)
    facts = documents.gather(request, shipment, date(2026, 10, 23))
    assert documents.needs(facts) == [(K.DELIVERY_NOTE, None)]  # no VRAT any more
    assert "Mockia nova" in documents.delivery_note(facts)
    assert "Mockia nova" not in before[0][1]


def test_no_event_and_no_row_change_holds_the_text_or_the_person(
    supply: Supply, two_step: Any, mockia: Taxon, curator: User, requester: Requester
) -> None:
    start_event = last_pk()
    start_row = RowChange.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    request = two_step(strain)
    texts = [d.text for d in docs(request)]
    events = json.dumps(
        [[e.changes, e.reason, e.subject_type] for e in events_since(start_event)],
        ensure_ascii=False,
    )
    rows = RowChange.objects.filter(pk__gt=start_row, table_label="distribution.shipmentdocument")
    assert rows.count() == len(texts) == 2
    news = [row.new or {} for row in rows]
    assert {new["text"] for new in news} == {"personal"}
    assert {new["text_sha256"] for new in news} == {
        hashlib.sha256(t.encode()).hexdigest() for t in texts
    }
    everything = events + json.dumps(
        list(RowChange.objects.filter(pk__gt=start_row).values_list("new", flat=True)),
        ensure_ascii=False,
    )
    for secret in (RESPONSIBLE, "Testovací 5", *(t.splitlines()[0] for t in texts)):
        assert secret not in everything, secret


# The guard trigger.


def sql(statement: str, params: list[Any]) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params)


def test_a_document_is_never_changed_or_deleted(supply: Supply, one_step: Any) -> None:
    request = one_step(supply(vials=6))
    [document] = docs(request)
    for statement, params in (
        ("UPDATE distribution_shipmentdocument SET text = 'x' WHERE id = %s", [document.pk]),
        (
            "UPDATE distribution_shipmentdocument SET updated_at = now() WHERE id = %s",
            [document.pk],
        ),
        ("DELETE FROM distribution_shipmentdocument WHERE id = %s", [document.pk]),
    ):
        with pytest.raises(IntegrityError, match="kept as sent"):
            sql(statement, params)
    assert docs(request)[0].text == document.text


def insert(shipment: Shipment, **changes: Any) -> None:
    text = changes.pop("text", "DELIVERY NOTE\n")
    values: dict[str, Any] = {
        "lab_id": shipment.lab_id,
        "shipment": shipment,
        "kind": K.DELIVERY_NOTE,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        **changes,
    }
    with transaction.atomic():
        ShipmentDocument.objects.create(**values)


def test_a_document_whose_sha256_is_not_of_its_text_is_refused(
    supply: Supply, one_step: Any
) -> None:
    shipment = Shipment.objects.get(request=one_step(supply(vials=6)))
    with pytest.raises(IntegrityError, match="not the SHA-256 of the text"):
        insert(shipment, kind=K.DELIVERY_NOTE, text_sha256="0" * 64)


def test_a_document_is_refused_for_a_line_that_does_not_need_it(
    supply: Supply, one_step: Any, exempli: Taxon
) -> None:
    request = one_step(supply(exempli, vials=6))
    shipment = Shipment.objects.get(request=request)
    line = request.lines.get()
    for kind in (K.ABS_SHEET, K.REGISTER_ENTRY):
        with pytest.raises(IntegrityError, match=f"a {kind} is written only for a line"):
            insert(shipment, kind=kind, line=line)


def test_a_document_is_about_a_line_of_its_own_request(
    supply: Supply, one_step: Any, exempli: Taxon
) -> None:
    first = one_step(supply(exempli, vials=6, **in_scope()))
    second = one_step(supply(exempli, vials=6))
    with pytest.raises(IntegrityError, match="a line of its request"):
        insert(Shipment.objects.get(request=second), kind=K.ABS_SHEET, line=first.lines.get())


def test_a_delivery_note_names_no_line_and_a_sheet_names_one(
    supply: Supply, one_step: Any, exempli: Taxon
) -> None:
    request = one_step(supply(exempli, vials=6, **in_scope()))
    shipment = Shipment.objects.get(request=request)
    with pytest.raises(IntegrityError, match="line_iff_per_line"):
        insert(shipment, kind=K.DELIVERY_NOTE, line=request.lines.get())
    with pytest.raises(IntegrityError, match="line_iff_per_line"):
        insert(shipment, kind=K.ABS_SHEET)


def test_a_document_is_written_in_the_lab_of_its_shipment(
    supply: Supply, one_step: Any, other_lab: Lab
) -> None:
    shipment = Shipment.objects.get(request=one_step(supply(vials=6)))
    with pytest.raises(IntegrityError, match="written with its shipment, in its lab"):
        insert(shipment, lab_id=other_lab.pk, text="ANOTHER NOTE\n")


def test_at_commit_a_shipment_without_its_documents_is_refused(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    requester: Requester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service is bypassed: a shipment with only a delivery note, of a request whose line is
    a VRAT, is refused when the deferred check runs."""
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    monkeypatch.setattr(
        services.two_person,
        "_write_documents",
        lambda locked, shipment, today: delivery_note(shipment),
    )
    with pytest.raises(IntegrityError, match="every document it needs"), transaction.atomic():
        two_step(strain)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS distribution_shipment_documented IMMEDIATE")


def test_at_commit_a_shipment_without_a_delivery_note_is_refused(
    supply: Supply, one_step: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services.shipment, "_write_documents", lambda locked, shipment, today: None)
    with pytest.raises(IntegrityError, match="every document it needs"), transaction.atomic():
        one_step(supply(vials=6))
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS distribution_shipment_documented IMMEDIATE")


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_a_document_is_never_added_to_a_shipment_later(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    """The shipment committed: a document written in a later transaction is refused, whatever
    it says."""
    with as_actor(curator):
        strain = supply(vials=6)
        request = submit(curator, lab, requester, [(strain, 1)])
        accept_mtas(curator, request)
        approve(curator, request)
        ship(curator, request)
    shipment = Shipment.objects.get(request=request)
    with pytest.raises(IntegrityError, match="written with its shipment"):
        insert(shipment, text="A SECOND NOTE\n")
    assert len(docs(request)) == 1


# Survivors of the mutation review.


def test_only_a_dual_use_restriction_brings_the_notice_not_a_vrat_listing(
    supply: Supply, two_step: Any, mockia: Taxon, curator: User, requester: Requester
) -> None:
    """Art. 11(9) is about Annex I of 2021/821: a VRAT line with no dual-use row prints none."""
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_VRAT)
    request = two_step(strain)
    assert documents.DUAL_USE_NOTICE not in note(request)
    assert "Dual-use" not in note(request)


def test_a_register_entry_says_when_the_company_number_is_not_known(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    make_requester: Any,
    lab: Lab,
    approver: User,
    manager: User,
) -> None:
    """Decree 474/2002 Sb., Annex 3 asks for the IČO if there is one: the entry says it is not
    known rather than leaving the line empty."""
    other = make_requester(institution="Example Company Laboratory", registration_number="")
    add_permit(curator, other, PermitKind.SUJB_VRAT)
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    request = submit(curator, lab, other, [(strain, 1)])
    accept_mtas(curator, request)
    approve(approver, request, "The recipient holds what the lists ask for.")
    prepare(manager, request)
    confirm(curator, request)
    entry = docs(request)[1].text.splitlines()
    assert "Company number (IČO): not known" in entry


def test_a_register_entry_without_a_known_seat_says_so_and_never_prints_the_delivery_address(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    make_requester: Any,
    lab: Lab,
    approver: User,
    manager: User,
) -> None:
    """A requester entered before the seat was asked has none: the entry says not known, and
    the laboratory's delivery address does not stand in for the registered office."""
    other = make_requester(institution="Example Older Laboratory", seat="")
    add_permit(curator, other, PermitKind.SUJB_VRAT)
    strain = supply(mockia, restrictions=[VRAT], vials=6)
    request = submit(curator, lab, other, [(strain, 1)])
    accept_mtas(curator, request)
    approve(approver, request, "The recipient holds what the lists ask for.")
    prepare(manager, request)
    confirm(curator, request)
    entry = docs(request)[1].text
    assert [line for line in entry.splitlines() if line.startswith("Seat:")] == ["Seat: not known"]
    for part in SCIENTIST.postal_address.splitlines():
        assert part not in entry, part


def test_at_commit_an_abs_sheet_does_not_stand_in_for_a_register_entry(
    *,
    supply: Supply,
    two_step: Any,
    mockia: Taxon,
    curator: User,
    requester: Requester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VRAT line whose terms are in scope needs both: the deferred check counts the register
    entry by its kind, so a line with only its ABS sheet is refused."""
    strain = supply(mockia, restrictions=[VRAT], vials=6, **in_scope())
    add_permit(curator, requester, PermitKind.SUJB_VRAT)

    def without_entry(locked: Any, shipment: Shipment, today: Any) -> None:
        facts = documents.gather(locked, shipment, today)
        for kind, line in documents.needs(facts):
            if kind == K.REGISTER_ENTRY:
                continue
            text = documents.render(facts, kind, line)
            ShipmentDocument.objects.create(
                lab_id=locked.lab_id,
                shipment=shipment,
                kind=kind,
                line=line,
                text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            )

    monkeypatch.setattr(services.two_person, "_write_documents", without_entry)
    with pytest.raises(IntegrityError, match="every document it needs"), transaction.atomic():
        two_step(strain)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS distribution_shipment_documented IMMEDIATE")
