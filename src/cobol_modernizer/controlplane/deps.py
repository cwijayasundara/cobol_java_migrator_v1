"""FastAPI dependencies for the control plane: a Postgres Session and a read-only
Neo4j client. Both are overridden in tests via app.dependency_overrides (sqlite
session; testcontainer Neo4j)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.db import make_engine


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return make_engine(os.environ["POSTGRES_URL"])


def get_session() -> Iterator[Session]:
    """Yield a transactional Session: commit on success, rollback on error."""
    session = Session(_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_neo4j() -> Iterator[object]:
    """Yield a read-only Neo4jClient built from env. Overridden in tests."""
    from cobol_modernizer.neo4j_client import Neo4jClient

    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "neo4j"),
    )
    try:
        yield client
    finally:
        client.close()
