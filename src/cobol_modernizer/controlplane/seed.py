"""Seed a demo workspace so the cockpit shows real data against a live backend.

Mirrors the cockpit's MSW fixture (web/src/test/fixtures/controlplane.ts):
a CardDemo workspace + the 11 journey stages + a BRD groundedness gate +
a workspace budget + one running BRD agent run (with a couple of events) +
a BRD artifact carrying an evidence_map.

Idempotent: if a workspace with the same repo_slug already exists, it is left
untouched. Run against a live Postgres with:

    python -m cobol_modernizer.controlplane.seed
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.events import emit_event
from cobol_modernizer.controlplane.stages import JOURNEY_STAGES
from cobol_modernizer.persistence.tables import (
    AgentRun, Artifact, Budget, Gate, JourneyStage, Workspace,
)

# Must match a directory under source_code_to_analyse/ (COBOL_SOURCE_ROOT) so the
# seeded workspace can actually Parse/Blueprint. carddemo-mini is the small,
# self-contained sample shipped for exactly this; the full aws-mf-mod-carddemo is
# heavier to parse. (Was "aws-mf-carddemo", which matched no on-disk folder.)
DEMO_REPO_SLUG = "carddemo-mini"
DEMO_NAME = "CardDemo (mini)"


def seed_demo(session: Session, *, created_by: str = "cwijay@biz2bricks.ai") -> Workspace:
    """Create the CardDemo demo workspace + journey if it does not already exist.
    Returns the workspace (existing or newly created)."""
    existing = session.execute(
        select(Workspace).where(Workspace.repo_slug == DEMO_REPO_SLUG)
    ).scalars().first()
    if existing is not None:
        return existing

    ws = Workspace(name=DEMO_NAME, repo_slug=DEMO_REPO_SLUG,
                   graph_snapshot="snap-001", created_by=created_by, status="active")
    session.add(ws); session.flush()

    stage_by_key: dict[str, JourneyStage] = {}
    for st in JOURNEY_STAGES:
        status = "passed" if st.ordinal < 5 else "running" if st.ordinal == 5 else "pending"
        row = JourneyStage(workspace_id=ws.id, stage_key=st.key, ordinal=st.ordinal,
                           status=status)
        session.add(row); stage_by_key[st.key] = row
    session.flush()

    blueprint = stage_by_key["blueprint"]
    session.add(Gate(workspace_id=ws.id, stage_id=blueprint.id,
                     gate_key="brd_groundedness", status="open",
                     threshold={"min_weighted": 4.2, "accuracy_floor": 3},
                     result={"weighted": 4.35, "accuracy": 4}))
    session.add(Budget(workspace_id=ws.id, scope="workspace", agent_run_id=None,
                       cap_usd=Decimal("50"), spent_usd=Decimal("0"), killed=False))

    run = AgentRun(workspace_id=ws.id, stage_id=blueprint.id, role="brd",
                   model="claude-sonnet-4-6", status="running", started_by=created_by,
                   input_tokens=12000, output_tokens=3400, cache_read_tokens=8000,
                   cache_creation_tokens=2000, total_cost_usd=Decimal("0.42"))
    session.add(run); session.flush()
    emit_event(session, run_id=run.id, type="plan",
               summary="drafting BRD for the account-view slice")
    emit_event(session, run_id=run.id, type="tool_call",
               summary="neighbors(CBACT01C)", detail={"name": "CBACT01C"})

    session.add(Artifact(workspace_id=ws.id, stage_id=blueprint.id, agent_run_id=run.id,
                         kind="brd", version=1,
                         object_uri="minio://artifacts/%s/brd/v1.html" % ws.id,
                         content_hash="sha256:demo",
                         evidence_map={"REQ-001": ["CBACT01C", "CBACT01C.1000-MAIN"]}))
    session.flush()
    return ws


def main() -> None:
    from cobol_modernizer.persistence.db import session_scope

    with session_scope() as session:
        ws = seed_demo(session)
        print(f"seeded demo workspace {ws.id} ({ws.repo_slug})")


if __name__ == "__main__":
    main()
