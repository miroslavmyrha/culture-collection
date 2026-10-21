"""The database holds distribution's rules on its own: constraints by name, and the guard
triggers against every writer (raw SQL here), each tried both ways."""

import hashlib
from datetime import date
from typing import Any

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Model

from cultures.audit.context import AuditContext
from cultures.deposits.models import Contact, DepositTerms, MtaTemplate
from cultures.distribution.models import (
    Document,
    LinePermit,
    MtaAcceptance,
    PermitKind,
    RecipientPermit,
    RequestCounter,
    Requester,
    RequestLine,
    VialReservation,
)
from cultures.labs.models import Lab
from cultures.lineage.models import Vial
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    PDF,
    MakeRequester,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    reserved,
    submit,
)

pytestmark = pytest.mark.django_db


def sql(statement: str, params: list[Any] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])


def refused_by(match: str, statement: str, params: list[Any] | None = None) -> None:
    with pytest.raises(DatabaseError, match=match), transaction.atomic():
        sql(statement, params)


def violates(name: str, model: type[Model], **values: Any) -> None:
    with pytest.raises(IntegrityError) as raised, transaction.atomic():
        model._default_manager.create(**values)
    assert raised.value.__cause__.diag.constraint_name == name  # type: ignore[union-attr]


def immediate() -> None:
    """Fire the deferred triggers now, as a commit would."""
    sql("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.fixture
def approved(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> Any:
    request = submit(curator, lab, requester, [(supply(), 2)])
    accept_mtas(curator, request)
    return approve(curator, request)


# Requesters.


@pytest.mark.parametrize(
    ("fields", "name"),
    [
        ({"institution": " x"}, "distribution_requester_institution_trimmed"),
        ({"legal_form": "private_person"}, "distribution_requester_legal_form_valid"),
        ({"registration_number": "1 "}, "distribution_requester_registration_number_trimmed"),
        ({"country": "XX"}, "distribution_requester_country_iso_3166"),
        ({"lab_evidence": "  "}, "distribution_requester_lab_evidence_given"),
    ],
)
def test_requester_constraints(requester: Requester, fields: dict[str, Any], name: str) -> None:
    contact = Contact.objects.create(lab_id=requester.lab_id, name="Someone")
    values = {
        "lab_id": requester.lab_id,
        "contact": contact,
        "institution": "Example",
        "legal_form": "legal_person",
        "country": "CZ",
        "lab_evidence": "seen",
        "lab_confirmed_on": date(2026, 1, 1),
        **fields,
    }
    violates(name, Requester, **values)


def test_a_requester_keeps_its_lab_and_contact_and_is_never_deleted(requester: Requester) -> None:
    refused_by("never deleted", "DELETE FROM distribution_requester")
    refused_by(
        "keeps its public id, lab and contact",
        "UPDATE distribution_requester SET contact_id = contact_id + 1",
    )
    sql("UPDATE distribution_requester SET institution = 'Renamed Institute'")


# Documents and permits.


def test_a_document_stores_the_hash_and_size_of_its_own_content(lab: Lab) -> None:
    good = hashlib.sha256(PDF).hexdigest()
    with pytest.raises(DatabaseError, match="sha256 and size"), transaction.atomic():
        Document.objects.create(
            lab=lab,
            content=PDF,
            content_type="application/pdf",
            size_bytes=len(PDF),
            sha256="0" * 64,
        )
    with pytest.raises(DatabaseError, match="sha256 and size"), transaction.atomic():
        Document.objects.create(
            lab=lab, content=PDF, content_type="application/pdf", size_bytes=1, sha256=good
        )
    Document.objects.create(
        lab=lab, content=PDF, content_type="application/pdf", size_bytes=len(PDF), sha256=good
    )
    refused_by(
        "a document is frozen", "UPDATE distribution_document SET content_type = 'image/png'"
    )
    refused_by("a document is frozen", "DELETE FROM distribution_document")


@pytest.mark.parametrize(
    ("content", "fields", "name"),
    [
        (PDF, {"content_type": "text/html"}, "distribution_document_type_valid"),
        (b"", {}, "distribution_document_size_range"),
        (PDF + b"x" * (10 * 1024 * 1024), {}, "distribution_document_size_range"),
    ],
)
def test_document_constraints(lab: Lab, content: bytes, fields: dict[str, Any], name: str) -> None:
    values = {
        "lab": lab,
        "content": content,
        "content_type": "application/pdf",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        **fields,
    }
    violates(name, Document, **values)


def raw_permit(requester: Requester, document: Document, **fields: Any) -> dict[str, Any]:
    return {
        "lab_id": requester.lab_id,
        "requester": requester,
        "kind": PermitKind.SUJB_RAT_NOTICE,
        "issuer": "SÚJB",
        "issuer_country": "CZ",
        "reference": "R/1",
        "valid_from": date(2026, 1, 1),
        "document": document,
        **fields,
    }


LOA = {"kind": PermitKind.PLANT_HEALTH_LOA, "covers": "Mockia vulgaris"}


@pytest.mark.parametrize(
    ("fields", "name"),
    [
        ({"kind": "import_permit"}, "distribution_permit_kind_valid"),
        ({"issuer": ""}, "distribution_permit_issuer_trimmed"),
        ({"issuer_country": "XX"}, "distribution_permit_issuer_country_iso_3166"),
        ({"reference": "R "}, "distribution_permit_reference_trimmed"),
        ({"expires_on": date(2025, 1, 1)}, "distribution_permit_expires_after_start"),
        ({"ended_on": date(2025, 1, 1), "end_reason": "r"}, "distribution_permit_ends_after_start"),
        ({"ended_on": date(2026, 2, 1)}, "distribution_permit_end_has_reason"),
        ({"end_reason": "r"}, "distribution_permit_end_has_reason"),
        ({"kind": PermitKind.SUJB_VRAT}, "distribution_permit_names_what_it_covers"),
        ({**LOA, "sendings_allowed": 1}, "distribution_permit_quantity_iff_loa"),
        (
            {**LOA, "quantity_allowed": 0, "sendings_allowed": 1},
            "distribution_permit_quantity_iff_loa",
        ),
        ({"quantity_allowed": 1, "sendings_allowed": 1}, "distribution_permit_quantity_iff_loa"),
        (
            {"endorsement_reference": "E/1", "endorsed_on": date(2026, 1, 2)},
            "distribution_permit_endorsement_of_loa",
        ),
        (
            {**LOA, "quantity_allowed": 1, "sendings_allowed": 1, "endorsement_reference": "E/1"},
            "distribution_permit_endorsement_of_loa",
        ),
        ({"kind": PermitKind.GMO_CONTAINED_USE}, "distribution_permit_category_iff_gmo"),
        (
            {"kind": PermitKind.GMO_CONTAINED_USE, "gmo_category": 5},
            "distribution_permit_category_iff_gmo",
        ),
        ({"gmo_category": 1}, "distribution_permit_category_iff_gmo"),
        (
            {"kind": PermitKind.PATHOGEN_WORK_PERMIT},
            "distribution_permit_risk_group_iff_work_permit",
        ),
        ({"risk_group": 2}, "distribution_permit_risk_group_iff_work_permit"),
    ],
)
def test_permit_constraints(
    as_curator: AuditContext,
    curator: User,
    requester: Requester,
    fields: dict[str, Any],
    name: str,
) -> None:
    document = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE).document
    violates(name, RecipientPermit, **raw_permit(requester, document, **fields))


def test_a_letter_with_its_quantity_sendings_and_endorsement_is_valid(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    document = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE).document
    RecipientPermit.objects.create(
        **raw_permit(
            requester,
            document,
            **LOA,
            quantity_allowed=4,
            sendings_allowed=1,
            endorsement_reference="ÚKZÚZ/E/1",
            endorsed_on=date(2026, 2, 1),
        )
    )


def test_a_permit_changes_once_when_it_ends_and_is_never_deleted(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    refused_by("never deleted", "DELETE FROM distribution_recipientpermit")
    refused_by("changes once", "UPDATE distribution_recipientpermit SET reference = 'other'")
    sql("UPDATE distribution_recipientpermit SET ended_on = '2026-06-01', end_reason = 'revoked'")
    refused_by(
        "changes once",
        "UPDATE distribution_recipientpermit SET ended_on = '2026-06-02', end_reason = 'again'",
    )


# The counter and requests.


def test_a_counter_only_rises(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    submit(curator, lab, requester, [(supply(), 1)])
    refused_by("only rises", "UPDATE distribution_requestcounter SET last_number = 0")
    refused_by("only rises", "UPDATE distribution_requestcounter SET year = year + 1")
    refused_by("only rises", "DELETE FROM distribution_requestcounter")
    sql("UPDATE distribution_requestcounter SET last_number = 5")
    assert RequestCounter.objects.get().last_number == 5


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ("end_use = 'something else'", "never changes"),
        ("requester_id = requester_id", None),
        ("containment_level = 3", "never changes"),
        ("number = number + 1", "never changes"),
        ("decision_reason = 'later'", "written with its status, once"),
    ],
)
def test_what_a_request_asks_for_never_changes(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    change: str,
    match: str | None,
) -> None:
    submit(curator, lab, requester, [(supply(), 1)])
    statement = f"UPDATE distribution_distributionrequest SET {change}"  # noqa: S608 (test literals)
    if match is None:
        sql(statement)
    else:
        refused_by(match, statement)
    refused_by("never deleted", "DELETE FROM distribution_distributionrequest")


def test_an_approval_stays_as_it_was_given(approved: Any, manager: User) -> None:
    refused_by(
        "an approval stays as it was given",
        "UPDATE distribution_distributionrequest SET status = 'cancelled', decided_by_id = %s,"
        " cancelled_by_id = %s, cancelled_at = now(), cancel_reason = 'r'",
        [manager.pk, manager.pk],
    )


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("approved", ""),
        ("rejected", ", decided_by_id = submitted_by_id, decided_at = now()"),
        ("cancelled", ", cancelled_by_id = submitted_by_id, cancelled_at = now()"),
    ],
)
def test_each_status_has_exactly_its_facts(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    status: str,
    extra: str,
) -> None:
    submit(curator, lab, requester, [(supply(), 1)])
    with pytest.raises(IntegrityError) as raised, transaction.atomic():
        sql(f"UPDATE distribution_distributionrequest SET status = '{status}'{extra}")  # noqa: S608
    assert raised.value.__cause__.diag.constraint_name == "distribution_request_facts_of_status"  # type: ignore[union-attr]


# Lines, the permits they were approved against, acceptances.


def test_a_line_never_changes_and_pins_its_strains_terms_and_mta(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    other = supply(mockia)
    line = request.lines.get()
    refused_by("never changes", "UPDATE distribution_requestline SET quantity = 2")
    refused_by("never changes", "DELETE FROM distribution_requestline")
    other_terms = DepositTerms.objects.get(deposit__strain=other)
    base = {"lab_id": lab.pk, "request": request, "quantity": 1}
    with pytest.raises(DatabaseError, match="pins a terms version"), transaction.atomic():
        RequestLine.objects.create(**base, strain=other, terms=line.terms, mta=line.mta)
    with pytest.raises(DatabaseError, match="pins a terms version"), transaction.atomic():
        RequestLine.objects.create(**base, strain=other, terms=other_terms, mta=None)
    RequestLine.objects.create(**base, strain=other, terms=other_terms, mta=other_terms.mta)


def test_lines_are_added_only_while_the_request_waits_and_in_its_lab(
    *,
    approved: Any,
    lab: Lab,
    other_lab: Lab,
    supply: Supply,
    mockia: Taxon,
) -> None:
    other = supply(mockia)
    terms = DepositTerms.objects.get(deposit__strain=other)
    with (
        pytest.raises(DatabaseError, match="added when a request is entered"),
        transaction.atomic(),
    ):
        RequestLine.objects.create(
            lab_id=lab.pk, request=approved, strain=other, quantity=1, terms=terms, mta=terms.mta
        )
    with pytest.raises(DatabaseError, match="of one lab"), transaction.atomic():
        RequestLine.objects.create(
            lab_id=other_lab.pk,
            request=approved,
            strain=other,
            quantity=1,
            terms=terms,
            mta=terms.mta,
        )


@pytest.mark.parametrize(
    ("fields", "name"),
    [
        ({"quantity": 0}, "distribution_line_quantity_range"),
        ({"quantity": 51}, "distribution_line_quantity_range"),
    ],
)
def test_line_constraints(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    fields: dict[str, Any],
    name: str,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    other = supply(mockia)
    terms = DepositTerms.objects.get(deposit__strain=other)
    values = {
        "lab_id": lab.pk,
        "request": request,
        "strain": other,
        "terms": terms,
        "mta": terms.mta,
    }
    violates(name, RequestLine, **{**values, **fields})
    line = request.lines.get()
    violates(
        "distribution_line_request_strain_uniq",
        RequestLine,
        **{**values, "strain": line.strain, "terms": line.terms, "mta": line.mta, "quantity": 1},
    )


def test_a_line_is_approved_against_its_requesters_permits_only(
    *,
    approved: Any,
    curator: User,
    make_requester: MakeRequester,
) -> None:
    stranger = make_requester(institution="Another Institute")
    foreign = add_permit(curator, stranger, PermitKind.SUJB_RAT_NOTICE)
    own = add_permit(curator, approved.requester, PermitKind.SUJB_RAT_NOTICE)
    line = approved.lines.get()
    with pytest.raises(DatabaseError, match="its requester's permits"), transaction.atomic():
        LinePermit.objects.create(line=line, permit=foreign)
    LinePermit.objects.create(line=line, permit=own)
    refused_by("never change", "DELETE FROM distribution_linepermit")


def test_an_acceptance_is_frozen_and_only_of_a_pinned_version(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    [acceptance] = accept_mtas(curator, request)
    refused_by(
        "never changes", "UPDATE distribution_mtaacceptance SET authorised_signatory = false"
    )
    refused_by("never changes", "DELETE FROM distribution_mtaacceptance")
    other = MtaTemplate.objects.create(
        lab=lab,
        code="OTHER",
        version=1,
        title="Other",
        text="t",
        text_sha256=hashlib.sha256(b"t").hexdigest(),
    )
    with (
        pytest.raises(DatabaseError, match="an acceptance is of an MTA version"),
        transaction.atomic(),
    ):
        MtaAcceptance.objects.create(
            lab=lab,
            request=request,
            mta=other,
            signer=Contact.objects.create(lab=lab, name="Someone"),
            signer_role="head_of_institution",
            authorised_signatory=True,
            accepted_on=date(2026, 10, 2),
            document=acceptance.document,
        )


# Reservations and the reserved vial.


def test_a_reservation_changes_once_when_it_ends_and_is_never_deleted(approved: Any) -> None:
    refused_by("never deleted", "DELETE FROM distribution_vialreservation")
    refused_by("changes once", "UPDATE distribution_vialreservation SET reserved_at = now()")
    held = VialReservation.objects.filter(line__request=approved).first()
    assert held is not None
    sql(
        "UPDATE distribution_vialreservation SET ended_at = clock_timestamp(),"
        " ended_by_id = reserved_by_id, end_reason = 'cancelled' WHERE id = %s",
        [held.pk],
    )
    # The vial follows, or the deferred check refuses the pair at the end of the test.
    sql("UPDATE lineage_vial SET status = 'available' WHERE id = %s", [held.vial_id])
    refused_by(
        "changes once",
        "UPDATE distribution_vialreservation SET end_reason = 'shipped' WHERE id = %s",
        [held.pk],
    )


def test_one_open_reservation_per_vial(approved: Any, curator: User) -> None:
    held = VialReservation.objects.filter(line__request=approved).first()
    assert held is not None
    violates(
        "distribution_reservation_one_open_per_vial",
        VialReservation,
        lab_id=held.lab_id,
        line=held.line,
        vial=held.vial,
        reserved_at=held.reserved_at,
        reserved_by=curator,
    )


@pytest.mark.parametrize(
    ("fields", "name"),
    [
        ({"end_reason": "cancelled"}, "distribution_reservation_end_complete"),
        (
            {"ended_at": "2020-01-01T00:00:00Z", "end_reason": "cancelled"},
            "distribution_reservation_end_complete",
        ),
    ],
)
def test_reservation_constraints(
    approved: Any, curator: User, fields: dict[str, Any], name: str
) -> None:
    held = VialReservation.objects.filter(line__request=approved).first()
    assert held is not None
    with pytest.raises(IntegrityError) as raised, transaction.atomic():
        VialReservation.objects.filter(pk=held.pk).update(**fields)
    assert raised.value.__cause__.diag.constraint_name == name  # type: ignore[union-attr]


def test_a_reservation_opens_only_for_a_vial_of_its_lines_strain(
    *,
    approved: Any,
    curator: User,
    supply: Supply,
    mockia: Taxon,
) -> None:
    other_vial = Vial.objects.filter(batch__strain=supply(mockia)).first()
    assert other_vial is not None
    with pytest.raises(DatabaseError, match="vial of its line's strain"), transaction.atomic():
        VialReservation.objects.create(
            lab_id=approved.lab_id,
            line=approved.lines.get(),
            vial=other_vial,
            reserved_at="2026-10-02T10:00:00Z",
            reserved_by=curator,
        )


def test_at_commit_a_vial_is_reserved_if_and_only_if_a_request_holds_it(approved: Any) -> None:
    [first, second] = reserved(approved)
    immediate()  # what the approval wrote holds
    with (
        pytest.raises(DatabaseError, match="if and only if a request holds it"),
        transaction.atomic(),
    ):
        sql("UPDATE lineage_vial SET status = 'available' WHERE id = %s", [first.pk])
        immediate()
    free = Vial.objects.filter(status="available", batch__strain_id=first.batch.strain_id).first()
    assert free is not None
    with (
        pytest.raises(DatabaseError, match="an open reservation holds a reserved vial"),
        transaction.atomic(),
    ):
        held = VialReservation.objects.get(vial=first)
        VialReservation.objects.create(
            lab_id=held.lab_id,
            line=held.line,
            vial=free,
            reserved_at=held.reserved_at,
            reserved_by=held.reserved_by,
        )
        immediate()
    assert second.status == "reserved"
    with (
        pytest.raises(DatabaseError, match="if and only if a request holds it"),
        transaction.atomic(),
    ):
        sql(
            "UPDATE lineage_vial SET status = 'reserved', status_changed_at = now() WHERE id = %s",
            [free.pk],
        )
        immediate()
    # Ending the reservation and freeing the vial together is what a cancellation does.
    with transaction.atomic():
        sql(
            "UPDATE distribution_vialreservation SET ended_at = clock_timestamp(),"
            " ended_by_id = reserved_by_id,"
            " end_reason = 'cancelled' WHERE vial_id = %s",
            [first.pk],
        )
        sql("UPDATE lineage_vial SET status = 'available' WHERE id = %s", [first.pk])
        immediate()
