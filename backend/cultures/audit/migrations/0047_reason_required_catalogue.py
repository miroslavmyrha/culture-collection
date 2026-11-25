"""A catalogue (#70) is imported with a reason: the reason constraint of audit_auditevent with
catalogue_imported.

Added NOT VALID, as audit.registry asks of this table, and validated by 0048 in a transaction
of its own (see 0022). The state is the AddConstraint Django generates.
"""

from django.conf import settings
from django.db import migrations, models

OLD = "'batch_check_entered_in_error', 'batch_status_changed', 'contact_erased', 'deposit_rejected', 'deposit_terms_replaced', 'destruction_confirmed', 'destruction_entered_in_error', 'destruction_recorded', 'enrolment_code_issued', 'factor_reset_confirmed', 'factor_reset_proposed', 'factor_reset_withdrawn', 'lab_authorisation_ended', 'location_grant_added', 'location_grant_confirmed', 'location_grant_revoked', 'medium_retired', 'recipient_permit_ended', 'request_approved_again', 'request_cancelled', 'request_rejected', 'request_shipment_withdrawn', 'storage_unit_status_changed', 'strain_deaccession_proposed', 'strain_deaccession_withdrawn', 'strain_deaccessioned', 'strain_growth_changed', 'strain_reclassified', 'strain_restriction_added', 'strain_restriction_end_proposed', 'strain_restriction_end_withdrawn', 'strain_restriction_ended', 'strain_risk_group_changed', 'strain_risk_group_lower_proposed', 'strain_risk_group_lower_withdrawn', 'user_activated', 'user_deactivated', 'user_erased', 'user_login_limits_cleared', 'user_staff_changed', 'user_superuser_changed', 'users_deactivated', 'vial_loss_reported', 'vial_status_changed', 'vials_destroyed', 'vials_marked_for_destruction', 'vrat_access_ended', 'vrat_access_granted'"
NEW = "'batch_check_entered_in_error', 'batch_status_changed', 'catalogue_imported', 'contact_erased', 'deposit_rejected', 'deposit_terms_replaced', 'destruction_confirmed', 'destruction_entered_in_error', 'destruction_recorded', 'enrolment_code_issued', 'factor_reset_confirmed', 'factor_reset_proposed', 'factor_reset_withdrawn', 'lab_authorisation_ended', 'location_grant_added', 'location_grant_confirmed', 'location_grant_revoked', 'medium_retired', 'recipient_permit_ended', 'request_approved_again', 'request_cancelled', 'request_rejected', 'request_shipment_withdrawn', 'storage_unit_status_changed', 'strain_deaccession_proposed', 'strain_deaccession_withdrawn', 'strain_deaccessioned', 'strain_growth_changed', 'strain_reclassified', 'strain_restriction_added', 'strain_restriction_end_proposed', 'strain_restriction_end_withdrawn', 'strain_restriction_ended', 'strain_risk_group_changed', 'strain_risk_group_lower_proposed', 'strain_risk_group_lower_withdrawn', 'user_activated', 'user_deactivated', 'user_erased', 'user_login_limits_cleared', 'user_staff_changed', 'user_superuser_changed', 'users_deactivated', 'vial_loss_reported', 'vial_status_changed', 'vials_destroyed', 'vials_marked_for_destruction', 'vrat_access_ended', 'vrat_access_granted'"

FORWARD = f"""
ALTER TABLE audit_auditevent DROP CONSTRAINT audit_auditevent_reason_required;
ALTER TABLE audit_auditevent ADD CONSTRAINT audit_auditevent_reason_required
    CHECK ((NOT ("event_type" IN ({NEW})) OR "reason"::text ~ E'\\\\S')) NOT VALID;
"""

REVERSE = f"""
ALTER TABLE audit_auditevent DROP CONSTRAINT audit_auditevent_reason_required;
ALTER TABLE audit_auditevent ADD CONSTRAINT audit_auditevent_reason_required
    CHECK ((NOT ("event_type" IN ({OLD})) OR "reason"::text ~ E'\\\\S'));
"""

TYPES = [t.strip().strip("'") for t in NEW.split(",")]


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0046_auditevent_actor_drop_single_index"),
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
                            models.Q(("event_type__in", TYPES), _negated=True),
                            ("reason__regex", "\\S"),
                            _connector="OR",
                        ),
                        name="audit_auditevent_reason_required",
                    ),
                ),
            ],
        ),
    ]
