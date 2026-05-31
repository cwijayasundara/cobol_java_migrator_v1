"""Task 8: v2 read-only MCP graph ops. Verifies the three seam-discovery ops are
registered as FQNs, return aggregated (not field-level) rows, and that the
neighbors edge whitelist accepts v2 edges but still rejects unknown/write edges.
Needs Docker."""
import json
from pathlib import Path

import pytest

from cobol_modernizer.contract.cobol_contract import load_contract
from cobol_modernizer.ingestion import ingest_parse_results
from cobol_modernizer.agent import graph_ops as ops
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, SERVER_NAME

FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_carddemo_slice.json"
REPO = "carddemo-slice"


@pytest.fixture
def deps(neo4j_graph):
    results = load_contract(json.loads(FIX.read_text()))
    ingest_parse_results(neo4j_graph, results, repo=REPO)
    return GraphDeps(client=neo4j_graph, repo_id=REPO, repo_path=Path("."))


def test_v2_tool_fqns_registered():
    for t in ("data_accesses", "reader_writer_classification", "seam_candidates"):
        assert f"mcp__{SERVER_NAME}__{t}" in GRAPH_TOOL_NAMES


def test_data_accesses_returns_intents(deps):
    acc = ops.data_accesses(deps, "COACTVWC")
    kinds = {a["kind"] for a in acc["accesses"]}
    assert "EXECUTES_CICS" in kinds
    assert all(a["intent"] in ("read", "write") for a in acc["accesses"])


def test_reader_writer_and_seam_candidates(deps):
    cls = ops.reader_writer_classification(deps, "ACCTDAT")
    assert {r["program"] for r in cls["readers"]} == {"CBACT01C", "COACTVWC"}
    assert cls["writers"] == []
    seams = ops.seam_candidates(deps, limit=5)
    names = [s["program"] for s in seams["seam_candidates"]]
    assert names.index("CBACT01C") < names.index("COBIL00C")


def test_neighbors_accepts_v2_edge_rejects_unknown(deps):
    ok = ops.neighbors(deps, "CBACT01C", edge="READS", direction="out")
    assert "neighbors" in ok
    bad = ops.neighbors(deps, "CBACT01C", edge="DROP", direction="out")
    assert "error" in bad
