"""Full-loop integration: real COBOL -> CobolParser (real extractor JAR) ->
CodeGraphIngester -> a real Neo4j (testcontainer). Proves the graph actually
contains Program nodes and non-zero entities/relationships from a real ingest,
not a fixture. Works against any COBOL sample in source_code_to_analyse.

Skips (never errors/hangs) when Docker/testcontainers/JAR/Java are unavailable.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from _cobol_helpers import discover_copybook_dirs, discover_programs

# Cap on programs copied into the throwaway repo — a small but real subset keeps
# the testcontainer ingest fast while still exercising COPY -> IMPORTS edges.
SUBSET_LIMIT = 6


def _require(cond: bool, reason: str) -> None:
    if not cond:
        pytest.skip(reason)


def _build_subset(sample_root: Path, dst: Path) -> tuple[Path, list[str]]:
    """Copy a handful of discovered programs + every copybook dir into dst.
    Returns (repo_root, copybook_dirs-relative-to-repo). Layout-independent."""
    (dst / "cbl").mkdir(parents=True)
    for src in discover_programs(sample_root)[:SUBSET_LIMIT]:
        shutil.copy2(src, dst / "cbl" / src.name)
    copybook_dirs: list[str] = []
    for i, d in enumerate(discover_copybook_dirs(sample_root)):
        rel = f"copybooks/d{i}"
        sub = dst / rel
        sub.mkdir(parents=True)
        for cpy in d.glob("*.cpy"):
            shutil.copy2(cpy, sub / cpy.name)
        copybook_dirs.append(rel)
    return dst, copybook_dirs


def test_cobol_subset_ingests_into_neo4j(cobol_sample_root, tmp_path):
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

    repo, copybook_dirs = _build_subset(cobol_sample_root, tmp_path / "cobol_subset")
    n_programs = len(list((repo / "cbl").glob("*.cbl")))
    assert n_programs >= 1

    from cobol_modernizer.cobol.parser import CobolParser
    from cobol_modernizer.language_registry import (
        register_repo_extractor,
        run_repo_extractors,
    )
    from cobol_modernizer import language_registry
    from cobol_modernizer.neo4j_client import Neo4jClient
    from cobol_modernizer.ingestion import CodeGraphIngester

    # Wire CobolParser (relative copybook dirs -> Deliverable-1 fix resolves them
    # absolute under repo_root) as a repo extractor so CodeGraphIngester picks up
    # COBOL through its normal parse_directory -> run_repo_extractors path.
    def _cobol_extractor(root: Path):
        parser = CobolParser(
            root,
            jar_path=jar,
            copybook_dirs=tuple(copybook_dirs),  # relative on purpose: exercises the fix
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
