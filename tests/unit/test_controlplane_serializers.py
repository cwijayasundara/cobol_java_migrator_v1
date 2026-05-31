from datetime import datetime, timezone
from decimal import Decimal
from cobol_modernizer.persistence.tables import (
    Workspace, JourneyStage, AgentRun, Artifact, Gate, Approval, Budget,
)
from cobol_modernizer.controlplane.serializers import (
    workspace_dto, stage_dto, run_dto, artifact_dto, gate_dto, approval_dto, budget_dto,
)

TS = datetime(2026, 5, 30, tzinfo=timezone.utc)


def test_workspace_dto_shape():
    ws = Workspace(id="ws-1", name="CardDemo", repo_slug="aws-mf-carddemo",
                   graph_snapshot="snap-001", created_by="cwijay@biz2bricks.ai",
                   created_at=TS, status="active")
    d = workspace_dto(ws)
    assert d == {
        "id": "ws-1", "name": "CardDemo", "repo_slug": "aws-mf-carddemo",
        "graph_snapshot": "snap-001", "created_by": "cwijay@biz2bricks.ai",
        "created_at": "2026-05-30T00:00:00+00:00", "status": "active",
    }


def test_budget_dto_numeric_to_float():
    b = Budget(id="bud-1", workspace_id="ws-1", scope="workspace", agent_run_id=None,
               cap_usd=Decimal("50"), spent_usd=Decimal("18.42"), killed=False,
               updated_at=TS)
    d = budget_dto(b)
    assert d["cap_usd"] == 50.0 and d["spent_usd"] == 18.42 and d["killed"] is False
    assert isinstance(d["cap_usd"], float)


def test_run_dto_tokens_and_cost():
    r = AgentRun(id="run-1", workspace_id="ws-1", stage_id="stg-blueprint", role="brd",
                 model="claude-sonnet-4-6", status="running", started_by="x",
                 started_at=TS, finished_at=None, input_tokens=12000, output_tokens=3400,
                 cache_read_tokens=8000, cache_creation_tokens=2000,
                 total_cost_usd=Decimal("0.42"), error=None)
    d = run_dto(r)
    assert d["input_tokens"] == 12000 and d["total_cost_usd"] == 0.42
    assert d["finished_at"] is None and d["status"] == "running"


def test_artifact_gate_approval_stage_dtos():
    art = Artifact(id="art-1", workspace_id="ws-1", stage_id="stg-blueprint",
                   agent_run_id="run-1", kind="brd", version=1,
                   object_uri="minio://a", content_hash="sha256:abc",
                   evidence_map={"REQ-001": ["CBACT01C"]}, created_at=TS)
    assert artifact_dto(art)["evidence_map"] == {"REQ-001": ["CBACT01C"]}
    g = Gate(id="gate-brd", workspace_id="ws-1", stage_id="stg-blueprint",
             gate_key="brd_groundedness", status="open",
             threshold={"min_weighted": 4.2}, result={"weighted": 4.35}, updated_at=TS)
    assert gate_dto(g)["gate_key"] == "brd_groundedness" and gate_dto(g)["status"] == "open"
    ap = Approval(id="ap-1", gate_id="gate-brd", decision="approved",
                  approver_email="lead@biz2bricks.ai", approver_role="lead_engineer",
                  risk_accepted=False, rationale="ok", decided_at=TS)
    assert approval_dto(ap)["approver_email"] == "lead@biz2bricks.ai"
    st = JourneyStage(id="stg-blueprint", workspace_id="ws-1", stage_key="blueprint",
                      ordinal=5, status="running", updated_at=TS)
    assert stage_dto(st) == {"id": "stg-blueprint", "workspace_id": "ws-1",
                             "stage_key": "blueprint", "ordinal": 5,
                             "status": "running", "updated_at": "2026-05-30T00:00:00+00:00"}
