"""PgRepo — the only writer of run/audit/budget rows. Neo4j stays code-graph
only; ALL cost/RBAC/run state lives here (foundation §1 strict storage split)."""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import (
    Workspace, AgentRun, Budget, WorkUnit,
)

WORK_UNIT_TERMINAL_CACHE_STATUSES = frozenset({"succeeded", "cached"})

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

    def create_work_unit(self, *, workspace_id: str, repo_slug: str, stage: str,
                         unit_type: str, unit_key: str, input_hash: str,
                         agent_run_id: str | None = None,
                         parent_unit_ids: list[str] | None = None,
                         model: str | None = None,
                         timeout_s: float | None = None,
                         max_turns: int | None = None) -> WorkUnit:
        existing = self.s.scalars(select(WorkUnit).where(
            WorkUnit.workspace_id == workspace_id,
            WorkUnit.stage == stage,
            WorkUnit.unit_type == unit_type,
            WorkUnit.unit_key == unit_key,
            WorkUnit.input_hash == input_hash,
        )).first()
        if existing is not None:
            return existing
        unit = WorkUnit(
            workspace_id=workspace_id, agent_run_id=agent_run_id,
            repo_slug=repo_slug, stage=stage, unit_type=unit_type,
            unit_key=unit_key, input_hash=input_hash, status="pending",
            parent_unit_ids=list(parent_unit_ids or []), model=model,
            timeout_s=Decimal(str(timeout_s)) if timeout_s is not None else None,
            max_turns=max_turns)
        self.s.add(unit); self.s.flush()
        return unit

    def find_cached_work_unit(self, *, workspace_id: str, stage: str,
                              unit_type: str, unit_key: str,
                              input_hash: str) -> WorkUnit | None:
        stmt = select(WorkUnit).where(
            WorkUnit.workspace_id == workspace_id,
            WorkUnit.stage == stage,
            WorkUnit.unit_type == unit_type,
            WorkUnit.unit_key == unit_key,
            WorkUnit.input_hash == input_hash,
            WorkUnit.status.in_(WORK_UNIT_TERMINAL_CACHE_STATUSES),
        )
        return self.s.scalars(stmt).first()

    def mark_work_unit_running(self, unit_id: str, *,
                               model: str | None = None,
                               timeout_s: float | None = None,
                               max_turns: int | None = None) -> WorkUnit:
        from cobol_modernizer.persistence.tables import _now

        unit = self.s.get(WorkUnit, unit_id)
        if unit is None:
            raise ValueError(f"work unit not found: {unit_id}")
        unit.status = "running"
        unit.attempt += 1
        unit.started_at = _now()
        unit.finished_at = None
        unit.error_cause = None
        if model is not None:
            unit.model = model
        if timeout_s is not None:
            unit.timeout_s = Decimal(str(timeout_s))
        if max_turns is not None:
            unit.max_turns = max_turns
        self.s.flush()
        return unit

    def mark_work_unit_succeeded(self, unit_id: str, *, payload: dict,
                                 token_usage: dict[str, int] | None = None,
                                 cost_usd: float = 0.0,
                                 artifact_id: str | None = None,
                                 cached: bool = False) -> WorkUnit:
        from cobol_modernizer.persistence.tables import _now

        unit = self.s.get(WorkUnit, unit_id)
        if unit is None:
            raise ValueError(f"work unit not found: {unit_id}")
        unit.status = "cached" if cached else "succeeded"
        unit.payload = dict(payload or {})
        unit.token_usage = dict(token_usage or {})
        unit.cost_usd = Decimal(str(max(0.0, cost_usd)))
        unit.artifact_id = artifact_id
        unit.error_cause = None
        unit.finished_at = _now()
        self.s.flush()
        return unit

    def mark_work_unit_failed(self, unit_id: str, *, error_cause: str,
                              payload: dict | None = None,
                              token_usage: dict[str, int] | None = None,
                              cost_usd: float = 0.0,
                              deferred: bool = False) -> WorkUnit:
        from cobol_modernizer.persistence.tables import _now

        unit = self.s.get(WorkUnit, unit_id)
        if unit is None:
            raise ValueError(f"work unit not found: {unit_id}")
        unit.status = "deferred" if deferred else "failed"
        unit.error_cause = error_cause
        unit.payload = dict(payload or {})
        unit.token_usage = dict(token_usage or {})
        unit.cost_usd = Decimal(str(max(0.0, cost_usd)))
        unit.finished_at = _now()
        self.s.flush()
        return unit

    def list_work_units(self, *, workspace_id: str, stage: str | None = None,
                        status: str | None = None) -> list[WorkUnit]:
        stmt = select(WorkUnit).where(WorkUnit.workspace_id == workspace_id)
        if stage is not None:
            stmt = stmt.where(WorkUnit.stage == stage)
        if status is not None:
            stmt = stmt.where(WorkUnit.status == status)
        stmt = stmt.order_by(WorkUnit.created_at, WorkUnit.id)
        return list(self.s.scalars(stmt))
