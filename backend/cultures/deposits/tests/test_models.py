"""The database refuses deposit records that cannot be true, also when the services are
skipped: a constraint for every invariant of one row, a trigger for what may never change."""

import hashlib
from datetime import date
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.models.functions import Now

from cultures.deposits.models import (
    AbsScope,
    Condition,
    Contact,
    Decision,
    Deposit,
    Depositor,
    DepositStatus,
    DepositTerms,
    MtaTemplate,
    TermsUse,
    Use,
)
from cultures.labs.models import Lab
from cultures.taxonomy.models import Taxon

from .support import MakeDeposit

pytestmark = pytest.mark.django_db


def refused(constraint: str) -> Any:
    return pytest.raises(IntegrityError, match=constraint)


def guarded(message: str) -> Any:
    """A guard trigger raises restrict_violation, which psycopg reports as an IntegrityError."""
    return pytest.raises((IntegrityError, InternalError), match=message)


def sql(statement: str, params: list[Any] | None = None) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params or [])


# Contacts.


def raw_contact(lab: Lab, **fields: Any) -> Contact:
    with transaction.atomic():
        return Contact.objects.create(lab=lab, **{"name": "Jana Vzorová", **fields})


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"name": ""}, "deposits_contact_named_unless_erased"),
        ({"name": " Jana"}, "deposits_contact_named_unless_erased"),
        ({"erased_at": Now()}, "deposits_contact_named_unless_erased"),
        ({"name": "", "email": "a@example.org", "erased_at": Now()}, "named_unless_erased"),
        ({"name": "", "postal_address": "Brno", "erased_at": Now()}, "named_unless_erased"),
        ({"email": "no at sign"}, "deposits_contact_email_shape"),
        ({"postal_address": "Brno\n"}, "deposits_contact_postal_address_trimmed"),
    ],
)
def test_a_contact_is_named_unless_erased_and_then_empty(
    lab: Lab, fields: dict[str, Any], constraint: str
) -> None:
    with refused(constraint):
        raw_contact(lab, **fields)


def test_an_erased_contact_is_an_empty_row(lab: Lab) -> None:
    raw_contact(lab, name="", erased_at=Now())


def test_a_contact_is_never_deleted_and_an_erasure_never_undone(lab: Lab) -> None:
    contact = raw_contact(lab)
    with guarded("contacts are never deleted"):
        sql("DELETE FROM deposits_contact")
    sql("UPDATE deposits_contact SET name = '', email = '', erased_at = now()")
    with guarded("an erasure is never undone"):
        sql("UPDATE deposits_contact SET erased_at = NULL, name = 'Back'")
    with guarded("keeps its public id and lab"):
        sql("UPDATE deposits_contact SET lab_id = lab_id + 1")
    assert Contact.objects.get(pk=contact.pk).erased_at is not None


# Depositors.


def test_a_depositor_keeps_its_contact_and_is_never_deleted(lab: Lab, depositor: Depositor) -> None:
    other = raw_contact(lab, name="Petr Příklad")
    with guarded("keeps its public id, lab and contact"):
        sql("UPDATE deposits_depositor SET contact_id = %s", [other.pk])
    with guarded("depositors are never deleted"):
        sql("DELETE FROM deposits_depositor")
    sql("UPDATE deposits_depositor SET institution = 'Another University'")
    with refused("deposits_depositor_institution_trimmed"):
        sql("UPDATE deposits_depositor SET institution = 'x '")


# MTA templates.


def raw_mta(lab: Lab, **fields: Any) -> MtaTemplate:
    text = fields.pop("text", "The text.")
    values: dict[str, Any] = {
        "code": "STD",
        "version": 1,
        "title": "Standard",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        **fields,
    }
    with transaction.atomic():
        return MtaTemplate.objects.create(lab=lab, **values)


def test_an_mta_version_stores_the_hash_of_its_own_text(lab: Lab) -> None:
    raw_mta(lab, text="Žluťoučký kůň")  # the hash of the UTF-8 bytes
    with guarded("text_sha256 is not the SHA-256 of the text"):
        raw_mta(lab, version=2, text_sha256=hashlib.sha256(b"other").hexdigest())


def test_an_mta_version_is_frozen(lab: Lab) -> None:
    raw_mta(lab)
    with guarded("an MTA version is frozen"):
        sql("UPDATE deposits_mtatemplate SET title = 'Changed'")
    with guarded("an MTA version is frozen"):
        sql("DELETE FROM deposits_mtatemplate")


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"code": "std"}, "deposits_mtatemplate_code_format"),
        ({"code": "-STD"}, "deposits_mtatemplate_code_format"),
        ({"version": 0}, "deposits_mtatemplate_version_positive"),
        ({"title": ""}, "deposits_mtatemplate_title_trimmed"),
        ({"text": " ", "text_sha256": hashlib.sha256(b" ").hexdigest()}, "text_given"),
    ],
)
def test_mta_constraints(lab: Lab, fields: dict[str, Any], constraint: str) -> None:
    with refused(constraint):
        raw_mta(lab, **fields)


def test_a_version_of_a_code_exists_once_per_lab(lab: Lab, other_lab: Lab) -> None:
    raw_mta(lab)
    raw_mta(other_lab)
    with refused("deposits_mtatemplate_lab_code_version_uniq"):
        raw_mta(lab)


# Deposits.


def raw_deposit(depositor: Depositor, **fields: Any) -> Deposit:
    values: dict[str, Any] = {
        "lab_id": depositor.lab_id,
        "depositor": depositor,
        "status": DepositStatus.RECEIVED,
        "received_on": date(2026, 10, 1),
        "condition": Condition.INTACT,
        "name_as_received": "Testella exempli D1",
        **fields,
    }
    with transaction.atomic():
        return Deposit.objects.create(**values)


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"status": "lost"}, "deposits_deposit_decided_iff_decision"),
        ({"status": "lost", "decided_at": Now()}, "deposits_deposit_decided_iff_decision"),
        ({"name_as_received": " x"}, "deposits_deposit_name_as_received_trimmed"),
        ({"condition": Condition.DAMAGED}, "deposits_deposit_condition_noted"),
        ({"condition": "melted", "condition_note": "x"}, "deposits_deposit_condition_noted"),
        ({"status": DepositStatus.ACCEPTED, "decided_at": Now()}, "strain_iff_accepted"),
        ({"status": DepositStatus.REJECTED, "decided_at": Now()}, "reason_iff_rejected"),
        ({"rejection_reason": "mixed"}, "deposits_deposit_reason_iff_rejected"),
        ({"decided_at": Now()}, "deposits_deposit_decided_iff_decision"),
        (
            {"status": DepositStatus.REJECTED, "rejection_reason": "mixed"},
            "deposits_deposit_decided_iff_decision",
        ),
    ],
)
def test_deposit_constraints(depositor: Depositor, fields: dict[str, Any], constraint: str) -> None:
    with refused(constraint):
        raw_deposit(depositor, **fields)


def test_a_damaged_arrival_with_its_note_is_valid(depositor: Depositor) -> None:
    raw_deposit(depositor, condition=Condition.DAMAGED, condition_note="cracked ampoule")


@pytest.mark.parametrize(
    "change",
    [
        "received_on = received_on - 1",
        "condition = 'damaged', condition_note = 'x'",
        "name_as_received = 'other'",
        "depositor_passages = 3",
        "lab_id = lab_id + 1",
        "public_id = gen_random_uuid()",
    ],
)
def test_the_receipt_never_changes(make_deposit: MakeDeposit, change: str) -> None:
    make_deposit()
    with guarded("the receipt of a deposit never changes"):
        sql(f"UPDATE deposits_deposit SET {change}")  # noqa: S608 (a literal from the list)


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("received", "accepted"),
        ("received", "rejected"),
        ("checking", "received"),
        ("rejected", "checking"),
    ],
)
def test_the_status_moves_only_forward_along_d8(
    make_deposit: MakeDeposit, exempli: Taxon, start: str, target: str
) -> None:
    make_deposit(start)
    with guarded(f"a {start} deposit cannot become {target}|a decided deposit never changes"):
        sql(
            "UPDATE deposits_deposit SET status = %s, rejection_reason = %s, decided_at = now()",
            [target, "x" if target == "rejected" else ""],
        )


def test_a_decided_deposit_never_changes(make_deposit: MakeDeposit, exempli: Taxon) -> None:
    make_deposit("accepted", taxon=exempli)
    with guarded("a decided deposit never changes"):
        sql("UPDATE deposits_deposit SET decided_at = now() - interval '1 day'")
    with guarded("deposits are never deleted"):
        sql("DELETE FROM deposits_deposit")


# Terms.


def raw_terms(deposit: Deposit, **fields: Any) -> DepositTerms:
    values: dict[str, Any] = {
        "lab_id": deposit.lab_id,
        "deposit": deposit,
        "version": 9,
        "is_active": False,
        "abs_scope": AbsScope.NOT_IN_SCOPE,
        "reason": "corrected",
        **fields,
    }
    with transaction.atomic():
        return DepositTerms.objects.create(**values)


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"is_active": True}, "deposits_depositterms_one_active"),
        ({"version": 1, "reason": ""}, "deposits_depositterms_deposit_version_uniq"),
        ({"reason": ""}, "deposits_depositterms_reason_after_first"),
        ({"abs_scope": "maybe"}, "deposits_depositterms_scope_valid"),
        ({"abs_scope": AbsScope.IN_SCOPE}, "deposits_depositterms_in_scope_has_ircc_or_permit"),
        ({"country_of_origin": "XX"}, "deposits_depositterms_country_iso_3166"),
        ({"collection_date": "2019-13"}, "deposits_depositterms_collection_date_iso_8601"),
        ({"ircc": " ABSCH"}, "deposits_depositterms_ircc_trimmed"),
        ({"permit_reference": "x "}, "deposits_depositterms_permit_reference_trimmed"),
        ({"pic_reference": " x"}, "deposits_depositterms_pic_reference_trimmed"),
        ({"mat_reference": " x"}, "deposits_depositterms_mat_reference_trimmed"),
    ],
)
def test_terms_constraints(
    make_deposit: MakeDeposit, fields: dict[str, Any], constraint: str
) -> None:
    deposit = make_deposit()  # with version 1, active
    with refused(constraint):
        raw_terms(deposit, **fields)


@pytest.mark.parametrize("reference", [{"ircc": "ABSCH-IRCC-XX-1"}, {"permit_reference": "P/1"}])
def test_material_in_scope_with_a_certificate_or_permit_is_valid(
    make_deposit: MakeDeposit, reference: dict[str, str]
) -> None:
    raw_terms(make_deposit(), abs_scope=AbsScope.IN_SCOPE, **reference)


def test_a_terms_version_only_stops_being_active(make_deposit: MakeDeposit) -> None:
    make_deposit()
    with guarded("a terms version only stops being active"):
        sql("UPDATE deposits_depositterms SET abs_scope = 'unknown'")
    with guarded("terms are history and never deleted"):
        sql("DELETE FROM deposits_depositterms")
    sql("UPDATE deposits_depositterms SET is_active = false")
    with guarded("a terms version only stops being active"):
        sql("UPDATE deposits_depositterms SET is_active = true")


def test_the_uses_of_a_version_never_change(make_deposit: MakeDeposit) -> None:
    make_deposit()
    assert TermsUse.objects.count() == len(Use)
    with guarded("the uses of a terms version never change"):
        sql("UPDATE deposits_termsuse SET decision = 'deny'")
    with guarded("the uses of a terms version never change"):
        sql("DELETE FROM deposits_termsuse")


def test_a_use_is_decided_once_per_version_with_known_values(make_deposit: MakeDeposit) -> None:
    terms = make_deposit().terms.get()
    with refused("deposits_termsuse_terms_use_uniq"), transaction.atomic():
        TermsUse.objects.create(terms=terms, use=Use.TEACHING, decision=Decision.DENY)
    with refused("deposits_termsuse_values_valid"), transaction.atomic():
        TermsUse.objects.create(terms=terms, use="eating", decision=Decision.DENY)
