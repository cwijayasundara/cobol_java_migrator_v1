from cobol_modernizer.deploy.canary import CanaryOrchestrator, CanaryDeps
from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline
from cobol_modernizer.cost.policy import CostPolicy, CostLedger


def _deps():
    led = CostLedger()
    led.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
    led.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
    rc = RoutingController(slice_name="account-view-service")
    guard = RollbackGuard(rc, workspace_id="w1", slice_name="account-view-service",
                          max_error_rate=0.01, max_divergence_rate=0.0)
    return CanaryDeps(
        routing=rc, guard=guard, cost=CostPolicy(led),
        smoke=lambda: SmokeResult(slice_name="account-view-service", health_ok=True,
                                  endpoints_ok=2, endpoints_total=2),
        perf=lambda: (PerfBaseline(slice_name="account-view-service", cobol_p95_ms=120.0,
                                   canary_p95_ms=90.0, cobol_throughput_rps=50.0,
                                   canary_throughput_rps=70.0, fixtures=3), 0),
    )


def test_happy_path_promotes():
    deps = _deps()
    orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1",
                              slice_name="account-view-service")
    result = orch.run(
        deploy_gate_passed=True, canary_pct=10, max_p95_ratio=1.2,
        health=CanaryHealth(requests=1000, errors=1, divergences=0),
    )
    assert result.status == "promoted"
    assert deps.routing.canary_pct == 10
    assert deps.routing.route("ACCT-00000000001") in (RouteTarget.LEGACY, RouteTarget.CANARY)


def test_smoke_failure_blocks_flip():
    deps = _deps()
    deps.smoke = lambda: SmokeResult(slice_name="s", health_ok=False,
                                     endpoints_ok=0, endpoints_total=2)
    orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
    result = orch.run(deploy_gate_passed=True, canary_pct=10, max_p95_ratio=1.2,
                      health=CanaryHealth(requests=0, errors=0, divergences=0))
    assert result.status == "rolled_back"
    assert deps.routing.canary_pct == 0     # never flipped


def test_gate_not_passed_refuses_to_flip():
    deps = _deps()
    orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
    result = orch.run(deploy_gate_passed=False, canary_pct=10, max_p95_ratio=1.2,
                      health=CanaryHealth(requests=1000, errors=0, divergences=0))
    assert result.status == "blocked_no_gate"
    assert deps.routing.canary_pct == 0
