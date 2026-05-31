import json
from pathlib import Path
from cobol_modernizer.equivalence.tolerance import load_ruleset
from cobol_modernizer.equivalence.differ import diff_records, DiffReport

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence"


def _load(name):
    return json.loads((FIX / name).read_text())


def _ruleset():
    return load_ruleset((FIX / "tolerance_acct.yaml").read_text())


def test_matching_candidate_is_clean():
    report = diff_records(
        golden=_load("golden_cbact01c_out.json")["records"],
        candidate=_load("candidate_ok.json")["records"],
        ruleset=_ruleset(), key="ACCT-ID",
    )
    assert isinstance(report, DiffReport)
    assert report.passed
    assert report.mismatches == []


def test_injected_precision_defect_is_caught():
    report = diff_records(
        golden=_load("golden_cbact01c_out.json")["records"],
        candidate=_load("candidate_precision_defect.json")["records"],
        ruleset=_ruleset(), key="ACCT-ID",
    )
    assert not report.passed
    assert len(report.mismatches) == 1
    mm = report.mismatches[0]
    assert mm.record_key == "00000000001"
    assert mm.field == "ACCT-CURR-BAL"
    assert "1234.56" in mm.reason and "1234.50" in mm.reason


def test_missing_record_is_a_mismatch():
    # Deviation from plan: the plan fed golden[:2] (zoned-format) as the
    # candidate, but the matcher's candidate side expects a plain decimal
    # string, so Decimal("00000012345F") would raise. Use the proper
    # candidate-format records (decimal) minus the third record instead.
    golden = _load("golden_cbact01c_out.json")["records"]
    candidate = _load("candidate_ok.json")["records"][:2]
    report = diff_records(golden=golden, candidate=candidate,
                          ruleset=_ruleset(), key="ACCT-ID")
    assert not report.passed
    assert any(m.field == "<record>" and m.record_key == "00000000003"
               for m in report.mismatches)
