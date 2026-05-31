import json
from pathlib import Path

from fastapi.testclient import TestClient

from cobol_modernizer.api import app, register_equivalence_slice
from cobol_modernizer.equivalence.tolerance import load_ruleset
from cobol_modernizer.equivalence.seam_link import SeamRef

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence"


def _resolver(program, field):
    if field == "ACCT-CURR-BAL":
        return SeamRef("CBACT01C.1300-POPUL-ACCT-RECORD", "MOVES_TO",
                       "app/cbl/CBACT01C.cbl", 218)
    return SeamRef(program, unresolved=True)


def _register_account_view():
    # Deviation from plan: the workload-specific golden/ruleset/resolver are
    # registered by the test (not baked into src), keeping the control plane a
    # generic converter per the binding generic-converter constraint.
    golden = json.loads((FIX / "golden_cbact01c_out.json").read_text())
    register_equivalence_slice(
        "account-view", workspace_id="w1",
        golden_records=golden["records"], record="ACCOUNT-RECORD",
        ruleset=load_ruleset((FIX / "tolerance_acct.yaml").read_text()),
        resolve_seam=_resolver, dialect="cobc 3.2 (ibm-strict, ASCII)",
    )


def test_run_equivalence_endpoint_fails_on_precision_defect():
    _register_account_view()
    client = TestClient(app)
    payload = {
        "workspace_id": "w1", "slice_name": "account-view",
        "program": "CBACT01C", "record_key": "ACCT-ID",
        "candidate_records": [
            {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
             "ACCT-CURR-BAL": "1234.5", "ACCT-CREDIT-LIMIT": "5000.00",
             "ACCT-OPEN-DATE": "2014-11-20", "FILLER": "p"}
        ],
        "online_uses_recorded_fixtures": False,
    }
    resp = client.post("/api/equivalence/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "fail"
    assert body["defects"][0]["source_seam"] == "CBACT01C.1300-POPUL-ACCT-RECORD"
    assert body["defects"][0]["field"] == "ACCT-CURR-BAL"
