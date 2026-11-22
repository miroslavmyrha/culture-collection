from rest_framework import serializers

from cultures.users.models import User


class LoginInputSerializer(serializers.Serializer[None]):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(
        max_length=256, trim_whitespace=False, style={"input_type": "password"}
    )


class MeOutputSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("public_id", "username", "first_name", "last_name", "email")
        read_only_fields = fields


SIGN_IN_STEPS = ("second_factor", "enrol")
METHODS = ("security_key", "totp", "recovery_code")


class LoginStepOutputSerializer(serializers.Serializer[None]):
    """What the password step leads to (#176): give a second factor, or enrol the first one."""

    step = serializers.ChoiceField(choices=SIGN_IN_STEPS)
    methods = serializers.ListField(child=serializers.ChoiceField(choices=METHODS))


class CodeInputSerializer(serializers.Serializer[None]):
    method = serializers.ChoiceField(choices=("totp", "recovery_code"))
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class CredentialInputSerializer(serializers.Serializer[None]):
    """The browser's answer to a WebAuthn ceremony, as @simplewebauthn/browser returns it."""

    credential = serializers.JSONField()


class KeyEnrolInputSerializer(CredentialInputSerializer):
    name = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")


class TotpEnrolInputSerializer(serializers.Serializer[None]):
    code = serializers.CharField(max_length=16, trim_whitespace=True)


class CeremonyOutputSerializer(serializers.Serializer[None]):
    """WebAuthn options for navigator.credentials, in the JSON form of the spec."""

    options = serializers.JSONField()


class TotpSetupOutputSerializer(serializers.Serializer[None]):
    secret = serializers.CharField()
    uri = serializers.CharField()


class EnrolledOutputSerializer(serializers.Serializer[None]):
    """After an enrolment. On the first factor the sign-in ends here: me is the signed-in user,
    and the recovery codes are shown this once."""

    me = MeOutputSerializer(allow_null=True)
    recovery_codes = serializers.ListField(child=serializers.CharField())


class RecoveryCodesOutputSerializer(serializers.Serializer[None]):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class SecurityKeyOutputSerializer(serializers.Serializer[None]):
    public_id = serializers.UUIDField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_used_at = serializers.DateTimeField(allow_null=True)


class FactorsOutputSerializer(serializers.Serializer[None]):
    security_keys = SecurityKeyOutputSerializer(many=True)
    totp = serializers.BooleanField()
    recovery_codes_left = serializers.IntegerField()
    fresh = serializers.BooleanField(
        help_text="A second factor in the last minutes: removal allowed"
    )


class FactorResetReasonInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000)


class FactorResetInputSerializer(FactorResetReasonInputSerializer):
    member = serializers.UUIDField(help_text="The membership of the person, in the lab")


class EnrolmentCodeInputSerializer(serializers.Serializer[None]):
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class EnrolmentCodeIssueInputSerializer(FactorResetReasonInputSerializer):
    member = serializers.UUIDField(help_text="The membership of the person, in the lab")


class EnrolmentCodeOutputSerializer(serializers.Serializer[None]):
    """The code, shown this once to the manager who hands it over (#176)."""

    code = serializers.CharField()
    username = serializers.CharField()
    valid_hours = serializers.IntegerField()


class FactorResetOutputSerializer(serializers.Serializer[None]):
    public_id = serializers.UUIDField()
    member = serializers.UUIDField(allow_null=True)
    username = serializers.CharField()
    proposed_by = serializers.CharField()
    proposed_at = serializers.DateTimeField()
    reason = serializers.CharField()
    may_confirm = serializers.BooleanField()
    enrolment_code = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Only on the confirmation: the code to hand over, shown this once",
    )
