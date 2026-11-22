from django.urls import path

from . import factor_views, views

urlpatterns = [
    path("csrf/", views.csrf, name="auth-csrf"),
    path("login/", views.login_view, name="auth-login"),
    path("logout/", views.logout_view, name="auth-logout"),
    path("me/", views.me, name="auth-me"),
    # The second factor (#176)
    path("second-factor/", factor_views.second_factor_code, name="auth-second-factor"),
    path(
        "second-factor/key/options/",
        factor_views.second_factor_key_options,
        name="auth-second-factor-key-options",
    ),
    path("second-factor/key/", factor_views.second_factor_key, name="auth-second-factor-key"),
    path("enrolment-code/", factor_views.enrolment_code, name="auth-enrolment-code"),
    path("enrolment-codes/", factor_views.enrolment_code_issue, name="auth-enrolment-code-issue"),
    path("factors/", factor_views.factor_list, name="auth-factors"),
    path(
        "factors/keys/options/",
        factor_views.key_registration_options,
        name="auth-factor-key-options",
    ),
    path("factors/keys/", factor_views.key_enrol, name="auth-factor-keys"),
    path("factors/keys/<uuid:public_id>/", factor_views.key_remove, name="auth-factor-key"),
    path("factors/totp/setup/", factor_views.totp_setup, name="auth-factor-totp-setup"),
    path("factors/totp/", factor_views.totp_enrol, name="auth-factor-totp"),
    path("factors/totp/remove/", factor_views.totp_remove, name="auth-factor-totp-remove"),
    path(
        "factors/recovery-codes/",
        factor_views.recovery_codes_issue,
        name="auth-factor-recovery-codes",
    ),
    path("factor-resets/", factor_views.factor_reset_list, name="auth-factor-resets"),
    path(
        "factor-resets/propose/",
        factor_views.factor_reset_propose,
        name="auth-factor-reset-propose",
    ),
    path(
        "factor-resets/<uuid:public_id>/confirm/",
        factor_views.factor_reset_confirm,
        name="auth-factor-reset-confirm",
    ),
    path(
        "factor-resets/<uuid:public_id>/withdraw/",
        factor_views.factor_reset_withdraw,
        name="auth-factor-reset-withdraw",
    ),
]
