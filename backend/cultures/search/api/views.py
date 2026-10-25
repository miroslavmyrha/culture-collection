from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.labs.access import access_of

from .. import selectors
from .serializers import SearchInputSerializer, SearchSerializer


@extend_schema(
    parameters=[SearchInputSerializer],
    responses={
        200: SearchSerializer,
        (400, PROBLEM): OpenApiResponse(ProblemSerializer, "The text is too long"),
    },
)
@api_view(["GET"])
def search(request: Request) -> Response:
    """Strains, vials, deposits and requests that match the text, by kind, from the person's
    labs and only the kinds their role there may read. A regulated strain's vial names its
    strain and lab, never its place. No lab, or fewer than 2 characters: no groups."""
    data = SearchInputSerializer(data=request.query_params)
    data.is_valid(raise_exception=True)
    groups = selectors.search(access=access_of(request), text=data.validated_data["q"])
    return Response(SearchSerializer({"groups": groups}).data)
