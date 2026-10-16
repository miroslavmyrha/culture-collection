import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from model_bakery import baker
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from cultures.core.pagination import LimitOffsetPagination, with_total_ordering
from cultures.users.models import User

pytestmark = pytest.mark.django_db


def paginate(query: str, queryset: object) -> list[User]:
    request = Request(APIRequestFactory().get(f"/x/{query}"))
    page = LimitOffsetPagination().paginate_queryset(queryset, request)
    assert page is not None
    return page


def test_limit_is_capped() -> None:
    baker.make(User, _quantity=205)
    assert len(paginate("?limit=1000000", User.objects.order_by("username"))) == 200


def test_pk_is_appended_to_the_ordering() -> None:
    ordered = with_total_ordering(User.objects.order_by("-last_name"))
    assert list(ordered.query.order_by) == ["-last_name", "pk"]
    assert list(with_total_ordering(User.objects.order_by("-pk")).query.order_by) == ["-pk"]


def test_meta_ordering_is_kept_when_pk_is_appended() -> None:
    assert Permission._meta.ordering  # the case under test: an ordering from Meta
    ordered = with_total_ordering(Permission.objects.all())
    assert list(ordered.query.order_by) == [*Permission._meta.ordering, "pk"]


def test_unordered_queryset_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="no ordering"):
        paginate("", User.objects.all())


def test_pages_over_tied_keys_neither_repeat_nor_skip() -> None:
    users = baker.make(User, last_name="Same", _quantity=30)
    queryset = User.objects.order_by("last_name")
    seen = [
        u.pk for offset in range(0, 30, 7) for u in paginate(f"?limit=7&offset={offset}", queryset)
    ]
    assert sorted(seen) == sorted(u.pk for u in users)
    assert len(seen) == len(set(seen))
