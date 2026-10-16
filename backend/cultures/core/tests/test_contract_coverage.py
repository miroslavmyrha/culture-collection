"""Every routed API view of the project has a ViewsetContract test class or a reviewed exemption.

A viewset gets its contract in <app>/tests/test_contract.py (any test_*.py works).
EXEMPT is for views the contract does not fit: no object scope, anonymous by
design. Each entry names the tests that cover it instead; adding one is a review
decision, like a new permission.
"""

from cultures.core.testing.contract import COVERED, import_test_modules, routed_api_views

EXEMPT = {
    "cultures.users.api.views.csrf": "anonymous, sets the CSRF cookie: users/tests/test_auth.py",
    "cultures.users.api.views.login_view": "anonymous by design: users/tests/test_auth.py",
    "cultures.users.api.views.logout_view": "own session only: users/tests/test_auth.py",
    "cultures.users.api.views.me": "own user only, no lookup: users/tests/test_auth.py",
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
        "object scope an entry in EXEMPT naming the tests that cover it."
    )
