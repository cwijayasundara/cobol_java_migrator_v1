from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import (
    Base, Workspace, Deployment, CanaryRoute, FitnessCheck,
)


def test_deploy_route_fitness_roundtrip():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                       created_by="cwijay@biz2bricks.ai")
        s.add(ws); s.flush()
        d = Deployment(workspace_id=ws.id, artifact_id=None,
                       slice_name="account-view-service",
                       image_ref="account-view-service:abc123",
                       image_digest="sha256:" + "0" * 64,
                       created_by="cwijay@biz2bricks.ai")
        s.add(d); s.flush()
        # stoppable-safe default: a new route starts full-legacy
        r = CanaryRoute(workspace_id=ws.id, slice_name="account-view-service",
                        deployment_id=d.id, canary_pct=0, legacy_pct=100, active=True)
        s.add(r); s.flush()
        fc = FitnessCheck(workspace_id=ws.id, commit_sha="deadbeef",
                          report={"checks": []}, passed=True)
        s.add(fc); s.commit()
        assert r.canary_pct == 0 and r.legacy_pct == 100
        assert d.status == "built"
        assert fc.passed is True
