import json
from pathlib import Path

from cobol_modernizer.slice.selection import pick_slice
from cobol_modernizer.slice.design import choose_transition_pattern
from cobol_modernizer.darklaunch.runner import run_dark_launch
from cobol_modernizer.cost.policy import CostPolicy, CostLedger

FIX = Path(__file__).parents[1] / "fixtures"


def test_thin_slice_pipeline_parity_under_cap():
    # 1) seam ranking -> reader-only slice
    cands = json.loads((FIX / "seam_candidates_sample.json").read_text())
    choice = pick_slice(cands)
    assert choice.program == "COACTVWC"
    # 2) design decision is CDC + ACL, no identity drift
    design = choose_transition_pattern(reader_only=choice.reader_only,
                                       writes=choice.evidence["writes"])
    assert design.production_pattern == "CDC/replica"
    # 3) dark launch diff-matches within tolerance
    inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
    golden = json.loads((FIX / "coactvwc_golden.json").read_text())

    class Svc:
        def get_account_view(self, a): return golden.get(a)
    summary = run_dark_launch(inputs, golden, Svc())
    assert summary.passed is True
    # 4) cost stayed under cap
    ledger = CostLedger()
    ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
    ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
    policy = CostPolicy(ledger)
    policy.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=2.3)
    policy.check(workspace_id="w1", run_id="r1")  # no raise
    assert policy.remaining_usd(workspace_id="w1") == 47.7
