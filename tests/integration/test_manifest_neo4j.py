"""Task 0a: Neo4jClient.save_manifest/load_manifest round-trip against a real
Neo4j (testcontainer). IncrementalIngester depends on these; previously only the
unit FakeClient implemented them. Skips cleanly without Docker."""
from __future__ import annotations


def test_manifest_roundtrip(neo4j_graph):
    neo4j_graph.save_manifest("repoX", {"a.cbl": "h1", "b.cpy": "h2"})
    assert neo4j_graph.load_manifest("repoX") == {"a.cbl": "h1", "b.cpy": "h2"}


def test_manifest_missing_returns_empty(neo4j_graph):
    assert neo4j_graph.load_manifest("never-saved") == {}


def test_manifest_overwrite(neo4j_graph):
    neo4j_graph.save_manifest("repoY", {"a.cbl": "h1"})
    neo4j_graph.save_manifest("repoY", {"a.cbl": "h2", "c.cbl": "h3"})
    assert neo4j_graph.load_manifest("repoY") == {"a.cbl": "h2", "c.cbl": "h3"}
