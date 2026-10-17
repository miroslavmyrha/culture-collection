"""Labs and who belongs to them, with which role.

Labs are created by staff in Django admin; the API only reads them. Members are
managed by the lab's managers through the API (services.py has the rules).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper

from cultures.core.models import PublicModel

from .permissions import Role
from .querysets import LabQuerySet, LabScopedQuerySet

# Services map a violation of these to a field error, so the names are constants.
LAB_NAME_UNIQUE = "labs_lab_name_uniq"
LAB_CODE_UNIQUE = "labs_lab_code_uniq"
MEMBERSHIP_UNIQUE = "labs_membership_user_lab_uniq"


class Lab(PublicModel):
    name = models.CharField(max_length=100)
    # Short, upper-case, used in labels and identifiers later (strain numbers).
    code = models.CharField(max_length=10)

    objects = LabQuerySet["Lab"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # Case-insensitive: "Mycology" and "mycology" are the same lab to a person.
            models.UniqueConstraint(Upper("name"), name=LAB_NAME_UNIQUE),
            models.UniqueConstraint(fields=["code"], name=LAB_CODE_UNIQUE),
            models.CheckConstraint(condition=~Q(name=""), name="labs_lab_name_not_blank"),
            models.CheckConstraint(
                condition=Q(code__regex=r"^[A-Z0-9]{2,10}$"), name="labs_lab_code_format"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Membership(PublicModel):
    # PROTECT both ways: users are deactivated, never deleted, and a lab with members
    # cannot be deleted by accident. Audit events point at both.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)

    objects = LabScopedQuerySet["Membership"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["user", "lab"], name=MEMBERSHIP_UNIQUE),
            models.CheckConstraint(
                condition=Q(role__in=Role.values), name="labs_membership_role_valid"
            ),
        ]
        indexes = [models.Index(fields=["lab", "role"], name="labs_membership_lab_role_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.lab_id} as {self.role}"
