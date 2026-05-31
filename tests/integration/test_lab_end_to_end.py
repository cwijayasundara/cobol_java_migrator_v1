import json
from pathlib import Path
from cobol_modernizer.equivalence.tolerance import load_ruleset
from cobol_modernizer.equivalence.seam_link import SeamRef
from cobol_modernizer.equivalence.golden import InMemoryGoldenStore
from cobol_modernizer.equivalence.lab import EquivalenceLab

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence"


def _resolver(program, field):
    if field == "ACCT-CURR-BAL":
        return SeamRef("CBACT01C.1300-POPUL-ACCT-RECORD", "MOVES_TO",
                       "app/cbl/CBACT01C.cbl", 218)
    return SeamRef(program, unresolved=True)


def _lab():
    store = InMemoryGoldenStore()
    golden = json.loads((FIX / "golden_cbact01c_out.json").read_text())
    store.put(workspace_id="w1", slice_name="account-view",
              record="ACCOUNT-RECORD", records=golden["records"])
    return EquivalenceLab(
        golden_store=store,
        ruleset=load_ruleset((FIX / "tolerance_acct.yaml").read_text()),
        resolve_seam=_resolver,
        dialect="cobc 3.2 (ibm-strict, ASCII)",
    )


def test_phase2_slice_verifies_clean():
    lab = _lab()
    candidate = json.loads((FIX / "candidate_ok.json").read_text())["records"]
    result = lab.run_equivalence(
        workspace_id="w1", slice_name="account-view", program="CBACT01C",
        candidate_records=candidate, record_key="ACCT-ID",
        online_uses_recorded_fixtures=False,
    )
    assert result.report.verdict == "pass"
    assert result.defects == []


def test_injected_precision_defect_yields_seam_linked_ticket():
    lab = _lab()
    candidate = json.loads(
        (FIX / "candidate_precision_defect.json").read_text())["records"]
    result = lab.run_equivalence(
        workspace_id="w1", slice_name="account-view", program="CBACT01C",
        candidate_records=candidate, record_key="ACCT-ID",
        online_uses_recorded_fixtures=False,
    )
    assert result.report.verdict == "fail"
    assert len(result.defects) == 1
    d = result.defects[0]
    assert d.field == "ACCT-CURR-BAL"
    assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
    assert d.seam_edge_kind == "MOVES_TO"
    assert d.source_line == 218
    assert d.severity == "high"
    assert "1234.56" in d.reason and "1234.50" in d.reason


def test_golden_round_trips_through_store():
    store = InMemoryGoldenStore()
    recs = [{"ACCT-ID": "1", "ACCT-CURR-BAL": "0000000100{"}]
    uri = store.put(workspace_id="w1", slice_name="s", record="R", records=recs)
    assert store.get(uri)["records"] == recs
