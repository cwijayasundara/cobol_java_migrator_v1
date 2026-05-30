"""Engine + session helpers for the Postgres run/audit store."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or os.environ["POSTGRES_URL"], future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = Session(engine or make_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
