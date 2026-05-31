import json
import pytest
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent import graph_tools as gt
from cobol_modernizer.agent import graph_ops as ops


class FakeClient:
    def __init__(self, rows_by_key): self.rows_by_key = rows_by_key
    def run(self, query, **params):
        for key, rows in self.rows_by_key.items():
            if key in query:
                return rows
        return []


def test_seam_candidates_tool_is_registered_and_readonly():
    assert "mcp__graph__seam_candidates" in gt.GRAPH_TOOL_NAMES
    assert "mcp__graph__reader_writer_classification" in gt.GRAPH_TOOL_NAMES
    assert "mcp__graph__data_accesses" in gt.GRAPH_TOOL_NAMES


def test_neighbors_edge_enum_extended_for_v2():
    # v2 IO/control-flow edges are traversable by the read-only neighbors tool.
    for e in ("READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"):
        assert e in ops._EDGES


def test_data_accesses_op_returns_normalized_rows():
    client = FakeClient({"accesses_for_program": [
        {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
    ]})
    deps = GraphDeps(client=client, repo_id="cardemo", repo_path=None)
    out = ops.data_accesses(deps, "COACTVWC")
    assert out["accesses"][0]["resource"] == "ACCTFILE"
    assert out["accesses"][0]["intent"] == "read"


def test_no_seam_op_emits_write_cypher():
    import inspect, cobol_modernizer.seam.signals as sg
    import cobol_modernizer.seam.reader_writer as rw
    import cobol_modernizer.seam.service as svc
    src = inspect.getsource(sg) + inspect.getsource(rw) + inspect.getsource(svc)
    for kw in ("CREATE ", "MERGE ", "DELETE ", "SET ", "REMOVE "):
        # CREATE/MERGE only appear in the test fixture, never in seam Cypher.
        assert kw not in src, f"seam Cypher must be read-only; found {kw!r}"
