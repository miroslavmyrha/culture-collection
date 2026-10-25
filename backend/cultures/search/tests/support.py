"""Helpers of the search tests: the search as a person sees it."""

from typing import Any

from cultures.core.testing import logged_in
from cultures.users.models import User

SEARCH_URL = "/api/v1/me/search/"


def search(user: User, text: str) -> dict[str, Any]:
    response = logged_in(user).get(SEARCH_URL, {"q": text})
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


def groups(user: User, text: str) -> dict[str, dict[str, Any]]:
    """The groups by kind."""
    return {group["kind"]: group for group in search(user, text)["groups"]}


def ids(user: User, text: str) -> dict[str, set[str]]:
    """The public ids found, by kind."""
    return {
        kind: {hit["public_id"] for hit in group["hits"]}
        for kind, group in groups(user, text).items()
    }
