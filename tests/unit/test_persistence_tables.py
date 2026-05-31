from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import Base, Workspace, Gate, Approval


def test_workspace_and_approval_roundtrip():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ws = Workspace(name="sample", repo_slug="sample-cobol",
                       created_by="cwijay@biz2bricks.ai")
        s.add(ws); s.flush()
        g = Gate(workspace_id=ws.id, stage_id=None, gate_key="brd_groundedness",
                 threshold={"min_weighted": 4.2, "accuracy_floor": 3})
        s.add(g); s.flush()
        ap = Approval(gate_id=g.id, decision="waived_with_risk",
                      approver_email="lead@biz2bricks.ai", approver_role="lead_engineer",
                      risk_accepted=True, rationale="known dead path")
        s.add(ap); s.commit()
        assert ap.approver_email == "lead@biz2bricks.ai"
        assert g.threshold["accuracy_floor"] == 3
