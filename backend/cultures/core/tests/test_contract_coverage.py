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
    # A route with a public id (#176): the test file must call the URL up to the id.
    with_id: bool = False


PROBE_ID = "00000000-0000-4000-8000-000000000000"


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
    "cultures.users.api.factor_views.second_factor_code": Exemption(
        "the second sign-in step, anonymous by design (#176)",
        "auth-second-factor",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.second_factor_key_options": Exemption(
        "the second sign-in step, anonymous by design (#176)",
        "auth-second-factor-key-options",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.second_factor_key": Exemption(
        "the second sign-in step, anonymous by design (#176)",
        "auth-second-factor-key",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.enrolment_code": Exemption(
        "the step before the first enrolment, anonymous by design (#176)",
        "auth-enrolment-code",
        "users/tests/test_enrolment_code.py",
    ),
    "cultures.users.api.factor_views.enrolment_code_issue": Exemption(
        "a member of a lab the caller manages, else not found",
        "auth-enrolment-code-issue",
        "users/tests/test_enrolment_code.py",
    ),
    "cultures.users.api.factor_views.factor_list": Exemption(
        "own factors only, no lookup", "auth-factors", "users/tests/test_second_factor.py"
    ),
    "cultures.users.api.factor_views.key_registration_options": Exemption(
        "the first enrolment after the password, or own account",
        "auth-factor-key-options",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.key_enrol": Exemption(
        "the first enrolment after the password, or own account",
        "auth-factor-keys",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.key_remove": Exemption(
        "own key only: the lookup is filtered by the signed-in user",
        "auth-factor-key",
        "users/tests/test_second_factor.py",
        with_id=True,
    ),
    "cultures.users.api.factor_views.totp_setup": Exemption(
        "the first enrolment after the password, or own account",
        "auth-factor-totp-setup",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.totp_enrol": Exemption(
        "the first enrolment after the password, or own account",
        "auth-factor-totp",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.totp_remove": Exemption(
        "own app only, no lookup", "auth-factor-totp-remove", "users/tests/test_second_factor.py"
    ),
    "cultures.users.api.factor_views.recovery_codes_issue": Exemption(
        "own codes only, no lookup",
        "auth-factor-recovery-codes",
        "users/tests/test_second_factor.py",
    ),
    "cultures.users.api.factor_views.factor_reset_list": Exemption(
        "a lab's resets for its managers: the lab is looked up by role, else not found",
        "auth-factor-resets",
        "users/tests/test_factor_reset.py",
    ),
    "cultures.users.api.factor_views.factor_reset_propose": Exemption(
        "a member of a lab the caller manages, else not found",
        "auth-factor-reset-propose",
        "users/tests/test_factor_reset.py",
    ),
    "cultures.users.api.factor_views.factor_reset_confirm": Exemption(
        "a reset of a lab the caller manages, else not found",
        "auth-factor-reset-confirm",
        "users/tests/test_factor_reset.py",
        with_id=True,
    ),
    "cultures.users.api.factor_views.factor_reset_withdraw": Exemption(
        "a reset of a lab the caller manages, else not found",
        "auth-factor-reset-withdraw",
        "users/tests/test_factor_reset.py",
        with_id=True,
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
    "cultures.search.api.views.search": Exemption(
        "own search across own labs, no object in the URL: rows scoped by membership",
        "me-search",
        "search/tests/test_api.py",
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
        url = reverse(exemption.url_name, args=[PROBE_ID] if exemption.with_id else [])
        cls = resolve(url).func.cls  # type: ignore[attr-defined]
        test_file = PACKAGE / exemption.tests
        called = url.split(PROBE_ID)[0]
        if (
            f"{cls.__module__}.{cls.__name__}" != name
            or not test_file.is_file()
            or called not in test_file.read_text()
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
