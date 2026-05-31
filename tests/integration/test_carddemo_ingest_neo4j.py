"""Full-loop integration: real CardDemo COBOL -> CobolParser (real extractor
JAR) -> CodeGraphIngester -> a real Neo4j (testcontainer). Proves the graph
actually contains Program nodes and non-zero entities/relationships from a real
ingest, not a fixture.

Skips (never errors/hangs) when Docker/testcontainers/JAR/Java are unavailable.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# A small but real subset of CardDemo: the batch (CB*) programs COPY members
# from app/cpy, so we copy those programs + the whole app/cpy copybook dir.
SUBSET_PROGRAMS = [
    "CBACT01C.cbl",
    "CBACT02C.cbl",
    "CBACT03C.cbl",
    "CBACT04C.cbl",
    "CBCUS01C.cbl",
    "CBTRN01C.cbl",
]


def _require(cond: bool, reason: str) -> None:
    if not cond:
        pytest.skip(reason)


def _build_subset(carddemo_root: Path, dst: Path) -> Path:
    """Copy a handful of real programs + the real app/cpy copybooks into dst."""
    (dst / "app" / "cbl").mkdir(parents=True)
    for name in SUBSET_PROGRAMS:
        src = carddemo_root / "app" / "cbl" / name
        if src.exists():
            shutil.copy2(src, dst / "app" / "cbl" / name)
    shutil.copytree(carddemo_root / "app" / "cpy", dst / "app" / "cpy")
    return dst


def test_carddemo_subset_ingests_into_neo4j(carddemo_root, tmp_path):
    # --- guards: skip cleanly if any real dependency is missing ---
    jar = os.getenv("COBOL_EXTRACTOR_JAR")
    _require(bool(jar) and Path(jar).exists(), "COBOL_EXTRACTOR_JAR not set / missing")
    _require(shutil.which("java") is not None or bool(os.getenv("JAVA_HOME")), "no Java")

    try:
        from testcontainers.neo4j import Neo4jContainer
    except Exception as exc:  # pragma: no cover - import guard
        pytest.skip(f"testcontainers/neo4j unavailable: {exc}")

    try:
        import docker  # noqa: F401

        docker.from_env().ping()
    except Exception as exc:
        pytest.skip(f"Docker unavailable: {exc}")

    repo = _build_subset(carddemo_root, tmp_path / "carddemo_subset")
    n_programs = len(list((repo / "app" / "cbl").glob("*.cbl")))
    assert n_programs >= 1

    from cobol_modernizer.cobol.parser import CobolParser
    from cobol_modernizer.language_registry import (
        register_repo_extractor,
        run_repo_extractors,
    )
    from cobol_modernizer import language_registry
    from cobol_modernizer.neo4j_client import Neo4jClient
    from cobol_modernizer.ingestion import CodeGraphIngester

    # Wire CobolParser (relative copybook dir -> Deliverable-1 fix resolves it
    # absolute under repo_root) as a repo extractor so CodeGraphIngester picks up
    # COBOL through its normal parse_directory -> run_repo_extractors path.
    def _cobol_extractor(root: Path):
        parser = CobolParser(
            root,
            jar_path=jar,
            copybook_dirs=("app/cpy",),  # relative on purpose: exercises the fix
            java_home=os.getenv("JAVA_HOME"),
        )
        return parser.parse_repo()

    saved = list(language_registry._extractors)
    register_repo_extractor(_cobol_extractor)
    try:
        # sanity: real parse must produce Program entities before we touch Neo4j
        parse_results = run_repo_extractors(repo)
        programs_parsed = sum(
            1
            for r in parse_results
            for e in r.entities
            if e.kind.value == "Program"
        )
        assert programs_parsed >= 1, "real extractor produced no Program entities"

        with Neo4jContainer("neo4j:5.26-community") as neo4j:
            uri = neo4j.get_connection_url()
            with Neo4jClient(
                uri=uri, user="neo4j", password=neo4j.password
            ) as client:
                ingester = CodeGraphIngester(client, repo)
                # with_git=False: the subset tmp dir is not a git repo
                stats = ingester.ingest(clear=True, with_git=False)

                programs = client.run(
                    "MATCH (p:Program) RETURN count(p) AS c"
                )[0]["c"]
                graph = client.stats()
                imports = client.run(
                    "MATCH ()-[r:IMPORTS]->() RETURN count(r) AS c"
                )[0]["c"]

        # --- real, non-zero assertions ---
        assert programs >= 1, f"expected >=1 Program node, got {programs}"
        assert graph["nodes"] > 0, "no nodes written to Neo4j"
        assert graph["relationships"] > 0, "no relationships written to Neo4j"
        assert stats["entities"] > 0
        assert imports >= 1, "expected COPY -> IMPORTS edges"

        print(
            f"\n[neo4j-ingest] programs(parsed)={programs_parsed} "
            f"Program nodes={programs} total nodes={graph['nodes']} "
            f"relationships={graph['relationships']} IMPORTS={imports} "
            f"ingester stats={stats}"
        )
    finally:
        language_registry._extractors[:] = saved
