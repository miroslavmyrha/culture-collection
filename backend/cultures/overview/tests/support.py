"""Helpers of the overview tests: Home's two reads as a person sees them."""

from typing import Any

from cultures.core.testing import logged_in
from cultures.users.models import User

OVERVIEW_URL = "/api/v1/me/overview/"
ACTIVITY_URL = "/api/v1/me/activity/"


def overview(user: User) -> dict[str, Any]:
    response = logged_in(user).get(OVERVIEW_URL)
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


def waiting(user: User) -> dict[str, list[dict[str, Any]]]:
    """The waiting items by kind."""
    return {group["kind"]: group["items"] for group in overview(user)["waiting"]}


def subjects(user: User, kind: str) -> list[str]:
    return [item["subject"] for item in waiting(user).get(kind, [])]


def lines(user: User) -> list[dict[str, Any]]:
    response = logged_in(user).get(ACTIVITY_URL)
    assert response.status_code == 200, response.content
    results: list[dict[str, Any]] = response.json()["results"]
    return results
