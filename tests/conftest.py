"""Shared test fixtures.

The COBOL under test lives in ``source_code_to_analyse/`` at the repo root
(any COBOL app can be dropped there). Point at a different tree with the
``COBOL_SAMPLE_DIR`` environment variable. Discovery helpers live in
``tests/_cobol_helpers.py`` so they can be imported directly by test modules.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _cobol_helpers import discover_programs, sample_root


@pytest.fixture
def cobol_sample_root() -> Path:
    """A COBOL source tree to analyse. Skips (never fails) when none is present."""
    root = sample_root()
    if not root.exists():
        pytest.skip(f"no COBOL sample dir at {root} (set COBOL_SAMPLE_DIR)")
    if not discover_programs(root):
        pytest.skip(f"no COBOL programs found under {root}")
    return root


@pytest.fixture
def neo4j_graph():
    """A live Neo4jClient backed by a throwaway Neo4j testcontainer, schema applied.
    Skips cleanly (never fails) when testcontainers/Docker are unavailable, so the
    suite stays green on machines without Docker. Shared by all v2 graph tests."""
    try:
        from testcontainers.neo4j import Neo4jContainer
    except Exception as exc:  # pragma: no cover - import guard
        pytest.skip(f"testcontainers/neo4j unavailable: {exc}")
    try:
        import docker  # noqa: F401

        docker.from_env().ping()
    except Exception as exc:
        pytest.skip(f"Docker unavailable: {exc}")

    from cobol_modernizer.neo4j_client import Neo4jClient

    with Neo4jContainer("neo4j:5.26-community") as neo4j:
        uri = neo4j.get_connection_url()
        with Neo4jClient(uri=uri, user="neo4j", password=neo4j.password) as client:
            client.apply_schema()
            yield client
