"""The documents of a shipment through the API (#90): every reader of a request sees which
exist, with their SHA-256; only a caller who may view requesters reads one, as it was stored."""

from typing import Any

import pytest

from cultures.audit.context import AuditContext
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.distribution import documents
from cultures.distribution.models import DistributionRequest, Requester, ShipmentDocument
from cultures.labs.models import Lab
from cultures.users.models import User

from .support import LAB_URL, REQUESTS_URL, Supply, accept_mtas, approve, ship, submit

pytestmark = pytest.mark.django_db

DOCUMENTS = f"{LAB_URL}/shipment-documents/"


@pytest.fixture
def shipped(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> DistributionRequest:
    request = submit(curator, lab, requester, [(supply(vials=6), 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    return ship(curator, request)


def test_every_reader_of_a_request_sees_its_documents_without_their_text(
    shipped: DistributionRequest, viewer: User, technician: User, curator: User
) -> None:
    document = ShipmentDocument.objects.get(shipment__request=shipped)
    for user in (viewer, technician, curator):
        shown = logged_in(user).get(f"{REQUESTS_URL}{shipped.public_id}/").json()["shipment"]
        assert shown["documents"] == [
            {
                "public_id": str(document.public_id),
                "kind": "delivery_note",
                "strain": None,
                "text_sha256": document.text_sha256,
                "created_at": shown["documents"][0]["created_at"],
            }
        ]
        assert "text" not in shown["documents"][0]


def test_a_curator_reads_the_stored_text_and_downloads_it(
    shipped: DistributionRequest, curator: User
) -> None:
    document = ShipmentDocument.objects.get(shipment__request=shipped)
    response = logged_in(curator).get(f"{DOCUMENTS}{document.public_id}/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["text"] == document.text
    assert (body["request"], body["request_number"]) == (str(shipped.public_id), shipped.label)
    assert body["kind"] == "delivery_note"
    download = logged_in(curator).get(f"{DOCUMENTS}{document.public_id}/download/")
    assert download.status_code == 200
    assert download.content.decode() == document.text
    assert download["Content-Type"] == "text/plain; charset=utf-8"
    assert download["Content-Disposition"] == (
        f'attachment; filename="delivery_note-{document.public_id}.txt"'
    )
    assert (download["Cache-Control"], download["X-Content-Type-Options"]) == (
        "no-store",
        "nosniff",
    )


def test_viewers_and_technicians_read_no_document(
    shipped: DistributionRequest, viewer: User, technician: User, outsider: User
) -> None:
    document = ShipmentDocument.objects.get(shipment__request=shipped)
    for user in (viewer, technician, outsider):
        for tail in ("", "download/"):
            assert_problem(
                logged_in(user).get(f"{DOCUMENTS}{document.public_id}/{tail}"), 404, "not_found"
            )


def test_reading_a_document_is_one_query_after_the_access(
    shipped: DistributionRequest, curator: User, query_baseline: QueryBaseline
) -> None:
    document = ShipmentDocument.objects.get(shipment__request=shipped)
    client = logged_in(curator)
    with query_baseline("shipment_document"):
        response = client.get(f"{DOCUMENTS}{document.public_id}/")
    assert response.status_code == 200


def test_reading_a_document_never_renders_it(
    shipped: DistributionRequest, curator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing renders a document at read time: the view never calls the renderer."""

    def refuse(*args: Any) -> str:
        raise AssertionError("a read rendered a document")

    monkeypatch.setattr(documents, "delivery_note", refuse)
    monkeypatch.setattr(documents, "render", refuse)
    document = ShipmentDocument.objects.get(shipment__request=shipped)
    assert logged_in(curator).get(f"{DOCUMENTS}{document.public_id}/").json()["text"] == (
        document.text
    )
