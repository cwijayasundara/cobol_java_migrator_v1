from pathlib import Path
ROOT = Path(__file__).parents[2]


def test_ci_runs_core_tests_and_stoppable_check():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "uv run pytest" in ci
    assert "test_stoppable" in ci          # stoppable-safe invariant enforced per commit
    assert "test_fitness" in ci


def test_canary_workflow_is_gated_by_environment():
    cw = (ROOT / ".github/workflows/canary.yml").read_text()
    assert "environment:" in cw            # GitHub environment protection == deploy gate
    assert "deploy" in cw
    assert "smoke" in cw and "perf" in cw


def test_canary_compose_has_router_legacy_canary():
    cc = (ROOT / "infra/deploy/canary-compose.yml").read_text()
    assert "router:" in cc and "legacy:" in cc and "canary:" in cc
