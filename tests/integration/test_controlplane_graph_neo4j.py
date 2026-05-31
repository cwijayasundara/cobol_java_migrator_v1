import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_graph_and_entity_endpoints(neo4j_graph):
    # seed a tiny subgraph (a program that CONTAINS a paragraph)
    neo4j_graph.merge_entity("CBACT01C", "Program",
                             {"simple_name": "CBACT01C", "kind": "Program",
                              "file_path": "CBACT01C.cbl", "semantic_summary": "reader"},
                             repo="aws-mf-carddemo")
    neo4j_graph.merge_entity("CBACT01C.1000-MAIN", "Paragraph",
                             {"simple_name": "1000-MAIN", "kind": "Paragraph",
                              "file_path": "CBACT01C.cbl", "semantic_summary": None},
                             repo="aws-mf-carddemo")
    neo4j_graph.merge_relationship("CBACT01C", "CBACT01C.1000-MAIN", "CONTAINS",
                                   {}, allow_unresolved=False, repo="aws-mf-carddemo")

    from cobol_modernizer.api import app
    from cobol_modernizer.controlplane.deps import get_neo4j
    app.dependency_overrides[get_neo4j] = lambda: neo4j_graph
    try:
        client = TestClient(app)
        g = client.get("/api/graph?repo=aws-mf-carddemo&limit=50").json()
        ids = {n["id"] for n in g["nodes"]}
        assert "CBACT01C" in ids and "CBACT01C.1000-MAIN" in ids
        assert any(l["type"] == "CONTAINS" for l in g["links"])
        e = client.get("/api/entity/CBACT01C").json()
        assert e["entity"]["qualified_name"] == "CBACT01C"
        assert any(o["relationship"] == "CONTAINS" for o in e["outgoing"])
        assert client.get("/api/entity/NOSUCH").status_code == 404
    finally:
        app.dependency_overrides.pop(get_neo4j, None)
