"""The uses a MAT covers (ADR 0008, amendment of 2026-10-20, #18): stored on the terms version,
only for material in scope of Regulation (EU) No 511/2014, in the vocabulary's order, in the
event and in the API."""

from typing import Any

import pytest
from django.db import IntegrityError, transaction

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.core.testing import assert_problem, logged_in
from cultures.deposits import services
from cultures.deposits.models import AbsScope, Deposit, DepositTerms, Use
from cultures.deposits.services import InvalidDeposit
from cultures.labs.access import Access
from cultures.users.models import User

from .support import DEPOSITS_URL, MakeDeposit, terms, terms_body

pytestmark = pytest.mark.django_db

IN_SCOPE = {"abs_scope": AbsScope.IN_SCOPE, "ircc": "ABSCH-IRCC-XX-1"}


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
        ({"mat_uses": [Use.TEACHING]}, "deposits_depositterms_mat_uses_in_scope_only"),
        (
            {"abs_scope": AbsScope.UNKNOWN, "mat_uses": [Use.TEACHING]},
            "deposits_depositterms_mat_uses_in_scope_only",
        ),
        ({**IN_SCOPE, "mat_uses": ["fishing"]}, "deposits_depositterms_mat_uses_valid"),
    ],
)
def test_the_database_holds_mat_uses_to_material_in_scope_and_the_vocabulary(
    make_deposit: MakeDeposit, fields: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError) as raised:
        raw_terms(make_deposit(), **fields)
    assert raised.value.__cause__.diag.constraint_name == constraint  # type: ignore[union-attr]


def test_material_in_scope_may_list_mat_uses_or_none(make_deposit: MakeDeposit) -> None:
    deposit = make_deposit()
    raw_terms(deposit, **IN_SCOPE, mat_uses=[Use.TEACHING, Use.RESEARCH_NONCOMMERCIAL])
    raw_terms(deposit, **IN_SCOPE, version=10, mat_uses=[])
    assert DepositTerms.objects.get(version=1).mat_uses == []  # what every older version holds


def test_new_terms_keep_the_mat_uses_in_the_vocabulary_order_and_record_them(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit
) -> None:
    deposit = make_deposit()
    added = services.deposit_terms_replace(
        access=curator_access,
        deposit=deposit,
        terms=terms(**IN_SCOPE, mat_uses=[Use.TEACHING, Use.RESEARCH_NONCOMMERCIAL, Use.TEACHING]),
        reason="the MAT arrived",
    )
    added.refresh_from_db()
    assert added.mat_uses == [Use.RESEARCH_NONCOMMERCIAL, Use.TEACHING]
    event = AuditEvent.objects.latest("pk")
    assert event.changes["terms"][1]["mat_uses"] == ["research_noncommercial", "teaching"]


@pytest.mark.parametrize("scope", [AbsScope.NOT_IN_SCOPE, AbsScope.UNKNOWN])
def test_mat_uses_outside_the_scope_are_refused_on_their_field(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    make_deposit: MakeDeposit,
    scope: AbsScope,
) -> None:
    deposit = make_deposit()
    with pytest.raises(InvalidDeposit) as raised:
        services.deposit_terms_replace(
            access=curator_access,
            deposit=deposit,
            terms=terms(abs_scope=scope, mat_uses=[Use.TEACHING]),
            reason="r",
        )
    assert raised.value.attr == "terms.mat_uses"
    assert deposit.terms.count() == 1


def test_the_api_takes_and_answers_the_mat_uses(curator: User, make_deposit: MakeDeposit) -> None:
    deposit = make_deposit()
    url = f"{DEPOSITS_URL}{deposit.public_id}/terms/"
    client = logged_in(curator)
    body = terms_body(abs_scope="in_scope", ircc="ABSCH-IRCC-XX-1", mat_uses=["teaching"])
    answer = client.post(url, {"terms": body, "reason": "MAT"}, content_type="application/json")
    assert answer.status_code == 200, answer.content
    assert answer.json()["terms"]["mat_uses"] == ["teaching"]
    assert [t["mat_uses"] for t in answer.json()["terms_history"]] == [["teaching"], []]
    refused = client.post(
        url,
        {"terms": terms_body(mat_uses=["teaching"]), "reason": "MAT"},
        content_type="application/json",
    )
    assert_problem(refused, 400, "invalid", attr="terms.mat_uses")
    unknown = client.post(
        url,
        {"terms": terms_body(abs_scope="in_scope", ircc="X", mat_uses=["fishing"]), "reason": "r"},
        content_type="application/json",
    )
    assert_problem(unknown, 400, "invalid", attr="terms.mat_uses.0")
