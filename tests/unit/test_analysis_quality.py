from cobol_modernizer.planner.dependency import derive_dependencies, stories_from_seam_set
from cobol_modernizer.planner.dag import delivery_waves, topo_order
from cobol_modernizer.planner.quality import assess_plan_quality
from cobol_modernizer.seam.quality import assess_seam_quality


def test_seam_quality_passes_grounded_ranked_candidates():
    cands = [{
        "program": "P1", "seam_type": "db_reader",
        "score": {"weighted": 0.9},
        "evidence_map": {"business": ["P1"]},
        "identity_drift_writer": False,
    }]
    passed, result, threshold = assess_seam_quality(cands, known_refs={"P1"})

    assert passed
    assert result["candidate_count"] == 1
    assert result["missing_evidence_programs"] == []
    assert threshold["require_evidence"] is True


def test_seam_quality_reports_missing_evidence_and_unknown_refs():
    cands = [
        {"program": "P1", "seam_type": "db_reader", "score": {"weighted": 0.9},
         "evidence_map": {}, "identity_drift_writer": False},
        {"program": "P2", "seam_type": "db_writer", "score": {"weighted": 0.4},
         "evidence_map": {"risk": ["GHOST"]}, "identity_drift_writer": True},
    ]
    passed, result, _ = assess_seam_quality(cands, known_refs={"P1", "P2"})

    assert not passed
    assert result["missing_evidence_programs"] == ["P1"]
    assert result["unknown_evidence_refs"] == ["GHOST"]


def test_plan_quality_passes_acyclic_grounded_story_dag():
    cands = [
        {"program": "Reader", "reads": ["A"], "writes": [],
         "score": {"weighted": 0.9}},
        {"program": "Writer", "reads": [], "writes": ["A"],
         "score": {"weighted": 0.4}},
    ]
    stories = stories_from_seam_set(cands, repo_id="repo")
    dag = derive_dependencies(stories, cands, repo_id="repo")
    order = topo_order(dag)
    waves = delivery_waves(dag)

    passed, result, threshold = assess_plan_quality(
        dag, seam_candidates=cands, acyclic=True,
        topo_order=order, delivery_waves=waves)

    assert passed
    assert result["story_count"] == 2
    assert result["stories_with_unknown_seam"] == []
    assert threshold["require_acyclic"] is True


def test_plan_quality_reports_unknown_seams_and_missing_evidence():
    cands = [{"program": "Known", "reads": [], "writes": [],
              "score": {"weighted": 0.9}}]
    stories = stories_from_seam_set(cands, repo_id="repo")
    stories[0].seam = "Ghost"
    stories[0].evidence_map = {}
    dag = derive_dependencies(stories, [{"program": "Ghost", "reads": [], "writes": [],
                                        "score": {"weighted": 0.9}}],
                              repo_id="repo")

    passed, result, _ = assess_plan_quality(
        dag, seam_candidates=cands, acyclic=True,
        topo_order=[stories[0].id], delivery_waves=[[stories[0].id]])

    assert not passed
    assert result["stories_with_unknown_seam"] == [stories[0].id]
    assert result["stories_without_evidence"] == [stories[0].id]
