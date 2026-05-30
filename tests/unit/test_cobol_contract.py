import json
from pathlib import Path
import pytest
from cobol_modernizer.contract.cobol_contract import (
    SUPPORTED_SCHEMA_VERSION, load_contract,
)

FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_sample.json"


def test_supported_version_is_2():
    assert SUPPORTED_SCHEMA_VERSION == 2


def test_loads_v2_entities_dataitems_and_edges():
    results = load_contract(json.loads(FIX.read_text()))
    assert len(results) == 1
    r = results[0]
    assert r.file_path == "app/cbl/CBACT01C.cbl"
    assert any(e.qualified_name == "CBACT01C.WS-ACCT-ID" for e in r.entities)
    reads = [rel for rel in r.relationships if rel.kind.value == "READS"]
    assert reads and reads[0].metadata["resource"] == "ACCTDAT"


def test_version_mismatch_raises():
    with pytest.raises(ValueError, match="schemaVersion"):
        load_contract({"schemaVersion": 1, "files": []})
