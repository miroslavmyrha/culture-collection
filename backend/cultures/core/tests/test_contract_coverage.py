"""Every routed API view of the project has a ViewsetContract test class or a reviewed exemption.

A viewset gets its contract in <app>/tests/test_contract.py (any test_*.py works).
EXEMPT is for views the contract does not fit: no object scope, anonymous by
design. Each entry names the URL of the view and the test file that covers it,
and that file must call the URL, so an exemption cannot claim tests that do not
exist. Adding one is a review decision, like a new permission.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest
from django.urls import resolve, reverse

import cultures
from cultures.core.testing.contract import COVERED, import_test_modules, routed_api_views

PACKAGE = Path(cultures.__file__).parent


@dataclass(frozen=True)
class Exemption:
    reason: str
    url_name: str  # the view's route name: the test file must call its URL
    tests: str  # the covering test file, relative to the cultures package


EXEMPT = {
    "cultures.users.api.views.csrf": Exemption(
        "anonymous, sets the CSRF cookie", "auth-csrf", "users/tests/test_auth.py"
    ),
    "cultures.users.api.views.login_view": Exemption(
        "anonymous by design", "auth-login", "users/tests/test_auth.py"
    ),
    "cultures.users.api.views.logout_view": Exemption(
        "own session only", "auth-logout", "users/tests/test_auth.py"
    ),
    "cultures.users.api.views.me": Exemption(
        "own user only, no lookup", "auth-me", "users/tests/test_auth.py"
    ),
    "cultures.overview.api.views.overview": Exemption(
        "own view across own labs, no object in the URL: rows scoped by membership",
        "me-overview",
        "overview/tests/test_api.py",
    ),
    "cultures.overview.api.views.recent_activity": Exemption(
        "own view across own labs, no object in the URL: rows scoped by membership",
        "me-activity",
        "overview/tests/test_api.py",
    ),
    "cultures.taxonomy.api.views.TaxonViewSet": Exemption(
        "global reference data read by every signed-in user: no lab, so no outsider to hide from",
        "taxon-list",
        "taxonomy/tests/test_api.py",
    ),
    "cultures.storage.api.views.BoxTypeViewSet": Exemption(
        "global reference data read by every signed-in user: no lab, so no outsider to hide from",
        "box-type-list",
        "storage/tests/test_api.py",
    ),
}


def test_every_routed_api_view_has_a_contract_or_an_exemption() -> None:
    import_test_modules()
    routed = routed_api_views()
    # An exemption for a view that is gone is stale, and an empty walk cannot pass.
    stale = sorted(set(EXEMPT) - set(routed))
    assert not stale, f"EXEMPT names views that are not routed: {stale}"
    missing = sorted(
        name for name, cls in routed.items() if name not in EXEMPT and cls not in COVERED
    )
    assert not missing, (
        f"routed API views without a ViewsetContract test class: {missing}. Add a subclass of "
        "cultures.core.testing.ViewsetContract in the app's tests, or for a view without an "
        "object scope an entry in EXEMPT naming its URL and the test file that calls it."
    )


def exemptions_without_a_calling_test() -> list[str]:
    """Entries whose URL is not the view's, or whose test file never calls that URL."""
    wrong = []
    for name, exemption in sorted(EXEMPT.items()):
        url = reverse(exemption.url_name)
        cls = resolve(url).func.cls  # type: ignore[attr-defined]
        test_file = PACKAGE / exemption.tests
        if (
            f"{cls.__module__}.{cls.__name__}" != name
            or not test_file.is_file()
            or url not in test_file.read_text()
        ):
            wrong.append(name)
    return wrong


def test_every_exemption_names_a_test_file_that_calls_the_view() -> None:
    assert EXEMPT  # an empty table must not pass
    assert exemptions_without_a_calling_test() == []


# The meta-test itself: each fault it exists to catch makes it fail.


def test_a_stale_exemption_fails_the_meta_test(monkeypatch: pytest.MonkeyPatch) -> None:
    gone = Exemption("removed view", "auth-me", "users/tests/test_auth.py")
    monkeypatch.setitem(EXEMPT, "cultures.users.api.views.gone", gone)
    with pytest.raises(
        AssertionError, match=r"not routed: \['cultures\.users\.api\.views\.gone'\]"
    ):
        test_every_routed_api_view_has_a_contract_or_an_exemption()


def test_an_uncovered_view_fails_the_meta_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(EXEMPT, "cultures.users.api.views.me")
    with pytest.raises(AssertionError, match=r"cultures\.users\.api\.views\.me"):
        test_every_routed_api_view_has_a_contract_or_an_exemption()


@pytest.mark.parametrize(
    ("url_name", "tests"),
    [
        ("auth-logout", "core/tests/test_health.py"),  # a file that never calls the URL
        ("auth-logout", "users/tests/missing.py"),
        ("auth-me", "users/tests/test_auth.py"),  # the URL of another view
    ],
)
def test_an_exemption_without_a_calling_test_is_found(
    monkeypatch: pytest.MonkeyPatch, url_name: str, tests: str
) -> None:
    name = "cultures.users.api.views.logout_view"
    monkeypatch.setitem(EXEMPT, name, Exemption("own session only", url_name, tests))
    assert exemptions_without_a_calling_test() == [name]
