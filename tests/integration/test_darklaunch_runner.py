import json
from pathlib import Path

from cobol_modernizer.darklaunch.runner import run_dark_launch, DarkLaunchSummary

FIX = Path(__file__).parents[1] / "fixtures"


class FakeService:
    """Stand-in for the Spring Boot service: returns golden (match scenario) or a
    perturbed value (mismatch scenario)."""
    def __init__(self, responses): self.responses = responses
    def get_account_view(self, acct_id): return self.responses.get(acct_id)


def test_all_match_passes():
    inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
    golden = json.loads((FIX / "coactvwc_golden.json").read_text())
    svc = FakeService(golden)  # perfect parity
    summary = run_dark_launch(inputs, golden, svc)
    assert isinstance(summary, DarkLaunchSummary)
    assert summary.total == 2
    assert summary.matched == 2
    assert summary.passed is True


def test_one_mismatch_fails_and_reports_field():
    inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
    golden = json.loads((FIX / "coactvwc_golden.json").read_text())
    perturbed = {k: dict(v) for k, v in golden.items()}
    perturbed["00000000123"]["currentBalance"] = "9999.99"   # injected defect
    svc = FakeService(perturbed)
    summary = run_dark_launch(inputs, golden, svc)
    assert summary.matched == 1
    assert summary.passed is False
    bad = [r for r in summary.reports if r["acct_id"] == "00000000123"][0]
    assert any(m["field"] == "currentBalance" for m in bad["mismatches"])
