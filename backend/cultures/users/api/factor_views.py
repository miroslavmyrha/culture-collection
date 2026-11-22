"""The second factor in the API (ADR 0009, #176): the second sign-in step, enrolment, the
user's own factors, and the reset by two people.

The sign-in step and the first enrolment run for the person who passed the password step
(cultures.users.signin.pending), not signed in yet: their writes check CSRF themselves, as the
login does, and run in an audit context with that person as the actor. The same step for a
signed-in user is a fresh check (step-up), which removal, a new key on a signed-in account and
new recovery codes need.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotAuthenticated, Throttled
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.core.exceptions import Forbidden, NotFound
from cultures.core.security import enforce_csrf
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users import factors, signin
from cultures.users.auth import current_user
from cultures.users.login_limits import Attempt, Surface
from cultures.users.models import FactorReset, SecurityKey, User

from .serializers import (
    CeremonyOutputSerializer,
    CodeInputSerializer,
    CredentialInputSerializer,
    EnrolledOutputSerializer,
    EnrolmentCodeInputSerializer,
    EnrolmentCodeIssueInputSerializer,
    EnrolmentCodeOutputSerializer,
    FactorResetInputSerializer,
    FactorResetOutputSerializer,
    FactorResetReasonInputSerializer,
    FactorsOutputSerializer,
    KeyEnrolInputSerializer,
    MeOutputSerializer,
    RecoveryCodesOutputSerializer,
    TotpEnrolInputSerializer,
    TotpSetupOutputSerializer,
)
from .views import LoginThrottle


class SecondFactorThrottle(LoginThrottle):
    """Rate "second_factor" per client IP: the steps after the password (#176)."""

    scope = "second_factor"


AUTHENTICATE, REGISTER = "authenticate", "register"
REFUSED = {
    (400, PROBLEM): OpenApiResponse(ProblemSerializer, "Invalid input"),
    (401, PROBLEM): OpenApiResponse(ProblemSerializer, "No password step and no session"),
    (403, PROBLEM): OpenApiResponse(ProblemSerializer, "CSRF, or a fresh second factor needed"),
    (422, PROBLEM): OpenApiResponse(ProblemSerializer, "The factor was not accepted"),
    (429, PROBLEM): OpenApiResponse(ProblemSerializer, "Too many attempts, see Retry-After"),
}


class StepUpRequired(Forbidden):
    default_code = "step_up_required"
    default_detail = "Confirm with your second factor first."


class EnrolmentCodeRequired(Forbidden):
    default_code = "enrolment_code_required"
    default_detail = "Enter the enrolment code a manager of your lab gave you first."


class VerifyFirst(Forbidden):
    default_code = "verify_first"
    default_detail = "This account has a second factor: sign in with it first."


@contextmanager
def _acting(user: User) -> Iterator[None]:
    """The person of the sign-in as the actor of what the step writes."""
    with audit_context(channel=Channel.API, actor=user):
        yield


def _who(request: Request) -> tuple[User, signin.Pending | None]:
    """The signed-in user (a step-up), or the person of the password step."""
    if isinstance(request.user, User):
        return request.user, None
    enforce_csrf(request)
    step = signin.pending(request._request)
    if step is None:
        raise NotAuthenticated
    return step.user, step


def _attempt(request: Request, user: User, step: signin.Pending | None) -> Attempt:
    attempt = (
        signin.attempt_for(request, step)
        if step
        else Attempt.of(request, user.username, Surface.API)
    )
    refusal = attempt.refusal()
    if refusal is not None:
        raise Throttled(wait=refusal.wait_seconds(timezone.now()))
    return attempt


def _signed_in(request: Request, user: User, step: signin.Pending | None) -> Response:
    response = Response(MeOutputSerializer(user).data)
    if step is None:
        signin.mark_verified(request._request)
    else:
        signin.finish(request._request, step, response)
    return response


@extend_schema(request=CodeInputSerializer, responses={200: MeOutputSerializer, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def second_factor_code(request: Request) -> Response:
    """A TOTP code or a recovery code: signs in after the password step, or confirms a
    signed-in user again. A wrong code counts as a failed login (ADR 0007)."""
    user, step = _who(request)
    data = CodeInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    attempt = _attempt(request, user, step)
    code: str = data.validated_data["code"]
    with _acting(user):
        if data.validated_data["method"] == "totp":
            ok = factors.totp_verify(user=user, code=code)
        else:
            ok = factors.recovery_code_use(user=user, code=code)
    if not ok:
        attempt.failed()
        raise factors.WrongCode(attr="code")
    return _signed_in(request, user, step)


@extend_schema(request=None, responses={200: CeremonyOutputSerializer, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def second_factor_key_options(request: Request) -> Response:
    """The challenge for one of the user's security keys."""
    user, _ = _who(request)
    if not SecurityKey.objects.filter(user=user).exists():
        raise factors.KeyRefused("This account has no security key.")
    rp_id, _origins = signin.site(request._request)
    ceremony = factors.key_authentication(user, rp_id)
    signin.keep_challenge(request._request, AUTHENTICATE, ceremony.challenge)
    return Response({"options": ceremony.options})


@extend_schema(request=CredentialInputSerializer, responses={200: MeOutputSerializer, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def second_factor_key(request: Request) -> Response:
    """The key's answer: signs in, or confirms a signed-in user again. A refused answer counts
    as a failed login."""
    user, step = _who(request)
    data = CredentialInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    attempt = _attempt(request, user, step)
    challenge = signin.take_challenge(request._request, AUTHENTICATE)
    rp_id, origins = signin.site(request._request)
    credential: dict[str, Any] = data.validated_data["credential"]
    ok = challenge is not None and factors.key_verify(
        user=user, credential=credential, challenge=challenge, rp_id=rp_id, origins=origins
    )
    if not ok:
        attempt.failed()
        raise factors.KeyRefused
    return _signed_in(request, user, step)


# --- enrolment ---------------------------------------------------------------------------------


def _enrolling(request: Request) -> tuple[User, signin.Pending | None]:
    """A signed-in user after a fresh second factor, or the person of the password step whose
    account has no factor yet (the first enrolment, ADR 0009: at the next sign-in)."""
    user, step = _who(request)
    if step is None:
        if not signin.fresh(request._request):
            raise StepUpRequired
        return user, None
    if factors.has_second_factor(user):
        raise VerifyFirst
    if not signin.enrolment_allowed(request._request, step):
        raise EnrolmentCodeRequired
    return user, step


def _enrolled(request: Request, user: User, step: signin.Pending | None) -> Response:
    """The first factor ends the sign-in and issues the recovery codes, shown this once."""
    if step is None:
        return Response({"me": None, "recovery_codes": []}, status=status.HTTP_201_CREATED)
    with _acting(user):
        codes = factors.recovery_codes_issue(user=user)
    response = Response(
        {"me": MeOutputSerializer(user).data, "recovery_codes": codes},
        status=status.HTTP_201_CREATED,
    )
    signin.finish(request._request, step, response)
    return response


@extend_schema(request=EnrolmentCodeInputSerializer, responses={204: None, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def enrolment_code(request: Request) -> Response:
    """The manager's one-time code, after the password, for an account without a factor
    (#176): without it no first factor is enrolled. A wrong code counts as a failed login."""
    user, step = _who(request)
    if step is None or factors.has_second_factor(user):
        raise VerifyFirst
    data = EnrolmentCodeInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    attempt = _attempt(request, user, step)
    with _acting(user):
        ok = factors.enrolment_code_use(user=user, code=data.validated_data["code"])
    if not ok:
        attempt.failed()
        raise factors.WrongCode("The enrolment code is not valid, used or expired.", attr="code")
    signin.allow_enrolment(request._request, step)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=None, responses={200: CeremonyOutputSerializer, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def key_registration_options(request: Request) -> Response:
    user, _ = _enrolling(request)
    rp_id, _origins = signin.site(request._request)
    ceremony = factors.key_registration(user, rp_id)
    signin.keep_challenge(request._request, REGISTER, ceremony.challenge)
    return Response({"options": ceremony.options})


@extend_schema(
    request=KeyEnrolInputSerializer, responses={201: EnrolledOutputSerializer, **REFUSED}
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def key_enrol(request: Request) -> Response:
    user, step = _enrolling(request)
    data = KeyEnrolInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    challenge = signin.take_challenge(request._request, REGISTER)
    if challenge is None:
        raise factors.KeyRefused("The security key took too long. Start again.")
    rp_id, origins = signin.site(request._request)
    with _acting(user):
        factors.key_enrol(
            user=user,
            credential=data.validated_data["credential"],
            challenge=challenge,
            rp_id=rp_id,
            origins=origins,
            name=data.validated_data["name"],
        )
    return _enrolled(request, user, step)


@extend_schema(request=None, responses={200: TotpSetupOutputSerializer, **REFUSED})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def totp_setup(request: Request) -> Response:
    """A new secret for an authenticator app, kept in the session until its first code."""
    user, _ = _enrolling(request)
    secret = factors.totp_new_secret()
    signin.keep_totp_setup(request._request, secret)
    return Response({"secret": secret, "uri": factors.totp_uri(user, secret)})


@extend_schema(
    request=TotpEnrolInputSerializer, responses={201: EnrolledOutputSerializer, **REFUSED}
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SecondFactorThrottle])
def totp_enrol(request: Request) -> Response:
    user, step = _enrolling(request)
    data = TotpEnrolInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    secret = signin.totp_setup(request._request)
    if secret is None:
        raise factors.WrongCode("Set up the app again: the secret expired.", attr="code")
    with _acting(user):
        factors.totp_enrol(user=user, secret=secret, code=data.validated_data["code"])
    signin.end_totp_setup(request._request)
    return _enrolled(request, user, step)


# --- the user's own factors ------------------------------------------------------------------


def _fresh_user(request: Request) -> User:
    user = current_user(request)
    if not signin.fresh(request._request):
        raise StepUpRequired
    return user


@extend_schema(responses={200: FactorsOutputSerializer})
@api_view(["GET"])
def factor_list(request: Request) -> Response:
    user = current_user(request)
    keys = SecurityKey.objects.filter(user=user).order_by("created_at")
    return Response(
        {
            "security_keys": [
                {
                    "public_id": k.public_id,
                    "name": k.name,
                    "created_at": k.created_at,
                    "last_used_at": k.last_used_at,
                }
                for k in keys
            ],
            "totp": hasattr(user, "totp_device") and user.totp_device is not None,
            "recovery_codes_left": factors.unused_recovery_codes(user),
            "fresh": signin.fresh(request._request),
        }
    )


@extend_schema(request=None, responses={204: None, **REFUSED})
@api_view(["DELETE"])
def key_remove(request: Request, public_id: UUID) -> Response:
    user = _fresh_user(request)
    key = SecurityKey.objects.filter(user=user, public_id=public_id).first()
    if key is None:
        raise NotFound
    factors.key_remove(user=user, key=key)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=None, responses={204: None, **REFUSED})
@api_view(["DELETE"])
def totp_remove(request: Request) -> Response:
    factors.totp_remove(user=_fresh_user(request))
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=None, responses={201: RecoveryCodesOutputSerializer, **REFUSED})
@api_view(["POST"])
def recovery_codes_issue(request: Request) -> Response:
    """Ten new codes in place of the old ones, shown this once."""
    codes = factors.recovery_codes_issue(user=_fresh_user(request))
    return Response({"recovery_codes": codes}, status=status.HTTP_201_CREATED)


# --- the reset by two people -----------------------------------------------------------------


def _managed_lab(user: User, lab_id: UUID) -> Lab:
    """A lab where the user is a manager; any other is not found (never say which)."""
    lab = Lab.objects.filter(public_id=lab_id).first()
    if lab is None or access_for(user).role_in(lab.pk) != Role.MANAGER:
        raise NotFound
    return lab


def _reset_output(
    reset: FactorReset, actor: User, member: UUID | None, code: str | None = None
) -> dict[str, Any]:
    return {
        "enrolment_code": code,
        "public_id": reset.public_id,
        "member": member,
        "username": reset.user.username,
        "proposed_by": reset.proposed_by.username,
        "proposed_at": reset.created_at,
        "reason": reset.reason,
        "may_confirm": actor.pk not in {reset.proposed_by_id, reset.user_id},
    }


def _member_id(reset: FactorReset) -> UUID | None:
    if reset.lab_id is None:
        return None
    member: UUID | None = (
        Membership.objects.filter(lab_id=reset.lab_id, user_id=reset.user_id)
        .values_list("public_id", flat=True)
        .first()
    )
    return member


@extend_schema(
    parameters=[OpenApiParameter("lab", UUID, required=True)],
    responses={200: FactorResetOutputSerializer(many=True)},
)
@api_view(["GET"])
def factor_reset_list(request: Request) -> Response:
    """The open resets of a lab, for its managers."""
    actor = current_user(request)
    try:
        lab_id = UUID(str(request.query_params.get("lab", "")))
    except ValueError:
        raise NotFound from None
    lab = _managed_lab(actor, lab_id)
    resets = FactorReset.objects.filter(
        lab=lab, confirmed_at__isnull=True, withdrawn_at__isnull=True
    ).select_related("user", "proposed_by")
    return Response([_reset_output(r, actor, _member_id(r)) for r in resets])


@extend_schema(
    request=FactorResetInputSerializer, responses={201: FactorResetOutputSerializer, **REFUSED}
)
@api_view(["POST"])
def factor_reset_propose(request: Request) -> Response:
    actor = current_user(request)
    data = FactorResetInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    member = (
        Membership.objects.select_related("user", "lab")
        .filter(public_id=data.validated_data["member"])
        .first()
    )
    if member is None:
        raise NotFound
    _managed_lab(actor, member.lab.public_id)
    reset = factors.factor_reset_propose(
        actor=actor, user=member.user, lab=member.lab, reason=data.validated_data["reason"]
    )
    return Response(_reset_output(reset, actor, member.public_id), status=status.HTTP_201_CREATED)


def _open_reset(actor: User, public_id: UUID) -> FactorReset:
    reset = (
        FactorReset.objects.select_related("user", "lab", "proposed_by")
        .filter(public_id=public_id)
        .first()
    )
    if reset is None or reset.lab is None:
        raise NotFound
    _managed_lab(actor, reset.lab.public_id)
    return reset


@extend_schema(
    request=FactorResetReasonInputSerializer,
    responses={200: FactorResetOutputSerializer, **REFUSED},
)
@api_view(["POST"])
def factor_reset_confirm(request: Request, public_id: UUID) -> Response:
    actor = current_user(request)
    data = FactorResetReasonInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    reset, code = factors.factor_reset_confirm(
        actor=actor, reset=_open_reset(actor, public_id), reason=data.validated_data["reason"]
    )
    return Response(_reset_output(reset, actor, _member_id(reset), code))


@extend_schema(
    request=FactorResetReasonInputSerializer,
    responses={200: FactorResetOutputSerializer, **REFUSED},
)
@api_view(["POST"])
def factor_reset_withdraw(request: Request, public_id: UUID) -> Response:
    actor = current_user(request)
    data = FactorResetReasonInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    reset = factors.factor_reset_withdraw(
        actor=actor, reset=_open_reset(actor, public_id), reason=data.validated_data["reason"]
    )
    return Response(_reset_output(reset, actor, _member_id(reset)))


@extend_schema(
    request=EnrolmentCodeIssueInputSerializer,
    responses={201: EnrolmentCodeOutputSerializer, **REFUSED},
)
@api_view(["POST"])
def enrolment_code_issue(request: Request) -> Response:
    """A manager issues a member of their lab a one-time code for the first enrolment (#176)."""
    actor = current_user(request)
    data = EnrolmentCodeIssueInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    member = (
        Membership.objects.select_related("user", "lab")
        .filter(public_id=data.validated_data["member"])
        .first()
    )
    if member is None:
        raise NotFound
    _managed_lab(actor, member.lab.public_id)
    code = factors.enrolment_code_issue(
        actor=actor, user=member.user, lab=member.lab, reason=data.validated_data["reason"]
    )
    return Response(
        {
            "code": code,
            "username": member.user.username,
            "valid_hours": settings.ENROLMENT_CODE_HOURS,
        },
        status=status.HTTP_201_CREATED,
    )
