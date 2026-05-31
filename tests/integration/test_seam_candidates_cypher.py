"""Task 6: reader/writer classification + seam-candidate ranking, computed
entirely in Cypher (ZERO LLM). Loads the deterministic v2 CardDemo slice into a
real Neo4j and asserts the in-DB seam math. Needs Docker."""
import json
from pathlib import Path

import pytest

from cobol_modernizer.contract.cobol_contract import load_contract
from cobol_modernizer.ingestion import ingest_parse_results
from cobol_modernizer.queries import CodeGraphQueries

FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_carddemo_slice.json"
REPO = "carddemo-slice"


@pytest.fixture
def loaded(neo4j_graph):
    results = load_contract(json.loads(FIX.read_text()))
    ingest_parse_results(neo4j_graph, results, repo=REPO)
    return neo4j_graph


def test_reader_writer_classification_acctdat(loaded):
    q = CodeGraphQueries(loaded)
    cls = q.reader_writer_classification("ACCTDAT", repo=REPO)
    readers = {r["program"] for r in cls["readers"]}
    writers = {r["program"] for r in cls["writers"]}
    assert "CBACT01C" in readers and "COACTVWC" in readers
    assert writers == set()                       # ACCTDAT is reader-only in this slice


def test_transact_has_writers(loaded):
    q = CodeGraphQueries(loaded)
    cls = q.reader_writer_classification("TRANSACT", repo=REPO)
    writers = {r["program"] for r in cls["writers"]}
    assert {"CBTRN02C", "COBIL00C"} <= writers


def test_seam_candidates_ranks_reader_only_first_no_llm(loaded):
    q = CodeGraphQueries(loaded)
    ranked = q.seam_candidates(repo=REPO, limit=10)
    names = [r["program"] for r in ranked]
    # reader-only programs rank above writers
    assert names.index("CBACT01C") < names.index("CBTRN02C")
    assert all("reader_only" in r and "fan_in" in r and "score" in r for r in ranked)
    # side-effect detection: TRANSACT writer flagged as not reader-only
    cobil = next(r for r in ranked if r["program"] == "COBIL00C")
    assert cobil["reader_only"] is False
