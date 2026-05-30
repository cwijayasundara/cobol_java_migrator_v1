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
