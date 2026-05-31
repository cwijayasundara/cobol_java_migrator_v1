from cobol_modernizer.deploy.canary import CanaryOrchestrator, CanaryDeps
from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline
from cobol_modernizer.cost.policy import CostPolicy, CostLedger


def test_injected_divergence_rolls_back_and_is_proven():
    led = CostLedger()
    led.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
    led.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
    rc = RoutingController(slice_name="s")
    guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                          max_error_rate=0.01, max_divergence_rate=0.0)
    deps = CanaryDeps(
        routing=rc, guard=guard, cost=CostPolicy(led),
        smoke=lambda: SmokeResult(slice_name="s", health_ok=True,
                                  endpoints_ok=2, endpoints_total=2),
        perf=lambda: (PerfBaseline(slice_name="s", cobol_p95_ms=120.0,
                                   canary_p95_ms=90.0, cobol_throughput_rps=50.0,
                                   canary_throughput_rps=70.0, fixtures=3), 0),
    )
    orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
    # flip succeeds, but observed traffic diverges from the COBOL golden master
    result = orch.run(
        deploy_gate_passed=True, canary_pct=25, max_p95_ratio=1.2,
        health=CanaryHealth(requests=1000, errors=0, divergences=3),
    )
    assert result.status == "rolled_back"
    assert result.rollback_event is not None
    assert result.rollback_event.reason == "equivalence_divergence"
    # ROLLBACK PROVEN: route is back to 100% legacy
    assert rc.canary_pct == 0
    assert rc.route("ACCT-00000000001") is RouteTarget.LEGACY
