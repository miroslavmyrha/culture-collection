import json
from http import HTTPStatus
from typing import Any

# The wire value the frontend depends on, spelled out. Importing the constant from
# core.errors would make the check follow a change of it.
PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_KEYS = {"type", "title", "status", "detail", "code", "errors"}


def assert_problem(
    response: Any, status: int, code: str, attr: str | None = None
) -> dict[str, Any]:
    """The API's one error shape (core.errors): problem details with a stable code.

    Checks the content type, the keys, type "about:blank", the title of the
    status, the status and the code. With attr, one of the field errors must
    name that field. Returns the body.
    """
    assert response.status_code == status, response.content
    assert response["Content-Type"] == PROBLEM_CONTENT_TYPE
    body: dict[str, Any] = json.loads(response.content)
    assert set(body) == PROBLEM_KEYS, body
    assert (body["status"], body["code"]) == (status, code), body
    assert (body["type"], body["title"]) == ("about:blank", HTTPStatus(status).phrase), body
    if attr is not None:
        assert attr in [error["attr"] for error in body["errors"]], body["errors"]
    return body
