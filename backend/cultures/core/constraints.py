"""The database's constraints as the final arbiter of a write (#232).

A check before a save can race with another request; the constraint cannot. A write runs in a
savepoint, so the caller's transaction stays usable, and the constraint it violates is turned
into the domain error the caller names for it. Any other integrity error is raised as it is.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model


def constraint_of(error: IntegrityError) -> str:
    """The name of the constraint the database reports, or "" (psycopg's error behind Django's)."""
    diag = getattr(error.__cause__, "diag", None)
    return str(getattr(diag, "constraint_name", None) or "")


@contextmanager
def arbitrated(errors: Mapping[str, Exception]) -> Iterator[None]:
    """A savepoint around the writes inside it; a violated constraint in `errors` raises its
    error."""
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        error = errors.get(constraint_of(exc))
        if error is not None:
            raise error from exc
        raise


def save_arbitrated(obj: Model, errors: Mapping[str, Exception], **kwargs: Any) -> None:
    """`obj.save(**kwargs)` under `arbitrated(errors)`."""
    with arbitrated(errors):
        obj.save(**kwargs)
