import json
from pathlib import Path
import pytest
from cobol_modernizer.contract.cobol_contract import load_contract
from cobol_modernizer.benchmark.carddemo_baseline import run_baseline

FIX = Path(__file__).parents[1] / "fixtures" / "carddemo_extract_v2.json"


def test_canned_extract_reports_depth_and_errors(carddemo_root):
    payload = json.loads(FIX.read_text())
    report = run_baseline(carddemo_root, parse_fn=lambda root: load_contract(payload))
    assert report.programs + report.copybooks == report.files_discovered
    assert report.parse_errors >= 1            # the BADFILE entry
    assert report.max_copybook_depth >= 2      # nested copybook chain
    assert report.parse_seconds >= 0.0
