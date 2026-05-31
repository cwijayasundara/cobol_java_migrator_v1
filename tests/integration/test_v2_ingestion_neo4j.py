"""Task 9 (exit-criteria gate): run the built extractor JAR over real COBOL
fixtures -> v2 contract -> repo-scoped ingest -> reader/writer + seam ranking in
Cypher. Proves the whole Python pipeline end-to-end on a live Neo4j.

Note: the CICS DATASET operand in cicsview.cbl is a *program variable*
(LIT-ACCTFILENAME), so CICS edges target that token (constant-resolution is a
later enrichment, per the Phase-1 design note) — assertions reflect that reality.
Needs Docker + the built JAR.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from cobol_modernizer.contract.cobol_contract import load_contract, SUPPORTED_SCHEMA_VERSION
from cobol_modernizer.ingestion import ingest_parse_results
from cobol_modernizer.queries import CodeGraphQueries

ROOT = Path(__file__).parents[2]
SRC = ROOT / "tests" / "fixtures" / "cobol"
JAR = ROOT / "tools" / "cobol-extractor" / "target" / "cobol-extractor.jar"
REPO = "carddemo-e2e"


def _java_bin() -> str:
    jh = os.getenv("JAVA_HOME")
    return str(Path(jh) / "bin" / "java") if jh else "java"


@pytest.mark.skipif(not JAR.exists(), reason="extractor JAR not built; run mvn package")
def test_extractor_emits_v2_and_graph_classifies_reader_writer(neo4j_graph):
    out = subprocess.run(
        [_java_bin(), "-jar", str(JAR), "--source-dir", str(SRC), "--format", "FIXED"],
        capture_output=True, text=True, check=True)
    payload = json.loads(out.stdout)
    assert payload["schemaVersion"] == SUPPORTED_SCHEMA_VERSION == 2
    assert any(f["dataItems"] for f in payload["files"])      # DataItem nodes emitted

    results = load_contract(payload)
    ingest_parse_results(neo4j_graph, results, repo=REPO)
    q = CodeGraphQueries(neo4j_graph)

    # ACCTDAT (VSAM) is read by the two batch readers, written by neither.
    acct = q.reader_writer_classification("ACCTDAT", repo=REPO)
    assert {"ACCTREAD", "ACCTVIEW"} <= {r["program"] for r in acct["readers"]}
    assert acct["writers"] == []

    # CICS I/O is represented as EXECUTES_CICS with both read and write intent.
    cics = {(a["kind"], a["intent"]) for a in q.data_accesses("CICSVIEW", repo=REPO)}
    assert ("EXECUTES_CICS", "read") in cics
    assert ("EXECUTES_CICS", "write") in cics

    # EXEC SQL intent: SELECT(read) + UPDATE(write) on the DB2 table.
    sql = q.data_accesses("SQLUPD", repo=REPO)
    assert any(a["kind"] == "EXECUTES_SQL" and a["intent"] == "write"
               and a["resource"] == "CARDDEMO.TRANSACTION_TYPE" for a in sql)

    # Pure-Cypher seam ranking: the reader-only program outranks the writers.
    ranked = q.seam_candidates(repo=REPO, limit=10)
    names = [r["program"] for r in ranked]
    assert any(r["reader_only"] for r in ranked)
    acctview = next(r for r in ranked if r["program"] == "ACCTVIEW")
    assert acctview["reader_only"] is True
    assert names.index("ACCTVIEW") < names.index("CICSVIEW")
