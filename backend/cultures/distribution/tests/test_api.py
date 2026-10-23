"""What the distribution APIs answer: the bodies (a request's lines, findings, reserved vials by
label, acceptances that name a signer only to those who may see people), the server errors a
form maps onto its fields, the files, the filters and exact query counts."""

from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from cultures.audit.context import AuditContext
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits.tests.support import DUAL_USE
from cultures.distribution import services
from cultures.distribution.models import DistributionRequest, PermitKind, Requester
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    PDF,
    PERMITS_URL,
    REQUESTERS_URL,
    REQUESTS_URL,
    MakeRequester,
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    prepare,
    reserved,
    ship,
    submit,
)

pytestmark = pytest.mark.django_db


def post(user: User, url: str, body: dict[str, Any]) -> Any:
    return logged_in(user).post(url, body, content_type="application/json")


def detail(request: DistributionRequest) -> str:
    return f"{REQUESTS_URL}{request.public_id}/"


def test_a_curator_enters_a_request_and_sees_what_blocks_it(
    *, curator: User, requester: Requester, supply: Supply, lab: Lab
) -> None:
    strain = supply(vials=2)
    response = post(
        curator,
        REQUESTS_URL,
        {
            "requester": str(requester.public_id),
            "use": "research_noncommercial",
            "end_use": "Teaching of antibiotic testing.",
            "containment_level": 2,
            "lines": [{"strain": str(strain.public_id), "quantity": 3}],
        },
    )
    assert response.status_code == 201, response.content
    body = response.json()
    line = body["lines"][0]
    assert (body["number"], body["status"], body["destination_country"]) == (
        f"{DistributionRequest.objects.get().year}/1",
        "submitted",
        "CZ",
    )
    assert body["requester"] == {
        "public_id": str(requester.public_id),
        "institution": "Example Institute of Microbiology",
        "country": "CZ",
    }
    assert (body["line_count"], body["vial_count"], body["regulated"]) == (1, 3, False)
    assert line["strain"]["accession_number"] == strain.accession_number
    assert (line["quantity"], line["terms_version"], line["mta"]["code"]) == (3, 1, "STD")
    assert line["reserved"] == line["permits"] == []
    assert [(f["code"], f["severity"], f["line"]) for f in body["findings"]] == [
        ("not_enough_vials", "block", line["public_id"]),
        ("mta_not_accepted", "block", line["public_id"]),
    ]
    assert body["findings"][0]["sentence"].startswith(f"{strain.accession_number}: 2 vials")


def test_approval_answers_the_reserved_vials_by_label_and_no_findings(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply()
    request = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, request)
    response = post(curator, f"{detail(request)}approve/", {})
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["status"], body["decided_by"], body["findings"]) == ("approved", "curator", [])
    labels = [v["label"] for v in body["lines"][0]["reserved"]]
    assert labels == [f"{strain.accession_number} / 1 / {v.seq}" for v in reserved(request)]
    assert "location" not in str(body)


def test_a_blocked_approval_is_422_and_a_regulated_one_needs_a_manager(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    blocked = submit(curator, lab, requester, [(supply(), 1)])
    response = post(curator, f"{detail(blocked)}approve/", {})
    assert_problem(response, 422, "request_blocked")
    assert "MTA STD version 1" in response.json()["detail"]
    regulated = submit(curator, lab, requester, [(supply(mockia, restrictions=[DUAL_USE]), 1)])
    accept_mtas(curator, regulated)
    assert_problem(
        post(curator, f"{detail(regulated)}approve/", {"reason": "ok"}),
        403,
        "manager_approval_required",
    )
    assert_problem(post(manager, f"{detail(regulated)}approve/", {}), 422, "reason_required")
    done = post(manager, f"{detail(regulated)}approve/", {"reason": "Inside the EU."})
    assert (done.status_code, done.json()["decision_reason"]) == (200, "Inside the EU.")
    assert_problem(
        post(manager, f"{detail(regulated)}approve/", {"reason": "x"}), 409, "request_state"
    )


def test_reject_and_cancel_need_a_reason_on_their_field(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    for action in ("reject/", "cancel/"):
        assert_problem(
            post(curator, f"{detail(request)}{action}", {"reason": ""}),
            400,
            "invalid",
            attr="reason",
        )
    response = post(curator, f"{detail(request)}cancel/", {"reason": "duplicate"})
    assert (
        response.json()["status"],
        response.json()["cancelled_by"],
        response.json()["cancel_reason"],
    ) == (
        "cancelled",
        "curator",
        "duplicate",
    )


def test_a_request_to_a_requester_outside_the_eu_is_refused_at_entry(
    curator: User, make_requester: MakeRequester, supply: Supply
) -> None:
    abroad = make_requester(country="US")
    response = post(
        curator,
        REQUESTS_URL,
        {
            "requester": str(abroad.public_id),
            "use": "research_noncommercial",
            "end_use": "Research.",
            "containment_level": 2,
            "lines": [{"strain": str(supply().public_id), "quantity": 1}],
        },
    )
    assert_problem(response, 422, "export_not_supported", attr="requester")


def test_input_from_another_lab_is_unknown_here(
    *, curator: User, other_lab: Lab, outsider: User, make_requester: MakeRequester, supply: Supply
) -> None:
    foreign = make_requester(lab=other_lab, actor=outsider)
    body = {
        "requester": str(foreign.public_id),
        "use": "teaching",
        "end_use": "Teaching.",
        "containment_level": 1,
        "lines": [{"strain": str(supply().public_id), "quantity": 1}],
    }
    assert_problem(post(curator, REQUESTS_URL, body), 400, "invalid", attr="requester")


def test_a_viewer_reads_a_request_without_the_people_or_their_files(
    *,
    as_curator: AuditContext,
    curator: User,
    viewer: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    accept_mtas(curator, request)
    seen = logged_in(viewer).get(detail(request)).json()["acceptances"][0]
    assert (seen["signer_name"], seen["document"]) == (None, None)
    assert seen["signer_role"] == "head_of_institution"
    full = logged_in(curator).get(detail(request)).json()["acceptances"][0]
    assert full["signer_name"] == "Karel Podpisový"
    assert full["document"]["content_type"] == "application/pdf"
    body = str(logged_in(viewer).get(detail(request)).json())
    assert "Petra" not in body and "Testovací" not in body


def test_a_permit_is_sent_with_its_file_and_the_file_comes_back_as_an_attachment(
    curator: User, requester: Requester
) -> None:
    client = logged_in(curator)
    response = client.post(
        PERMITS_URL,
        {
            "requester": str(requester.public_id),
            "kind": "plant_health_loa",
            "issuer": "ÚKZÚZ",
            "issuer_country": "CZ",
            "reference": "LoA DEV/1 (invented example)",
            "valid_from": "2026-01-01",
            "covers": "Mockia vulgaris",
            "quantity_allowed": "4",
            "sendings_allowed": "2",
            "file": SimpleUploadedFile("letter.pdf", PDF, "application/pdf"),
        },
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["kind"], body["quantity_allowed"], body["valid_today"]) == (
        "plant_health_loa",
        4,
        True,
    )
    document = client.get(
        f"/api/v1/labs/{requester.lab.public_id}/documents/{body['document']['public_id']}/"
    )
    assert document.status_code == 200
    assert document.content == PDF
    assert (
        document["Content-Type"],
        document["Cache-Control"],
        document["X-Content-Type-Options"],
    ) == (
        "application/pdf",
        "no-store",
        "nosniff",
    )
    assert document["Content-Disposition"].startswith("attachment;")
    requester_body = client.get(f"{REQUESTERS_URL}{requester.public_id}/").json()
    assert [p["reference"] for p in requester_body["permits"]] == ["LoA DEV/1 (invented example)"]


@pytest.mark.parametrize(
    ("content", "name"),
    [(b"<html><script>", "letter.pdf"), (b"", "empty.pdf"), (b"GIF89a", "image.gif")],
)
def test_a_file_that_is_not_a_pdf_png_or_jpeg_is_refused_on_its_field(
    curator: User, requester: Requester, content: bytes, name: str
) -> None:
    response = logged_in(curator).post(
        PERMITS_URL,
        {
            "requester": str(requester.public_id),
            "kind": "sujb_rat_notice",
            "issuer": "SÚJB",
            "issuer_country": "CZ",
            "reference": "R/1",
            "valid_from": "2026-01-01",
            "file": SimpleUploadedFile(name, content, "application/pdf"),
        },
    )
    assert_problem(response, 400, "invalid", attr="file")


def test_an_acceptance_is_sent_with_the_signed_copy(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    mta = request.lines.get().mta
    assert mta is not None
    response = logged_in(curator).post(
        f"{detail(request)}acceptances/",
        {
            "mta": str(mta.public_id),
            "signer_name": "Karel Podpisový",
            "signer_role": "responsible_scientist",
            "authorised_signatory": "true",
            "accepted_on": "2026-10-02",
            "file": SimpleUploadedFile("signed.pdf", PDF, "application/pdf"),
        },
    )
    assert response.status_code == 201, response.content
    assert [f["code"] for f in response.json()["findings"]] == []


REQUESTER = {
    "institution": "Example Seat Institute",
    "legal_form": "legal_person",
    "country": "CZ",
    "lab_evidence": "Seen on the department page.",
    "lab_confirmed_on": "2026-10-01",
    "name": "Petra Ukázková",
    "postal_address": "Testovací 5, Brno",
}


def test_a_requester_is_entered_and_read_with_its_seat(curator: User) -> None:
    created = post(curator, REQUESTERS_URL, {**REQUESTER, "seat": " Vzorová 12,  Brno "})
    assert created.status_code == 201, created.content
    assert created.json()["seat"] == "Vzorová 12, Brno"
    read = logged_in(curator).get(f"{REQUESTERS_URL}{created.json()['public_id']}/").json()
    assert (read["seat"], read["postal_address"]) == ("Vzorová 12, Brno", "Testovací 5, Brno")


def test_a_requester_without_a_seat_is_entered_with_none(curator: User) -> None:
    created = post(curator, REQUESTERS_URL, REQUESTER)
    assert created.status_code == 201, created.content
    assert created.json()["seat"] == ""
    assert Requester.objects.get(public_id=created.json()["public_id"]).seat == ""


def test_a_seat_longer_than_300_characters_is_refused_on_its_field(curator: User) -> None:
    response = post(curator, REQUESTERS_URL, {**REQUESTER, "seat": "x" * 301})
    assert_problem(response, 400, "invalid", attr="seat")
    assert not Requester.objects.filter(institution="Example Seat Institute").exists()


def test_the_requester_form_errors_name_their_field(curator: User) -> None:
    response = post(
        curator,
        REQUESTERS_URL,
        {
            "institution": "Example",
            "legal_form": "private_person",
            "country": "CZ",
            "lab_evidence": "x",
            "lab_confirmed_on": "2026-01-01",
            "name": "Petra",
            "postal_address": "",
        },
    )
    body = response.json()
    assert response.status_code == 400
    assert {e["attr"] for e in body["errors"]} == {"legal_form", "postal_address"}


def test_the_status_filter_and_search_narrow_within_the_lab(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    make_requester: MakeRequester,
    supply: Supply,
) -> None:
    strain = supply()
    first = submit(curator, lab, requester, [(strain, 1)])
    other = make_requester(institution="Second Laboratory")
    second = submit(curator, lab, other, [(strain, 1)])
    client = logged_in(curator)
    services.request_reject(access=access_for(curator), request=first, reason="no lab")

    def numbers(query: str) -> list[str]:
        return [r["number"] for r in client.get(f"{REQUESTS_URL}?{query}").json()["results"]]

    assert numbers("") == [second.label, first.label]  # newest first
    assert numbers("status=rejected") == [first.label]
    assert numbers("search=second") == [second.label]
    assert numbers(f"search={first.year}/{first.number}") == [first.label]
    assert numbers(f"search={strain.accession_number}") == [second.label, first.label]
    assert numbers(f"requester={other.public_id}") == [second.label]
    assert numbers("status=shipped") == []
    assert_problem(client.get(f"{REQUESTS_URL}?status=lost"), 400, "invalid", attr="status")


def scoped(queries: list[dict[str, str]], table: str) -> list[str]:
    return [
        q["sql"]
        for q in queries
        if f'FROM "{table}"' in q["sql"] and f'"{table}"."lab_id" IN (' in q["sql"]
    ]


@pytest.mark.parametrize("rows", [1, 20])
def test_the_request_list_query_count_is_exact_and_flat(
    *,
    rows: int,
    viewer: User,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    query_baseline: QueryBaseline,
) -> None:
    strain = supply()
    with as_actor(curator):
        for _ in range(rows):
            submit(curator, lab, requester, [(strain, 1)])
    client = logged_in(viewer)
    # Session, user, memberships, the lab, count, the page with requester and the counts.
    with query_baseline("request_list") as captured:
        response = client.get(REQUESTS_URL)
    assert response.json()["count"] == rows
    assert scoped(captured.captured_queries, "distribution_distributionrequest")


@pytest.mark.parametrize("lines", [1, 4])
def test_the_request_detail_query_count_is_exact_and_flat(
    *,
    lines: int,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    exempli: Taxon,
    query_baseline: QueryBaseline,
) -> None:
    strains = [supply(mockia if i % 2 else exempli) for i in range(lines)]
    with as_actor(curator):
        request = submit(curator, lab, requester, [(s, 1) for s in strains])
        accept_mtas(curator, request)
        add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    client = logged_in(curator)
    with query_baseline("request_detail"):
        response = client.get(detail(request))
    assert len(response.json()["lines"]) == lines
    with as_actor(curator):
        approve(curator, request)
    with query_baseline("request_detail_approved"):
        response = client.get(detail(request))
    assert sum(len(line["reserved"]) for line in response.json()["lines"]) == lines
    ship(curator, request)
    with query_baseline("request_detail_shipped"):
        response = client.get(detail(request))
    assert sum(len(line["shipped"]) for line in response.json()["lines"]) == lines


@pytest.mark.parametrize("rows", [1, 20])
def test_the_requester_and_permit_lists_are_exact_and_flat(
    *,
    rows: int,
    curator: User,
    make_requester: MakeRequester,
    query_baseline: QueryBaseline,
) -> None:
    for i in range(rows):
        requester = make_requester(institution=f"Institute {i}")
        with as_actor(curator):
            add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    client = logged_in(curator)
    with query_baseline("requester_list") as captured:
        assert client.get(REQUESTERS_URL).json()["count"] == rows
    assert scoped(captured.captured_queries, "distribution_requester")
    with query_baseline("permit_list") as captured:
        assert client.get(PERMITS_URL).json()["count"] == rows
    assert scoped(captured.captured_queries, "distribution_recipientpermit")


def test_a_cancelled_request_shows_no_vial_as_reserved(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    response = post(curator, f"{detail(request)}cancel/", {"reason": "withdrawn"})
    assert response.json()["lines"][0]["reserved"] == []
    assert logged_in(curator).get(detail(request)).json()["lines"][0]["reserved"] == []


SHIP_BODY = {
    "transport_class": "un3373",
    "classification_basis": "professional_judgement",
    "basis_note": "Risk group 1, shipped as Category B on the safe side.",
    "packing_instruction": "p650",
    "coolant": "dry_ice",
    "coolant_kg": "2.50",
    "responsible_name": "Jan Odpovědný",
    "responsible_phone": "+420 555 000 111",
    "carrier": "Example Courier (invented example)",
    "tracking_number": "EX123456789CZ",
}


def test_a_curator_ships_and_the_request_shows_the_shipment_and_the_vials_sent(
    *,
    as_curator: AuditContext,
    curator: User,
    viewer: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    request = submit(curator, lab, requester, [(supply(vials=6), 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    labels = sorted(
        f"{v.batch.strain.accession_number} / {v.batch.number} / {v.seq}" for v in reserved(request)
    )
    response = post(curator, f"{detail(request)}ship/", SHIP_BODY)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "shipped"
    assert body["lines"][0]["reserved"] == []
    assert sorted(v["label"] for v in body["lines"][0]["shipped"]) == labels
    shipment = body["shipment"]
    assert {k: shipment[k] for k in SHIP_BODY if k != "coolant_kg"} == {
        k: v for k, v in SHIP_BODY.items() if k != "coolant_kg"
    }
    assert (shipment["coolant_kg"], shipment["shipped_by"], shipment["classified_by"]) == (
        "2.50",
        curator.username,
        curator.username,
    )
    # A viewer reads the shipment, never the person who answers for it.
    seen = logged_in(viewer).get(detail(request)).json()["shipment"]
    assert (seen["responsible_name"], seen["responsible_phone"]) == (None, None)
    assert seen["carrier"] == SHIP_BODY["carrier"]
    assert_problem(post(curator, f"{detail(request)}ship/", SHIP_BODY), 409, "request_state")


def test_a_request_not_shipped_has_no_shipment(
    *, as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    body = logged_in(curator).get(detail(request)).json()
    assert body["shipment"] is None
    assert body["lines"][0]["shipped"] == []


def test_a_refused_shipment_answers_its_code_on_its_field(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    request = submit(curator, lab, requester, [(supply(vials=6), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    url = f"{detail(request)}ship/"
    for changes, attr, code in (
        ({"transport_class": "un2814"}, "transport_class", "invalid"),
        ({"packing_instruction": "triple_packaging"}, "packing_instruction", "invalid"),
        ({"responsible_phone": "ask at the desk"}, "responsible_phone", "invalid"),
        ({"basis_note": ""}, "basis_note", "required"),
        ({"coolant_kg": None}, "coolant_kg", "required"),
    ):
        response = post(curator, url, {**SHIP_BODY, **changes})
        assert_problem(response, 400, code, attr=attr)
    regulated = submit(curator, lab, requester, [(supply(mockia, restrictions=[DUAL_USE]), 1)])
    accept_mtas(curator, regulated)
    approve(manager, regulated, "Dual-use inside the EU.")
    response = post(curator, f"{detail(regulated)}ship/", SHIP_BODY)
    assert_problem(response, 422, "second_person_required")


# The two-person shipment (#89).


def test_a_curator_prepares_a_regulated_request_and_a_manager_confirms_it(
    *,
    curator: User,
    manager: User,
    approver: User,
    viewer: User,
    regulated: Regulated,
) -> None:
    request = regulated(2)
    labels = sorted(
        f"{v.batch.strain.accession_number} / {v.batch.number} / {v.seq}" for v in reserved(request)
    )
    response = post(curator, f"{detail(request)}prepare-shipment/", SHIP_BODY)
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["status"], body["shipment"]) == ("awaiting_confirmation", None)
    assert sorted(v["label"] for v in body["lines"][0]["reserved"]) == labels
    [prepared] = body["preparations"]
    assert {k: prepared[k] for k in SHIP_BODY if k != "coolant_kg"} == {
        k: v for k, v in SHIP_BODY.items() if k != "coolant_kg"
    }
    assert (prepared["prepared_by"], prepared["withdrawn_at"]) == (curator.username, None)
    # The preparer may not confirm, and is told why; so is the approver; the manager may.
    assert prepared["confirm_refusal"] == "confirm_own_preparation"
    refusals = {
        user.username: logged_in(user)
        .get(detail(request))
        .json()["preparations"][0]["confirm_refusal"]
        for user in (approver, manager)
    }
    assert refusals == {approver.username: "confirm_own_approval", manager.username: None}
    seen = logged_in(viewer).get(detail(request)).json()["preparations"][0]
    assert (seen["responsible_name"], seen["responsible_phone"]) == (None, None)

    url = f"{detail(request)}confirm-shipment/"
    assert_problem(
        post(curator, url, {"preparation": prepared["public_id"]}), 403, "confirm_own_preparation"
    )
    assert_problem(
        post(approver, url, {"preparation": prepared["public_id"]}), 403, "confirm_own_approval"
    )
    assert_problem(
        post(manager, url, {"preparation": str(request.public_id)}), 409, "preparation_changed"
    )
    assert_problem(post(manager, url, {}), 400, "invalid", attr="preparation")
    response = post(manager, url, {"preparation": prepared["public_id"]})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "shipped"
    assert sorted(v["label"] for v in body["lines"][0]["shipped"]) == labels
    shipment = body["shipment"]
    assert (
        shipment["preparation"],
        shipment["classified_by"],
        shipment["shipped_by"],
        shipment["classified_at"],
    ) == (prepared["public_id"], curator.username, manager.username, prepared["prepared_at"])


def test_a_withdrawal_needs_its_reason_and_keeps_the_preparation(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    url = f"{detail(request)}withdraw-shipment/"
    assert_problem(post(manager, url, {"reason": " "}), 400, "invalid", attr="reason")
    response = post(manager, url, {"reason": "The courier cannot come this week."})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "approved"
    [kept] = body["preparations"]
    assert (kept["withdrawn_by"], kept["withdraw_reason"]) == (
        manager.username,
        "The courier cannot come this week.",
    )
    assert_problem(post(manager, url, {"reason": "again"}), 409, "request_state")


def test_the_preparations_come_newest_first_so_the_open_one_leads(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    post(manager, f"{detail(request)}withdraw-shipment/", {"reason": "Wrong carrier."})
    body = post(curator, f"{detail(request)}prepare-shipment/", SHIP_BODY).json()
    assert [p["withdrawn_at"] is None for p in body["preparations"]] == [True, False]
    assert body["preparations"][0]["prepared_at"] > body["preparations"][1]["prepared_at"]


def test_an_approver_who_prepared_is_told_the_approval_bars_them(
    *, approver: User, regulated: Regulated
) -> None:
    """The service refuses the approval first (confirm_own_approval); the page says the same."""
    request = regulated(prepared_by=approver)
    seen = logged_in(approver).get(detail(request)).json()["preparations"][0]
    assert seen["confirm_refusal"] == "confirm_own_approval"


def test_preparing_an_unregulated_request_is_refused_with_its_code(
    *, as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(vials=6), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    response = post(curator, f"{detail(request)}prepare-shipment/", SHIP_BODY)
    assert_problem(response, 422, "ship_in_one_step")


def test_the_detail_of_a_request_awaiting_confirmation_has_an_exact_query_count(
    *, curator: User, manager: User, regulated: Regulated, query_baseline: QueryBaseline
) -> None:
    request = regulated(prepared_by=curator)
    with as_actor(curator):
        services.request_withdraw_shipment(access=access_for(curator), request=request, reason="r")
    prepare(curator, request)
    client = logged_in(manager)
    with query_baseline("request_detail_awaiting"):
        response = client.get(detail(request))
    assert len(response.json()["preparations"]) == 2
