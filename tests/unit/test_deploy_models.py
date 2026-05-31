from cobol_modernizer.deploy.models import (
    DeploySpec, SmokeResult, PerfBaseline, RolloutPlan, RollbackEvent, FitnessReport,
)


def test_deploy_spec_roundtrip():
    spec = DeploySpec(
        workspace_id="w1",
        artifact_id="a-spring-1",
        slice_name="account-view-service",
        image_ref="account-view-service:abc123",
        image_digest="sha256:" + "0" * 64,
    )
    dumped = spec.model_dump()
    assert DeploySpec(**dumped) == spec
    # json_schema-safe: serializes with no custom types
    assert spec.model_dump_json().startswith("{")


def test_perf_baseline_ratio():
    pb = PerfBaseline(
        slice_name="account-view-service",
        cobol_p95_ms=120.0,
        canary_p95_ms=90.0,
        cobol_throughput_rps=50.0,
        canary_throughput_rps=70.0,
        fixtures=12,
    )
    # canary faster -> ratio < 1.0 is good
    assert pb.p95_ratio == 0.75
    assert pb.meets(max_p95_ratio=1.2) is True


def test_rollout_plan_weights_sum_to_100():
    plan = RolloutPlan(canary_pct=10, legacy_pct=90)
    assert plan.canary_pct + plan.legacy_pct == 100
    assert plan.is_full_legacy() is False
    assert RolloutPlan(canary_pct=0, legacy_pct=100).is_full_legacy() is True


def test_rollback_event_records_reason():
    ev = RollbackEvent(
        workspace_id="w1", slice_name="account-view-service",
        reason="equivalence_divergence", from_canary_pct=10, to_canary_pct=0,
        triggered_by="auto",
    )
    assert ev.to_canary_pct == 0
    assert ev.triggered_by in ("auto", "human")
