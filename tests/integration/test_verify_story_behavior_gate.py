from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.controlplane.verify import evaluate_story_behavior
from cobol_modernizer.persistence.tables import Base, JourneyStage, Workspace


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Workspace(id="ws-1", name="m", repo_slug="r", created_by="t"))
    s.add(JourneyStage(workspace_id="ws-1", stage_key="verify", ordinal=12, status="running"))
    s.commit()
    return s


def test_gate_passes_when_all_stories_have_tests_and_equivalence():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "passed"


def test_gate_blocks_when_equivalence_failed():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="fail")
    s.flush()
    assert gate.status == "open"
    assert "US-1" in str(gate.result)


def test_gate_blocks_when_acceptance_test_missing():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=[], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "open"
