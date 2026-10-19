"""Lab authorisations: staff record a permit and end it, in Django admin or a command.

Both take the lab lock first (labs.locks), the same lock the strain accession
holds while it checks the permits (policy.require_authorisation). Rows are
never deleted and never edited: a wrong row is ended with its reason and a
new one recorded.
"""

from datetime import date

from django.db import IntegrityError, transaction

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import LAB_AUTHORISATION_ADDED, LAB_AUTHORISATION_ENDED
from cultures.core.exceptions import Conflict, DomainError, NotFound
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab

from .models import AUTHORISATION_UNIQUE, ISSUER_OF, AuthorisationKind, LabAuthorisation

AUTHORISATION = "lab_authorisation"


class InvalidAuthorisation(DomainError):
    default_code = "invalid_authorisation"


class AlreadyEnded(Conflict):
    default_code = "already_ended"
    default_detail = "This authorisation has ended already."


def authorisation_create(
    *,
    lab: Lab,
    kind: AuthorisationKind,
    permit_reference: str,
    valid_from: date,
    expires_on: date | None,
) -> LabAuthorisation:
    reference = " ".join(permit_reference.split())
    if not reference:
        raise InvalidAuthorisation("Enter the permit reference.", attr="permit_reference")
    if expires_on is not None and expires_on < valid_from:
        raise InvalidAuthorisation("The expiry comes before the start.", attr="expires_on")
    with audited_atomic():
        lock_lab(lab.pk)
        authorisation = LabAuthorisation(
            lab=lab,
            kind=kind,
            issuer=ISSUER_OF[kind],
            permit_reference=reference,
            valid_from=valid_from,
            expires_on=expires_on,
        )
        try:
            with transaction.atomic():
                authorisation.save()
        except IntegrityError as exc:
            diag = getattr(exc.__cause__, "diag", None)
            if getattr(diag, "constraint_name", None) == AUTHORISATION_UNIQUE:
                raise InvalidAuthorisation(
                    "The lab has this permit recorded already.",
                    code="unique",
                    attr="permit_reference",
                ) from exc
            raise
        record_event(
            LAB_AUTHORISATION_ADDED,
            Change(
                AUTHORISATION,
                authorisation.public_id,
                {
                    "kind": [None, kind],
                    "issuer": [None, authorisation.issuer],
                    "permit_reference": [None, reference],
                    "valid_from": [None, valid_from.isoformat()],
                    "expires_on": [None, expires_on.isoformat() if expires_on else None],
                },
                lab_id=lab.pk,
            ),
        )
    return authorisation


def authorisation_end(
    *, authorisation: LabAuthorisation, ended_on: date, reason: str
) -> LabAuthorisation:
    """The permit stops being valid on `ended_on`. The reason says why, never who."""
    with audited_atomic():
        lock_lab(authorisation.lab_id)
        locked = LabAuthorisation.objects.select_for_update().filter(pk=authorisation.pk).first()
        if locked is None:
            raise NotFound
        if locked.ended_on is not None:
            raise AlreadyEnded
        if ended_on < locked.valid_from:
            raise InvalidAuthorisation("The end comes before the start.", attr="ended_on")
        locked.ended_on, locked.end_reason = ended_on, reason.strip()
        record_event(
            LAB_AUTHORISATION_ENDED,
            Change(
                AUTHORISATION,
                locked.public_id,
                {"ended_on": [None, ended_on.isoformat()]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=["ended_on", "end_reason", "updated_at"])
    return locked
