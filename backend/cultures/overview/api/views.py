from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.labs.access import access_of

from .. import activity, selectors
from .serializers import ActivitySerializer, OverviewSerializer


@extend_schema(responses={200: OverviewSerializer})
@api_view(["GET"])
def overview(request: Request) -> Response:
    """Home: what waits for the signed-in person in each of their labs, by kind, and per lab the
    role, the figures and the actions the role may start. Scoped by the person's memberships:
    nobody else's labs, and in each lab only what the role may handle or see. No lab: empty."""
    access = access_of(request)
    labs = selectors.my_labs(access=access)
    codes = {entry.lab.pk: str(entry.lab.public_id) for entry in labs}
    data = {"waiting": selectors.waiting(access=access), "labs": labs}
    return Response(OverviewSerializer(data, context={"labs": codes}).data)


@extend_schema(responses={200: ActivitySerializer})
@api_view(["GET"])
def recent_activity(request: Request) -> Response:
    """The latest 20 audit events of the person's labs they may read, newest first, one line
    each. A line names its subject and the actor's pseudonymous label, never a location or a
    person's data."""
    lines = activity.recent(access=access_of(request))
    return Response(ActivitySerializer({"results": lines}).data)
