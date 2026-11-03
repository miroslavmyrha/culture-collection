"""The report of a lost VRAT or RAT vial to the police (#159).

Act 281/2002 Sb., § 5(5): whoever finds a loss of a highly risky or risky agent reports it to the
Police of the Czech Republic without undue delay. The collection cannot report for anyone. It
records that the report was made: the Czech day, the police reference and a reason, once per
loss, by a manager of the lab (distribution.approve_regulated: managers answer to the authority
for regulated agents, labs.permissions). Until then Home lists the loss for the lab's managers
(overview.selectors). A vial found before a report is no longer lost and owes none.
"""

from datetime import date, datetime

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import VIAL_LOSS_REPORTED
from cultures.biosafety.policy import PERMIT_TIME_ZONE, permit_today
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.permissions import Perm

from ..models import LOSS_REPORT_ONE_PER_LOSS, Vial, VialLossReport, VialStatus
from ..selectors import reportable_loss
from ._shared import VIAL, _check_reason, _locked_vial, _require, _save, normalised
from .errors import InvalidVial, LossChanged, LossNotReportable, LossReported, VialNotLost

REFERENCE_LENGTH = 100


def vial_loss_report(
    *,
    access: Access,
    vial: Vial,
    lost_at: datetime,
    reported_on: date,
    reference: str,
    reason: str,
) -> VialLossReport:
    """Records that the loss the vial is in was reported to the police. `lost_at` is the vial's
    status_changed_at as the caller read it: a vial found and lost again since is another loss
    (409 loss_changed). The reference is the police's and names no person."""
    reason = _check_reason(reason)
    reference = normalised(reference)
    if not reference:
        raise InvalidVial("Give the reference the police gave the report.", attr="reference")
    if len(reference) > REFERENCE_LENGTH:
        raise InvalidVial(
            f"At most {REFERENCE_LENGTH} characters.", code="max_length", attr="reference"
        )
    if reported_on > permit_today():
        raise InvalidVial("This date is in the future.", attr="reported_on")
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id, Perm.APPROVE_REGULATED)
        locked = _locked_vial(vial)
        if locked.status != VialStatus.LOST:
            raise VialNotLost
        if locked.status_changed_at != lost_at:
            raise LossChanged
        assert locked.status_changed_at is not None  # noqa: S101 (a lost vial changed once)
        # The restrictions change under the lab lock this service holds (strains.services).
        if not Vial.objects.filter(pk=locked.pk).filter(reportable_loss()).exists():
            raise LossNotReportable
        if reported_on < locked.status_changed_at.astimezone(PERMIT_TIME_ZONE).date():
            raise InvalidVial("The report is not dated before the loss.", attr="reported_on")
        if VialLossReport.objects.filter(vial=locked, lost_at=locked.status_changed_at).exists():
            raise LossReported
        report = VialLossReport(
            lab_id=locked.lab_id,
            vial=locked,
            lost_at=locked.status_changed_at,
            reported_on=reported_on,
            reference=reference,
            recorded_by=access.user,
            recorded_at=timezone.now(),
        )
        _save(report, {LOSS_REPORT_ONE_PER_LOSS: LossReported()})
        record_event(
            VIAL_LOSS_REPORTED,
            Change(
                VIAL,
                locked.public_id,
                {
                    "loss_report": [None, str(report.public_id)],
                    "lost_at": [None, report.lost_at.isoformat()],
                    "reported_on": [None, report.reported_on.isoformat()],
                    "reference": [None, report.reference],
                },
                lab_id=locked.lab_id,
                strain_id=locked.batch.strain.public_id,
            ),
            reason=reason,
        )
    return report
