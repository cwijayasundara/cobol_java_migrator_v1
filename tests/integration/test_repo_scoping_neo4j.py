"""Task 0b: repo-scoped ingestion. Proves ingest_parse_results writes a `repo`
property, isolates same-named programs across repos (no global qualified_name
collision), persists v2 DataItem columns + IO edge metadata, and that the
repo-scoped graph_ops read path resolves the right repo's node. Needs Docker."""
from __future__ import annotations

from pathlib import Path

from cobol_modernizer.ingestion import ingest_parse_results
from cobol_modernizer.models import (
    CodeEntity, CodeRelationship, EntityKind, ParseResult, RelKind,
)


def _prog(name: str, fp: str) -> CodeEntity:
    return CodeEntity(kind=EntityKind.PROGRAM, qualified_name=name, simple_name=name,
                      file_path=fp, start_line=1, end_line=10)


def test_ingest_parse_results_is_repo_scoped(neo4j_graph):
    ingest_parse_results(neo4j_graph,
                         [ParseResult(entities=[_prog("SHARED", "a.cbl")], relationships=[], file_path="a.cbl")],
                         repo="repoA")
    ingest_parse_results(neo4j_graph,
                         [ParseResult(entities=[_prog("SHARED", "b.cbl")], relationships=[], file_path="b.cbl")],
                         repo="repoB")

    a = neo4j_graph.run("MATCH (e:CodeEntity {repo:$r, qualified_name:'SHARED'}) RETURN e.file_path AS fp", r="repoA")
    b = neo4j_graph.run("MATCH (e:CodeEntity {repo:$r, qualified_name:'SHARED'}) RETURN e.file_path AS fp", r="repoB")
    assert len(a) == 1 and a[0]["fp"] == "a.cbl"
    assert len(b) == 1 and b[0]["fp"] == "b.cbl"   # no cross-repo collision

    # repo-scoped read path (every graph_op filters {repo:$repo})
    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.graph_ops import get_entity
    deps = GraphDeps(client=neo4j_graph, repo_id="repoA", repo_path=Path("."))
    assert get_entity(deps, "SHARED")["file_path"] == "a.cbl"


def test_ingest_persists_v2_columns_and_edge_metadata(neo4j_graph):
    di = CodeEntity(kind=EntityKind.DATA_ITEM, qualified_name="P.WS-BAL", simple_name="WS-BAL",
                    file_path="p.cbl", start_line=5, end_line=5,
                    level=5, picture="S9(10)V99", usage="COMP-3", parent_qname="P.WS-REC")
    rel = CodeRelationship(source_qname="P", target_qname="ACCTDAT", kind=RelKind.READS,
                           file_path="p.cbl", line=10,
                           metadata={"resource": "ACCTDAT", "resourceType": "VSAM", "mode": "sequential"})
    pr = ParseResult(entities=[_prog("P", "p.cbl"), di], relationships=[rel], file_path="p.cbl")
    ingest_parse_results(neo4j_graph, [pr], repo="r1")

    row = neo4j_graph.run(
        "MATCH (e:DataItem {repo:'r1', qualified_name:'P.WS-BAL'}) "
        "RETURN e.picture AS pic, e.usage AS u, e.level AS lvl, e.parent_qname AS parent")[0]
    assert row["pic"] == "S9(10)V99" and row["u"] == "COMP-3"
    assert row["lvl"] == 5 and row["parent"] == "P.WS-REC"

    edge = neo4j_graph.run(
        "MATCH (:CodeEntity {repo:'r1', qualified_name:'P'})-[r:READS]->(t) "
        "RETURN r.resource AS res, r.mode AS mode, t.qualified_name AS tgt")[0]
    assert edge["res"] == "ACCTDAT" and edge["mode"] == "sequential" and edge["tgt"] == "ACCTDAT"
