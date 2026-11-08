"""Short transaction boundary shared by domain services."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

from sqlalchemy.orm import Session


@contextmanager
def transaction(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """Commit on normal exit and roll back all changes on any exception."""
    with session_factory() as session:
        with session.begin():
            yield session
