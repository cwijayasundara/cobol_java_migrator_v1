import json
from pathlib import Path
from cobol_modernizer.deploy.fitness import run_fitness, load_targets
from cobol_modernizer.deploy.models import FitnessReport

FIX = Path(__file__).parents[1] / "fixtures" / "fitness_targets.json"


def test_all_pass():
    targets = load_targets(json.loads(FIX.read_text()))
    report = run_fitness(
        workspace_id="w1", commit_sha="abc",
        measured={
            "equivalence_divergence_rate": 0.0,
            "canary_p95_ratio": 0.75,
            "slice_test_coverage": 0.9,
            "seams_migrated": 1,
            "identity_drift_writers": 0.0,
        },
        targets=targets,
    )
    assert isinstance(report, FitnessReport)
    assert report.passed is True
    assert len(report.checks) == 5


def test_divergence_fails():
    targets = load_targets(json.loads(FIX.read_text()))
    report = run_fitness(
        workspace_id="w1", commit_sha="abc",
        measured={
            "equivalence_divergence_rate": 0.01,   # any divergence fails
            "canary_p95_ratio": 0.9,
            "slice_test_coverage": 0.9,
            "seams_migrated": 1,
            "identity_drift_writers": 0.0,
        },
        targets=targets,
    )
    assert report.passed is False
    bad = [c.key for c in report.checks if not c.passed]
    assert bad == ["equivalence_divergence_rate"]


def test_regression_detection_against_prior():
    targets = load_targets(json.loads(FIX.read_text()))
    good = {"equivalence_divergence_rate": 0.0, "canary_p95_ratio": 0.9,
            "slice_test_coverage": 0.9, "seams_migrated": 1, "identity_drift_writers": 0.0}
    prior = run_fitness(workspace_id="w1", commit_sha="p", measured=good, targets=targets)
    worse = dict(good, canary_p95_ratio=2.0)
    now = run_fitness(workspace_id="w1", commit_sha="n", measured=worse, targets=targets)
    assert now.regressions(prior) == ["canary_p95_ratio"]
