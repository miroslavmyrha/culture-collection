"""What the deposit APIs answer: the bodies, the server errors a form maps onto its fields
(also the biosafety refusals at acceptance), the filters, the order and exact query counts."""

from datetime import date
from typing import Any

import pytest

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.models import AuthorisationKind
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits import services
from cultures.deposits.models import Deposit, Depositor, MtaTemplate
from cultures.deposits.services import ContactInput
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Passage
from cultures.strains.models import Strain
from cultures.strains.tests.test_api import field_code
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    DEPOSITORS_URL,
    DEPOSITS_URL,
    MTA_URL,
    MakeDeposit,
    MakeDepositor,
    as_actor,
    facts_body,
    make_permit,
    terms_body,
)

pytestmark = pytest.mark.django_db
# Raised by the services with their own code on top; a serializer's field error is "invalid".
DOMAIN_CODES = {"risk_group_4_refused", "lab_authorisation_required", "unique"}


def post(user: User, url: str, body: dict[str, Any]) -> Any:
    return logged_in(user).post(url, body, content_type="application/json")


def receipt(depositor: Depositor, **changes: Any) -> dict[str, Any]:
    return {
        "depositor": str(depositor.public_id),
        "received_on": "2026-10-01",
        "condition": "damaged",
        "condition_note": "cracked ampoule",
        "name_as_received": "Testella exempli K3",
        "depositor_passages": 4,
        "terms": terms_body(),
        **changes,
    }


# The intake through the API, step by step.


def test_a_curator_takes_a_deposit_from_receipt_to_a_strain(
    *, curator: User, lab: Lab, depositor: Depositor, mta: MtaTemplate, exempli: Taxon
) -> None:
    created = post(
        curator,
        DEPOSITS_URL,
        receipt(
            depositor,
            terms=terms_body(
                mta=str(mta.public_id),
                abs_scope="in_scope",
                permit_reference="Permit DEV/1 (invented example)",
                country_of_origin="CZ",
                collection_date="2019",
            ),
        ),
    )
    assert created.status_code == 201, created.content
    body = created.json()
    deposit = Deposit.objects.get()
    terms = deposit.terms.get()
    assert body == {
        "public_id": str(deposit.public_id),
        "status": "received",
        "received_on": "2026-10-01",
        "name_as_received": "Testella exempli K3",
        "depositor": {
            "public_id": str(depositor.public_id),
            "name": "Jana Vzorová",
            "institution": "Example University",
            "erased": False,
        },
        "strain": None,
        "created_at": body["created_at"],
        "condition": "damaged",
        "condition_note": "cracked ampoule",
        "depositor_passages": 4,
        "decided_at": None,
        "rejection_reason": "",
        "terms": body["terms_history"][0],
        "terms_history": [
            {
                "public_id": str(terms.public_id),
                "version": 1,
                "is_active": True,
                "mta": {
                    "public_id": str(mta.public_id),
                    "code": "STD",
                    "version": 1,
                    "title": "Standard MTA",
                    "text_sha256": mta.text_sha256,
                },
                "abs_scope": "in_scope",
                "country_of_origin": "CZ",
                "collection_date": "2019",
                "pic_reference": "",
                "mat_reference": "",
                "ircc": "",
                "permit_reference": "Permit DEV/1 (invented example)",
                "mat_uses": [],
                "reason": "",
                "uses": body["terms_history"][0]["uses"],
                "created_at": body["terms_history"][0]["created_at"],
            }
        ],
    }
    assert len(body["terms"]["uses"]) == 8
    detail = f"{DEPOSITS_URL}{deposit.public_id}/"
    checking = post(curator, f"{detail}start-check/", {})
    assert checking.json()["status"] == "checking"
    accepted = post(curator, f"{detail}accept/", facts_body(exempli, country_of_origin="CZ"))
    assert accepted.status_code == 200, accepted.content
    strain = Strain.objects.get()
    assert accepted.json()["strain"] == {
        "public_id": str(strain.public_id),
        "accession_number": "MYC 1",
    }
    assert strain.name_as_received == "Testella exempli K3"
    assert Passage.objects.get().source_deposit == deposit
    event = AuditEvent.objects.get(event_type="deposit_accepted")
    assert (event.channel, event.actor, event.request_id) == (
        Channel.API,
        curator,
        accepted["X-Request-ID"],
    )


def test_the_input_names_no_lab_status_strain_or_version(
    *, curator: User, lab: Lab, other_lab: Lab, depositor: Depositor, make_strain: Any
) -> None:
    elsewhere = make_strain(name_as_received="other")
    body = receipt(
        depositor,
        lab=str(other_lab.public_id),
        status="accepted",
        strain=str(elsewhere.public_id),
        terms=terms_body(version=7, is_active=False),
    )
    answer = post(curator, DEPOSITS_URL, body).json()
    assert (answer["status"], answer["strain"], answer["terms"]["version"]) == ("received", None, 1)
    assert Deposit.objects.get().lab == lab


@pytest.mark.parametrize(
    ("changes", "code", "attr"),
    [
        ({"depositor": "00000000-0000-4000-8000-000000000999"}, "does_not_exist", "depositor"),
        ({"condition": "melted"}, "invalid_choice", "condition"),
        ({"condition_note": ""}, "invalid", "condition_note"),
        ({"name_as_received": ""}, "blank", "name_as_received"),
        ({"received_on": "2999-01-01"}, "invalid", "received_on"),
        ({"terms": terms_body(abs_scope="in_scope")}, "invalid", "terms.ircc"),
        ({"terms": terms_body(uses=[])}, "invalid", "terms.uses"),
        (
            {"terms": terms_body(uses=[{"use": "eating", "decision": "permit"}])},
            "invalid_choice",
            "terms.uses.0.use",
        ),
        (
            {"terms": terms_body(mta="00000000-0000-4000-8000-000000000999")},
            "does_not_exist",
            "terms.mta",
        ),
        (
            {"terms": terms_body(country_of_origin="XK")},
            "invalid_choice",
            "terms.country_of_origin",
        ),
    ],
)
def test_receipt_errors_name_their_field(
    *, curator: User, depositor: Depositor, changes: dict[str, Any], code: str, attr: str
) -> None:
    body = assert_problem(
        post(curator, DEPOSITS_URL, {**receipt(depositor), **changes}), 400, "invalid", attr=attr
    )
    assert field_code(body, attr) == code
    assert not Deposit.objects.exists()


def test_a_depositor_or_mta_of_another_lab_is_unknown_here(
    *,
    curator: User,
    depositor: Depositor,
    other_lab: Lab,
    outsider: User,
    make_depositor: MakeDepositor,
    as_curator: AuditContext,
) -> None:
    foreign = make_depositor(lab=other_lab, actor=outsider)
    template = services.mta_template_publish(
        access=access_for(outsider), lab=other_lab, code="STD", title="T", text="x"
    )
    for body, attr in (
        (receipt(foreign), "depositor"),
        (receipt(depositor, terms=terms_body(mta=str(template.public_id))), "terms.mta"),
    ):
        answer = assert_problem(post(curator, DEPOSITS_URL, body), 400, "invalid", attr=attr)
        assert field_code(answer, attr) == "does_not_exist"


@pytest.mark.parametrize(
    ("changes", "status", "code", "attr"),
    [
        ({"risk_group": 4}, 400, "risk_group_4_refused", "risk_group"),
        ({"risk_group": 5}, 400, "invalid_choice", "risk_group"),
        ({"taxon": "00000000-0000-4000-8000-000000000999"}, 400, "does_not_exist", "taxon"),
        ({"taxon": "not-a-uuid"}, 400, "does_not_exist", "taxon"),
        ({"country_of_origin": "XK"}, 400, "invalid_choice", "country_of_origin"),
        ({"isolation_date": "2019-02-30"}, 400, "invalid", "isolation_date"),
        ({"identified_on": "2999-01-01"}, 400, "invalid", "identified_on"),
        (
            {"restrictions": [{"kind": "dual_use", "reference": "1C351.c"}]},
            400,
            "invalid",
            "restrictions.0.act",
        ),
        (
            {"restrictions": [{"kind": "gmo", "reference": "x"}]},
            400,
            "invalid",
            "restrictions.0.gmo_category",
        ),
        (
            {
                "restrictions": [
                    {"kind": "cz_rat", "reference": "x"},
                    {"kind": "cz_vrat", "reference": "y"},
                ]
            },
            422,
            "lab_authorisation_required",
            "restrictions.1.kind",
        ),
    ],
)
def test_acceptance_errors_name_their_field_and_change_nothing(
    *,
    curator: User,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    changes: dict[str, Any],
    status: int,
    code: str,
    attr: str,
) -> None:
    deposit = make_deposit("checking")
    events = AuditEvent.objects.count()
    response = post(
        curator, f"{DEPOSITS_URL}{deposit.public_id}/accept/", {**facts_body(exempli), **changes}
    )
    top = code if code in DOMAIN_CODES else "invalid"  # a serializer error is "invalid" on top
    body = assert_problem(response, status, top, attr=attr)
    assert field_code(body, attr) == code
    assert Deposit.objects.get(pk=deposit.pk).status == "checking"
    assert not Strain.objects.exists()
    assert AuditEvent.objects.count() == events


def test_the_permit_refusal_says_which_permit(
    *, curator: User, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    deposit = make_deposit("checking")
    body = assert_problem(
        post(
            curator,
            f"{DEPOSITS_URL}{deposit.public_id}/accept/",
            facts_body(
                exempli, restrictions=[{"kind": "quarantine_pest", "reference": "Annex II"}]
            ),
        ),
        422,
        "lab_authorisation_required",
    )
    assert body["detail"] == "The lab holds no valid ÚKZÚZ permit for quarantine pests today."


def test_with_the_permit_a_vrat_strain_is_accepted(
    *, curator: User, lab: Lab, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    deposit = make_deposit("checking")
    response = post(
        curator,
        f"{DEPOSITS_URL}{deposit.public_id}/accept/",
        facts_body(exempli, restrictions=[{"kind": "cz_vrat", "reference": "Příloha 1, bod 2"}]),
    )
    assert response.status_code == 200, response.content


def test_a_second_decision_is_409_and_the_terms_need_a_reason(
    *, curator: User, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    deposit = make_deposit("accepted", taxon=exempli)
    detail = f"{DEPOSITS_URL}{deposit.public_id}/"
    for action, body in (
        ("accept/", facts_body(exempli)),
        ("reject/", {"reason": "r"}),
        ("start-check/", {}),
    ):
        assert_problem(post(curator, detail + action, body), 409, "deposit_state")
    assert_problem(
        post(curator, f"{detail}terms/", {"terms": terms_body(), "reason": ""}),
        400,
        "invalid",
        attr="reason",
    )
    replaced = post(
        curator,
        f"{detail}terms/",
        {"terms": terms_body(abs_scope="unknown"), "reason": "corrected"},
    )
    answer = replaced.json()
    assert (answer["terms"]["version"], [t["version"] for t in answer["terms_history"]]) == (
        2,
        [2, 1],
    )
    assert [t["is_active"] for t in answer["terms_history"]] == [True, False]


# Depositors and MTA templates.


def test_a_curator_adds_and_changes_a_depositor(curator: User, lab: Lab) -> None:
    created = post(
        curator,
        DEPOSITORS_URL,
        {
            "name": "Petr Příklad",
            "email": "petr@example.org",
            "postal_address": "Brno",
            "institution": "",
        },
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert {k: body[k] for k in ("name", "email", "postal_address", "institution", "erased")} == {
        "name": "Petr Příklad",
        "email": "petr@example.org",
        "postal_address": "Brno",
        "institution": "",
        "erased": False,
    }
    changed = logged_in(curator).put(
        f"{DEPOSITORS_URL}{body['public_id']}/",
        {"name": "Petr Příklad", "email": "", "institution": "Example Institute"},
        content_type="application/json",
    )
    assert (changed.json()["email"], changed.json()["institution"]) == ("", "Example Institute")
    bad = post(curator, DEPOSITORS_URL, {"name": "", "email": "not an address"})
    answer = assert_problem(bad, 400, "invalid")
    assert {e["attr"] for e in answer["errors"]} == {"name", "email"}


def test_an_erased_depositor_shows_as_erased_and_cannot_be_changed(
    *, curator: User, depositor: Depositor, as_curator: AuditContext
) -> None:
    services.contact_erase(contact=depositor.contact, reason="erasure request")
    row = logged_in(curator).get(f"{DEPOSITORS_URL}{depositor.public_id}/").json()
    assert (row["name"], row["email"], row["postal_address"], row["erased"]) == ("", "", "", True)
    response = logged_in(curator).put(
        f"{DEPOSITORS_URL}{depositor.public_id}/", {"name": "Back"}, content_type="application/json"
    )
    assert_problem(response, 409, "contact_erased")


def test_a_manager_publishes_a_new_version_and_its_text_is_returned(
    *, manager: User, curator: User, mta: MtaTemplate
) -> None:
    response = post(
        manager, MTA_URL, {"code": "std", "title": "Standard MTA", "text": "  Version two.\r\n"}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["code"], body["version"], body["text"]) == ("STD", 2, "Version two.")
    assert body["text_sha256"] == services.sha256_of("Version two.")
    listed = logged_in(curator).get(MTA_URL).json()["results"]
    assert [(t["code"], t["version"]) for t in listed] == [("STD", 2), ("STD", 1)]
    assert "text" not in listed[0]  # the list carries no texts, the detail does
    assert_problem(
        post(manager, MTA_URL, {"code": "s t d", "title": "T", "text": "x"}),
        400,
        "invalid",
        attr="code",
    )


# Filters and order.


def test_the_status_filter_and_search_narrow_within_the_lab(
    *, curator: User, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    received = make_deposit(name_as_received="first one")
    checking = make_deposit("checking", name_as_received="second one")
    accepted = make_deposit("accepted", taxon=exempli, name_as_received="third one")

    def ids(**params: str) -> list[str]:
        rows = logged_in(curator).get(DEPOSITS_URL, params).json()["results"]
        return [row["public_id"] for row in rows]

    assert ids(status="checking") == [str(checking.public_id)]
    assert ids(status="received") == [str(received.public_id)]
    assert ids(search="third") == [str(accepted.public_id)]
    assert ids(search="MYC 1") == [str(accepted.public_id)]  # the strain's number
    assert ids(search="Vzorov") == [str(d.public_id) for d in (accepted, checking, received)]
    assert_problem(logged_in(curator).get(DEPOSITS_URL, {"status": "lost"}), 400, "invalid")


def test_the_newest_receipt_comes_first_and_pages_neither_repeat_nor_skip(
    *, curator: User, make_deposit: MakeDeposit
) -> None:
    made = [
        make_deposit(received_on=date(2026, 9, 1 + i % 3), name_as_received=f"d{i}")
        for i in range(7)
    ]
    pages = [
        logged_in(curator).get(DEPOSITS_URL, {"limit": 3, "offset": n}).json()["results"]
        for n in (0, 3, 6)
    ]
    seen = [row["public_id"] for page in pages for row in page]
    assert sorted(seen) == sorted(str(d.public_id) for d in made)
    days = [row["received_on"] for page in pages for row in page]
    assert days == sorted(days, reverse=True)


def test_depositors_are_found_by_name_or_institution(
    *, curator: User, make_depositor: MakeDepositor
) -> None:
    a = make_depositor(contact=ContactInput("Alena Vzorová"), institution="Example University")
    b = make_depositor(contact=ContactInput("Bohdan Příklad"), institution="Example Institute")
    rows = logged_in(curator).get(DEPOSITORS_URL, {"search": "institute"}).json()["results"]
    assert [r["public_id"] for r in rows] == [str(b.public_id)]
    rows = logged_in(curator).get(DEPOSITORS_URL).json()["results"]
    assert [r["public_id"] for r in rows] == [str(a.public_id), str(b.public_id)]


# Exact, flat query counts, with the lab scope in the SQL.


def scoped(queries: list[dict[str, str]], table: str) -> list[str]:
    return [
        q["sql"]
        for q in queries
        if f'FROM "{table}"' in q["sql"] and f'"{table}"."lab_id" IN (' in q["sql"]
    ]


@pytest.mark.parametrize("rows", [1, 20])
def test_the_deposit_list_query_count_is_exact_and_flat(
    *,
    rows: int,
    curator: User,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    query_baseline: QueryBaseline,
) -> None:
    for i in range(rows):
        make_deposit("accepted" if i % 2 else "received", taxon=exempli)
    client = logged_in(curator)
    # Session, user, memberships, the lab, count, the page with depositor, contact and strain.
    with query_baseline("deposit_list") as captured:
        response = client.get(DEPOSITS_URL)
    assert response.json()["count"] == rows
    assert scoped(captured.captured_queries, "deposits_deposit")


@pytest.mark.parametrize("versions", [1, 5])
def test_the_deposit_detail_query_count_is_exact_and_flat(
    *,
    versions: int,
    curator: User,
    make_deposit: MakeDeposit,
    mta: MtaTemplate,
    query_baseline: QueryBaseline,
) -> None:
    deposit = make_deposit()
    for _ in range(versions - 1):
        post(
            curator,
            f"{DEPOSITS_URL}{deposit.public_id}/terms/",
            {"terms": terms_body(mta=str(mta.public_id)), "reason": "corrected"},
        )
    client = logged_in(curator)
    with query_baseline("deposit_detail"):
        response = client.get(f"{DEPOSITS_URL}{deposit.public_id}/")
    assert len(response.json()["terms_history"]) == versions


@pytest.mark.parametrize("rows", [1, 20])
def test_the_depositor_and_mta_lists_are_exact_and_flat(
    *,
    rows: int,
    curator: User,
    manager: User,
    lab: Lab,
    make_depositor: MakeDepositor,
    query_baseline: QueryBaseline,
) -> None:
    for i in range(rows):
        make_depositor()
        with as_actor(manager):
            services.mta_template_publish(
                access=access_for(manager), lab=lab, code=f"M{i}", title="T", text="x"
            )
    client = logged_in(curator)
    with query_baseline("depositor_list") as captured:
        assert client.get(DEPOSITORS_URL).json()["count"] == rows
    assert scoped(captured.captured_queries, "deposits_depositor")
    with query_baseline("mta_template_list") as captured:
        assert client.get(MTA_URL).json()["count"] == rows
    assert scoped(captured.captured_queries, "deposits_mtatemplate")
