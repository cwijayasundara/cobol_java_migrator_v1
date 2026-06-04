"""Postgres run/audit/version/RBAC schema (Neo4j is code-graph only).

Portable types are used deliberately so the same mapped classes run on Postgres
(production) and in-memory SQLite (shape tests): ``JSON`` not ``JSONB``, string
UUID primary keys, ``Numeric`` for money. Column names mirror the foundation
schema verbatim — downstream plans reference them by name.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    repo_slug: Mapped[str] = mapped_column(String, nullable=False)
    graph_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")


class JourneyStage(Base):
    __tablename__ = "journey_stage"
    __table_args__ = (UniqueConstraint("workspace_id", "stage_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    stage_id: Mapped[str | None] = mapped_column(
        ForeignKey("journey_stage.id", ondelete="CASCADE"), nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    started_by: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Artifact(Base):
    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    stage_id: Mapped[str | None] = mapped_column(
        ForeignKey("journey_stage.id", ondelete="CASCADE"), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    object_uri: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    evidence_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Gate(Base):
    __tablename__ = "gate"
    __table_args__ = (UniqueConstraint("workspace_id", "gate_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    stage_id: Mapped[str | None] = mapped_column(
        ForeignKey("journey_stage.id", ondelete="CASCADE"), nullable=True)
    gate_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    threshold: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    __tablename__ = "approval"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    gate_id: Mapped[str] = mapped_column(
        ForeignKey("gate.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    approver_email: Mapped[str] = mapped_column(String, nullable=False)
    approver_role: Mapped[str] = mapped_column(String, nullable=False)
    risk_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Budget(Base):
    __tablename__ = "budget"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run.id"), nullable=True)
    cap_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    spent_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    killed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DefectTicket(Base):
    """An equivalence-diff failure, linked to the COBOL source seam that owns
    the failing field (Phase 3). ``source_seam`` is a real graph entity qname,
    never invented; ``dialect_note`` records the GnuCOBOL-vs-mainframe
    provenance behind the §7 fidelity risk."""
    __tablename__ = "defect_ticket"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    stage_id: Mapped[str | None] = mapped_column(
        ForeignKey("journey_stage.id", ondelete="CASCADE"), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run.id"), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact.id"), nullable=True)
    source_seam: Mapped[str] = mapped_column(String, nullable=False)
    seam_edge_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String, nullable=True)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field: Mapped[str] = mapped_column(String, nullable=False)
    record_key: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="high")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    dialect_note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- Phase 6: deployment automation + canary (Postgres run/audit split) ---
# Neo4j carries zero deploy/routing state; everything below is Postgres state.
class Deployment(Base):
    __tablename__ = "deployment"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact.id"), nullable=True)         # the spring_boot_project
    slice_name: Mapped[str] = mapped_column(String, nullable=False)
    image_ref: Mapped[str] = mapped_column(String, nullable=False)
    image_digest: Mapped[str] = mapped_column(String, nullable=False)   # sha256 anchor
    smoke_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    perf_baseline: Mapped[dict] = mapped_column(JSON, default=dict)      # PerfBaseline body
    status: Mapped[str] = mapped_column(String, default="built")
    # built|smoked|baselined|canarying|promoted|rolled_back
    created_by: Mapped[str] = mapped_column(String, nullable=False)      # RBAC identity
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CanaryRoute(Base):
    __tablename__ = "canary_route"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    slice_name: Mapped[str] = mapped_column(String, nullable=False)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deployment.id"), nullable=True)        # canary image behind the route
    canary_pct: Mapped[int] = mapped_column(Integer, default=0)   # 0 == full legacy (safe)
    legacy_pct: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    rollback_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (
        UniqueConstraint("workspace_id", "slice_name", "active",
                         name="uq_canary_route_active"),    # one active route per slice
    )


class FitnessCheck(Base):
    __tablename__ = "fitness_check"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    report: Mapped[dict] = mapped_column(JSON, default=dict)      # FitnessReport body
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (
        UniqueConstraint("workspace_id", "commit_sha", name="uq_fitness_commit"),
    )


class AgentRunEvent(Base):
    """Append-only per-run event log feeding the cockpit SSE stream. One row per
    emitted event; (run_id, seq) is unique and monotonically increasing per run."""
    __tablename__ = "agent_run_event"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    type: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_run_event_seq"),
    )


class WorkUnit(Base):
    """Durable progress/cache record for one bounded unit of LLM or verification work.

    Stages such as BRD, backlog, domain design, technical design, codegen, and verify
    should record every expensive unit here rather than hiding progress inside one
    opaque background job. The cache key is the stage/unit identity plus the input
    hash; a succeeded/cached row with the same hash can be reused on a later run.
    """
    __tablename__ = "work_unit"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "stage", "unit_type", "unit_key", "input_hash",
            name="uq_work_unit_cache_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_run.id", ondelete="SET NULL"), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact.id", ondelete="SET NULL"), nullable=True)
    repo_slug: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    unit_type: Mapped[str] = mapped_column(String, nullable=False)
    unit_key: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    timeout_s: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    max_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_unit_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
