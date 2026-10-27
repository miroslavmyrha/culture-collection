from datetime import date
from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from cultures.biosafety import selectors
from cultures.biosafety.models import LabAuthorisation
from cultures.biosafety.policy import permit_today
from cultures.core.api import ScopedReadOnlyViewSet
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .serializers import LabPermitOutputSerializer

LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


# The lab's permits (ADR 0009, Lab authorisation), read only: staff record and end them in
# Django admin. Managers read them (biosafety.view_permits); a member of another role gets 403
# on the list and 404 on a single permit (the rows are scoped by the permission, like deposits),
# a non-member 404 on both. All of them in one answer, not paged: a lab holds a few permits per
# kind, and a page would cut the history from what expires soon. Each row says where it stands
# on today's Czech day (policy.permit_today), the same day for every row of the answer.
# (Comments, not a docstring: a docstring becomes the description of every operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class PermitViewSet(ScopedReadOnlyViewSet):
    action_perms = {"list": Perm.VIEW_LAB_PERMITS, "retrieve": Perm.VIEW_LAB_PERMITS}
    serializer_class = LabPermitOutputSerializer
    pagination_class = None

    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    @cached_property
    def today(self) -> date:
        return permit_today()

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.permit_list(access=access_of(self.request), lab=self.lab, today=self.today)

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "today": self.today}

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, LabAuthorisation) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)
