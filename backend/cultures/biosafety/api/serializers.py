from datetime import date

from rest_framework import serializers

from cultures.biosafety.models import AuthorisationKind, Issuer, LabAuthorisation
from cultures.biosafety.selectors import Standing


class LabPermitOutputSerializer(serializers.ModelSerializer[LabAuthorisation]):
    """A lab permit as staff recorded it, with where it stands on the selector's day."""

    kind = serializers.ChoiceField(choices=AuthorisationKind.choices, read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    issuer = serializers.ChoiceField(choices=Issuer.choices, read_only=True)
    issuer_label = serializers.CharField(source="get_issuer_display", read_only=True)
    # Annotated by selectors.permit_list for the same Czech day.
    standing = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in Standing], read_only=True
    )
    last_valid_day = serializers.DateField(allow_null=True, read_only=True)
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = LabAuthorisation
        fields = (
            "public_id",
            "kind",
            "kind_label",
            "issuer",
            "issuer_label",
            "permit_reference",
            "valid_from",
            "expires_on",
            "ended_on",
            "end_reason",
            "standing",
            "last_valid_day",
            "days_left",
        )
        read_only_fields = fields

    def get_days_left(self, obj: LabAuthorisation) -> int | None:
        """Whole days from today to the last valid day (0 on that day itself), only for a
        permit in force that states one."""
        last: date | None = getattr(obj, "last_valid_day", None)
        if last is None or getattr(obj, "standing", None) not in _IN_FORCE:
            return None
        today: date = self.context["today"]
        return (last - today).days


_IN_FORCE = frozenset({Standing.VALID.value, Standing.EXPIRES_SOON.value})
