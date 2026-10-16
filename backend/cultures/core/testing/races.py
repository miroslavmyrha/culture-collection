from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock


@contextmanager
def run_before(target: object, name: str, competitor: Callable[[], object]) -> Iterator[None]:
    """Run `competitor` once, right before the first call of target.name.

    Puts a competing write at an exact point of the code under test, with no
    threads: the deterministic way to test what happens when someone else wins.
    """
    original = getattr(target, name)
    done = False

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        nonlocal done
        if not done:
            done = True
            competitor()
        return original(*args, **kwargs)

    with mock.patch.object(target, name, wrapper):
        yield
