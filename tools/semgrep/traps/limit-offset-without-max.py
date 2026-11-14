from rest_framework import pagination, viewsets
from rest_framework.pagination import LimitOffsetPagination

# ruleid: limit-offset-without-max
REST_FRAMEWORK = {"DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination"}


# ruleid: limit-offset-without-max
class LoosePagination(LimitOffsetPagination):
    default_limit = 50


# ok: limit-offset-without-max
class ProjectPagination(pagination.LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


class SampleViewSet(viewsets.ModelViewSet):
    # ruleid: limit-offset-without-max
    pagination_class = LimitOffsetPagination


class BoxViewSet(viewsets.ModelViewSet):
    # ok: limit-offset-without-max
    pagination_class = ProjectPagination
