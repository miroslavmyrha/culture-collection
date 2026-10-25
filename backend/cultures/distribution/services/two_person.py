"""The two-person shipment of a regulated request (#89, ADR 0009)."""

import uuid

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    REQUEST_SHIPMENT_PREPARED,
    REQUEST_SHIPMENT_WITHDRAWN,
    REQUEST_SHIPPED,
)
from cultures.labs.access import Access
from cultures.labs.permissions import Perm

from ..models import (
    ONE_OPEN_PREPARATION,
    PACKAGE_FIELDS,
    DistributionRequest,
    RequestStatus,
    Shipment,
    ShipmentPreparation,
)
from ._shared import (
    REQUEST,
    _check_reason,
    _defer_reservation_checks,
    _locked_request,
    _move,
    _save,
)
from .errors import (
    ConfirmOwnApproval,
    ConfirmOwnPreparation,
    PreparationChanged,
    PreparedMeanwhile,
    ShipInOneStep,
)
from .inputs import (
    ShipmentInput,
)
from .shipment import (
    _check_exempt,
    _checked_shipment,
    _exhaust_emptied,
    _gates_today,
    _locked_strains,
    _package,
    _package_changes,
    _regulated,
    _send,
    _write_documents,
)

# The two-person shipment of a regulated request (#89, ADR 0009).


def _open_preparation(locked: DistributionRequest) -> ShipmentPreparation:
    """The request's one preparation not withdrawn (a partial unique index). The request's lock
    serialises every writer of it, so it takes no lock of its own."""
    return ShipmentPreparation.objects.select_related("responsible", "prepared_by").get(
        request=locked, withdrawn_at__isnull=True
    )


def request_prepare_shipment(
    *, access: Access, request: DistributionRequest, data: ShipmentInput
) -> DistributionRequest:
    """Step 1 for a request with a regulated line: the shipment as this person records it, the
    same facts as a shipment in one step. The gates run today; the request awaits a second
    person's confirmation. Nothing leaves: the vials stay reserved."""
    data = _checked_shipment(data)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.AWAITING_CONFIRMATION, source=RequestStatus.APPROVED)
        _, strains = _locked_strains(locked)
        _gates_today(locked)
        if not _regulated(strains):
            raise ShipInOneStep
        _check_exempt(data.classification_basis, strains)
        preparation = ShipmentPreparation(
            **_package(data, locked.lab_id),
            request=locked,
            prepared_by=access.user,
            prepared_at=timezone.now(),
        )
        _save(preparation, {ONE_OPEN_PREPARATION: PreparedMeanwhile()})
        locked.status = RequestStatus.AWAITING_CONFIRMATION
        locked.save(update_fields=["status", "updated_at"])
        record_event(
            REQUEST_SHIPMENT_PREPARED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.AWAITING_CONFIRMATION],
                    "preparation": [None, str(preparation.public_id)],
                    **_package_changes(preparation),
                },
                lab_id=locked.lab_id,
            ),
        )
    return locked


def request_confirm_shipment(
    *, access: Access, request: DistributionRequest, preparation: uuid.UUID
) -> DistributionRequest:
    """Step 2: a different person confirms the prepared shipment they read (`preparation`, its
    public id): neither the approver nor the preparer. The gates run again today, then exactly
    what a shipment in one step does happens, with the preparation's facts. The event holds
    both people and both times (ADR 0009)."""
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.SHIPPED, source=RequestStatus.AWAITING_CONFIRMATION)
        prepared = _open_preparation(locked)
        if prepared.public_id != preparation:
            raise PreparationChanged
        if locked.decided_by_id == access.user.pk:
            raise ConfirmOwnApproval
        if prepared.prepared_by_id == access.user.pk:
            raise ConfirmOwnPreparation
        lines, strains = _locked_strains(locked)
        today = _gates_today(locked)
        _check_exempt(prepared.classification_basis, strains)
        now = timezone.now()
        _defer_reservation_checks(shipment=True)
        shipment = Shipment.objects.create(
            **{f: getattr(prepared, f) for f in PACKAGE_FIELDS},
            lab_id=locked.lab_id,
            request=locked,
            preparation=prepared,
            classified_by_id=prepared.prepared_by_id,
            classified_at=prepared.prepared_at,
            shipped_by=access.user,
            shipped_at=now,
        )
        batches = _send(access, locked, lines, shipment)
        record_event(
            REQUEST_SHIPPED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.SHIPPED],
                    "shipment": [None, str(shipment.public_id)],
                    "shipped_on": [None, today.isoformat()],
                    **_package_changes(shipment),
                    "preparation": [None, str(prepared.public_id)],
                    # Pseudonymous: public ids, never names (ADR 0005).
                    "prepared_by": [None, str(prepared.prepared_by.public_id)],
                    "prepared_at": [None, prepared.prepared_at.isoformat()],
                    "confirmed_by": [None, str(access.user.public_id)],
                    "confirmed_at": [None, now.isoformat()],
                },
                lab_id=locked.lab_id,
            ),
        )
        _write_documents(locked, shipment, today)
        _exhaust_emptied(locked, batches)
    return locked


def request_withdraw_shipment(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The prepared shipment is withdrawn, with the reason, by its preparer or anyone else who
    manages distribution: the request is approved again and may be prepared anew. The
    preparation stays as history, its facts unchanged."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.APPROVED, source=RequestStatus.AWAITING_CONFIRMATION)
        prepared = _open_preparation(locked)
        prepared.withdrawn_by, prepared.withdrawn_at = access.user, timezone.now()
        prepared.withdraw_reason = reason
        prepared.save(
            update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"]
        )
        locked.status = RequestStatus.APPROVED
        locked.save(update_fields=["status", "updated_at"])
        record_event(
            REQUEST_SHIPMENT_WITHDRAWN,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.APPROVED],
                    "preparation": [str(prepared.public_id), None],
                },
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked
