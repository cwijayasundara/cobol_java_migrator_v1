import json
from pathlib import Path
from cobol_modernizer.deploy.perf_baseline import run_perf_baseline, load_fixtures

FIX = Path(__file__).parents[1] / "fixtures"


def test_perf_baseline_against_cobol_golden():
    fixtures = load_fixtures(str(FIX / "canary_fixtures.jsonl"))
    golden = json.loads((FIX / "perf_golden_baseline.json").read_text())

    # fake canary: returns the expected body in ~10ms (faster than COBOL)
    def fake_invoke(request: dict) -> tuple[dict, float]:
        acct = request["acctId"]
        body = {"ACCT-00000000001": {"acctId": acct, "balance": "1000.00"},
                "ACCT-00000000002": {"acctId": acct, "balance": "250.50"},
                "ACCT-00000000003": {"acctId": acct, "balance": "0.00"}}
        return body[f"ACCT-{acct}"], 10.0

    pb, divergences = run_perf_baseline(
        slice_name="account-view-service", fixtures=fixtures,
        invoke=fake_invoke, cobol_baseline=golden,
    )
    assert pb.fixtures == 3
    assert pb.canary_p95_ms < pb.cobol_p95_ms     # canary faster
    assert pb.meets(max_p95_ratio=1.2) is True
    assert divergences == 0                        # outputs match golden (equivalence)


def test_perf_baseline_flags_divergence():
    fixtures = load_fixtures(str(FIX / "canary_fixtures.jsonl"))
    golden = json.loads((FIX / "perf_golden_baseline.json").read_text())

    def bad_invoke(request: dict) -> tuple[dict, float]:
        return {"acctId": request["acctId"], "balance": "999.99"}, 10.0  # wrong

    _, divergences = run_perf_baseline(
        slice_name="account-view-service", fixtures=fixtures,
        invoke=bad_invoke, cobol_baseline=golden,
    )
    assert divergences == 3
