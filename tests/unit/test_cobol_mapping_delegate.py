import json
from pathlib import Path
import pytest
from cobol_modernizer.cobol.mapping import (
    cobol_json_to_parse_results, SUPPORTED_SCHEMA_VERSION,
)

FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_sample.json"

def test_mapping_supports_v2():
    assert SUPPORTED_SCHEMA_VERSION == 2

def test_mapping_delegates_to_v2_loader():
    results = cobol_json_to_parse_results(json.loads(FIX.read_text()))
    assert len(results) == 1
    assert results[0].file_path == "app/cbl/CBACT01C.cbl"

def test_mapping_rejects_v1():
    with pytest.raises(ValueError, match="schemaVersion"):
        cobol_json_to_parse_results({"schemaVersion": 1, "files": []})
