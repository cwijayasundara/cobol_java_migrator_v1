"""PgRepo — the only writer of run/audit/budget rows. Neo4j stays code-graph
only; ALL cost/RBAC/run state lives here (foundation §1 strict storage split)."""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import (
    Workspace, AgentRun, Budget,
)

class PgRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create_workspace(self, *, name: str, repo_slug: str, created_by: str) -> Workspace:
        ws = Workspace(name=name, repo_slug=repo_slug, created_by=created_by)
        self.s.add(ws); self.s.flush()
        return ws

    def start_run(self, *, workspace_id, stage_id, role: str, model: str,
                  started_by: str) -> AgentRun:
        run = AgentRun(workspace_id=workspace_id, stage_id=stage_id, role=role,
                       model=model, started_by=started_by, status="running")
        self.s.add(run); self.s.flush()
        return run

    def set_budget(self, *, workspace_id, scope: str, cap_usd: float,
                   agent_run_id=None) -> Budget:
        b = Budget(workspace_id=workspace_id, scope=scope,
                   agent_run_id=agent_run_id, cap_usd=Decimal(str(cap_usd)))
        self.s.add(b); self.s.flush()
        return b

    def _budget(self, *, workspace_id, scope, agent_run_id=None) -> Budget:
        stmt = select(Budget).where(Budget.workspace_id == workspace_id,
                                    Budget.scope == scope)
        if scope == "run":
            stmt = stmt.where(Budget.agent_run_id == agent_run_id)
        return self.s.scalars(stmt).one()

    def record_run_usage(self, *, workspace_id, run_id,
                         token_usage: dict[str, int], cost_usd: float) -> None:
        run = self.s.get(AgentRun, run_id)
        run.input_tokens += token_usage.get("input", 0)
        run.output_tokens += token_usage.get("output", 0)
        run.cache_read_tokens += token_usage.get("cache_read", 0)
        run.cache_creation_tokens += token_usage.get("cache_creation", 0)
        run.total_cost_usd = (run.total_cost_usd or Decimal(0)) + Decimal(str(cost_usd))
        for scope, arid in (("run", run_id), ("workspace", None)):
            b = self._budget(workspace_id=workspace_id, scope=scope, agent_run_id=arid)
            b.spent_usd = (b.spent_usd or Decimal(0)) + Decimal(str(cost_usd))
        self.s.flush()

    def budget_spent(self, *, workspace_id, scope, agent_run_id=None) -> float:
        return float(self._budget(workspace_id=workspace_id, scope=scope,
                                  agent_run_id=agent_run_id).spent_usd)
