"""The decisions on a request: approval with its reservations, rejection, cancellation."""

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    REQUEST_APPROVED,
    REQUEST_CANCELLED,
    REQUEST_LINE_RELEASED,
    REQUEST_LINE_RESERVED,
    REQUEST_REJECTED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Forbidden, RuleViolation
from cultures.labs.access import Access
from cultures.labs.permissions import Perm
from cultures.lineage import services as lineage
from cultures.lineage.models import Vial, VialStatus
from cultures.lineage.selectors import distributable
from cultures.strains.models import Strain

from .. import policy
from ..models import (
    ONE_OPEN_RESERVATION,
    DistributionRequest,
    LinePermit,
    RequestStatus,
    ReservationEnd,
    VialReservation,
)
from ._shared import (
    LINE,
    REQUEST,
    _check_reason,
    _defer_reservation_checks,
    _locked_request,
    _move,
    _require,
    _save,
)
from .errors import (
    ManagerRequired,
    NotEnoughVials,
    RequestBlocked,
    ReservedMeanwhile,
)


def request_approve(
    *, access: Access, request: DistributionRequest, reason: str = ""
) -> DistributionRequest:
    """Curators approve; a manager approves when a finding asks for one, with a reason. Every
    blocker refuses. The vials are reserved now (D19, no expiry): for each line, the available
    vials of distributable batches of its strain, locked in pk order and skipping those another
    approval holds, all chosen before anything is written."""
    reason = reason.strip()
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.APPROVED, source=RequestStatus.SUBMITTED)
        lines = list(locked.lines.select_related("strain").order_by("pk"))
        # The strains next (lock order lab, request, strain, vial): their status and
        # restrictions change only under the lab lock, the lock here keeps the order explicit.
        list(
            Strain.objects.select_for_update()
            .filter(pk__in=[line.strain_id for line in lines])
            .order_by("pk")
        )
        evaluation = policy.evaluate(locked, permit_today())
        blockers = evaluation.blockers
        if blockers:
            raise RequestBlocked(" ".join(f.sentence for f in blockers))
        if evaluation.needs_manager:
            try:
                _require(access, locked.lab_id, Perm.APPROVE_REGULATED)
            except Forbidden:
                raise ManagerRequired from None
            if not reason:
                raise RuleViolation(
                    "Say why the findings allow it.", code="reason_required", attr="reason"
                )
        chosen: dict[int, list[Vial]] = {}
        for line in lines:
            vials = list(
                Vial.objects.select_for_update(skip_locked=True, of=("self",))
                .filter(
                    distributable("batch__"),
                    lab_id=locked.lab_id,
                    status=VialStatus.AVAILABLE,
                    batch__strain_id=line.strain_id,
                )
                .select_related("batch__strain")
                .order_by("pk")[: line.quantity]
            )
            if len(vials) < line.quantity:
                raise NotEnoughVials(
                    f"{line.strain.accession_number}: {len(vials)} vials are free now, the line"
                    f" asks for {line.quantity}."
                )
            chosen[line.pk] = vials
        now = timezone.now()
        label = f"Reserved for request {locked.label}."
        _defer_reservation_checks()
        for line in lines:
            for vial in chosen[line.pk]:
                lineage.vial_reserve_locked(access=access, vial=vial, reason=label)
                _save(
                    VialReservation(
                        lab_id=locked.lab_id,
                        line=line,
                        vial=vial,
                        reserved_at=now,
                        reserved_by=access.user,
                    ),
                    {ONE_OPEN_RESERVATION: ReservedMeanwhile()},
                )
            permits = {p.pk: p for ln, p in evaluation.used if ln.pk == line.pk}
            for permit in permits.values():
                LinePermit.objects.create(line=line, permit=permit)
            record_event(
                REQUEST_LINE_RESERVED,
                Change(
                    LINE,
                    line.public_id,
                    {
                        "vials": [None, [str(v.public_id) for v in chosen[line.pk]]],
                        "permits": [None, sorted(str(p.public_id) for p in permits.values())],
                    },
                    lab_id=locked.lab_id,
                    strain_id=line.strain.public_id,
                ),
            )
        locked.status, locked.decided_by, locked.decided_at = (
            RequestStatus.APPROVED,
            access.user,
            now,
        )
        locked.decision_reason = reason
        locked.save(
            update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"]
        )
        record_event(
            REQUEST_APPROVED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.APPROVED],
                    "findings": [None, [f.code for f in evaluation.findings]],
                },
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


def request_reject(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The request is refused, with the reason: kept for good (OECD 11.5), nothing reserved."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.REJECTED)
        locked.status, locked.decided_by, locked.decided_at = (
            RequestStatus.REJECTED,
            access.user,
            timezone.now(),
        )
        locked.decision_reason = reason
        locked.save(
            update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"]
        )
        record_event(
            REQUEST_REJECTED,
            Change(
                REQUEST,
                locked.public_id,
                {"status": [old, RequestStatus.REJECTED]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


def request_cancel(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The request is withdrawn, before or after approval. Its open reservations end and their
    vials are available again."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.CANCELLED)
        lines = list(locked.lines.select_related("strain").order_by("pk"))
        list(
            Strain.objects.select_for_update()
            .filter(pk__in=[line.strain_id for line in lines])
            .order_by("pk")
        )
        now = timezone.now()
        _defer_reservation_checks()
        open_rows = list(
            # of=self: a join locks every table it reads, and lines take no UPDATE (frozen).
            VialReservation.objects.select_for_update(of=("self",))
            .filter(line__request=locked, ended_at__isnull=True)
            .order_by("vial_id")
        )
        vials = {
            v.pk: v
            for v in Vial.objects.select_for_update(of=("self",))
            .select_related("batch__strain")
            .filter(pk__in=[r.vial_id for r in open_rows])
            .order_by("pk")
        }
        for line in lines:
            reservations = [r for r in open_rows if r.line_id == line.pk]
            if not reservations:
                continue
            for reservation in reservations:
                reservation.ended_at, reservation.ended_by = now, access.user
                reservation.end_reason = ReservationEnd.CANCELLED
                reservation.save(update_fields=["ended_at", "ended_by", "end_reason", "updated_at"])
                lineage.vial_release_locked(
                    access=access,
                    vial=vials[reservation.vial_id],
                    reason=f"Request {locked.label} was cancelled.",
                )
            record_event(
                REQUEST_LINE_RELEASED,
                Change(
                    LINE,
                    line.public_id,
                    {"vials": [[str(vials[r.vial_id].public_id) for r in reservations], None]},
                    lab_id=locked.lab_id,
                    strain_id=line.strain.public_id,
                ),
                reason=reason,
            )
        locked.status, locked.cancelled_by, locked.cancelled_at = (
            RequestStatus.CANCELLED,
            access.user,
            now,
        )
        locked.cancel_reason = reason
        locked.save(
            update_fields=["status", "cancelled_by", "cancelled_at", "cancel_reason", "updated_at"]
        )
        record_event(
            REQUEST_CANCELLED,
            Change(
                REQUEST,
                locked.public_id,
                {"status": [old, RequestStatus.CANCELLED]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked
