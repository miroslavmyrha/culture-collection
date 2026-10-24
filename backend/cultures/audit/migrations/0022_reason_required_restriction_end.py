"""The two event types of #105 need a reason: audit_auditevent_reason_required with them.

Added NOT VALID, as audit.registry asks of this table: the constraint holds for every new row at
once, and 0023 validates the rows already there in a transaction of its own, under a lock that
lets writes go on. A plain AddConstraint would scan the append-only table under ACCESS
EXCLUSIVE. The state is the AddConstraint Django generates.
"""

from django.conf import settings
from django.db import migrations, models


FORWARD = r"""
ALTER TABLE audit_auditevent DROP CONSTRAINT audit_auditevent_reason_required;
ALTER TABLE audit_auditevent ADD CONSTRAINT audit_auditevent_reason_required
    CHECK ((NOT ("event_type" IN ('batch_check_entered_in_error', 'batch_status_changed', 'contact_erased', 'deposit_rejected', 'deposit_terms_replaced', 'lab_authorisation_ended', 'location_grant_added', 'location_grant_revoked', 'recipient_permit_ended', 'request_cancelled', 'request_rejected', 'request_shipment_withdrawn', 'storage_unit_status_changed', 'strain_reclassified', 'strain_restriction_added', 'strain_restriction_end_proposed', 'strain_restriction_end_withdrawn', 'strain_restriction_ended', 'strain_risk_group_changed', 'user_activated', 'user_deactivated', 'user_erased', 'user_login_limits_cleared', 'user_staff_changed', 'user_superuser_changed', 'users_deactivated', 'vial_status_changed')) OR "reason"::text ~ E'\\S')) NOT VALID;
"""

REVERSE = r"""
ALTER TABLE audit_auditevent DROP CONSTRAINT audit_auditevent_reason_required;
ALTER TABLE audit_auditevent ADD CONSTRAINT audit_auditevent_reason_required
    CHECK ((NOT ("event_type" IN ('batch_check_entered_in_error', 'batch_status_changed', 'contact_erased', 'deposit_rejected', 'deposit_terms_replaced', 'lab_authorisation_ended', 'location_grant_added', 'location_grant_revoked', 'recipient_permit_ended', 'request_cancelled', 'request_rejected', 'request_shipment_withdrawn', 'storage_unit_status_changed', 'strain_reclassified', 'strain_restriction_added', 'strain_restriction_ended', 'strain_risk_group_changed', 'user_activated', 'user_deactivated', 'user_erased', 'user_login_limits_cleared', 'user_staff_changed', 'user_superuser_changed', 'users_deactivated', 'vial_status_changed')) OR "reason"::text ~ E'\\S'));
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0021_reason_required_shipment_withdrawn"),
        ("labs", "0004_locationgrant_audit_and_guard"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD, REVERSE)],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="auditevent",
                    name="audit_auditevent_reason_required",
                ),
                migrations.AddConstraint(
                    model_name="auditevent",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                (
                                    "event_type__in",
                                    [
                                        "batch_check_entered_in_error",
                                        "batch_status_changed",
                                        "contact_erased",
                                        "deposit_rejected",
                                        "deposit_terms_replaced",
                                        "lab_authorisation_ended",
                                        "location_grant_added",
                                        "location_grant_revoked",
                                        "recipient_permit_ended",
                                        "request_cancelled",
                                        "request_rejected",
                                        "request_shipment_withdrawn",
                                        "storage_unit_status_changed",
                                        "strain_reclassified",
                                        "strain_restriction_added",
                                        "strain_restriction_end_proposed",
                                        "strain_restriction_end_withdrawn",
                                        "strain_restriction_ended",
                                        "strain_risk_group_changed",
                                        "user_activated",
                                        "user_deactivated",
                                        "user_erased",
                                        "user_login_limits_cleared",
                                        "user_staff_changed",
                                        "user_superuser_changed",
                                        "users_deactivated",
                                        "vial_status_changed",
                                    ],
                                ),
                                _negated=True,
                            ),
                            ("reason__regex", "\\S"),
                            _connector="OR",
                        ),
                        name="audit_auditevent_reason_required",
                    ),
                ),
            ],
        ),
    ]
