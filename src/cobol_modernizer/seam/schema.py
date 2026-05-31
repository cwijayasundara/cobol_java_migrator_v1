from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

EvidenceMap = dict[str, list[str]]
"""signal_name -> [graph entity ids / source refs] backing that signal."""


class SeamType(str, Enum):
    batch_io = "batch_io"          # sequential file IO batch program -> Spring Batch adapter
    cics_api = "cics_api"          # CICS/online txn -> facade routed by transaction id
    db_reader = "db_reader"        # read-only data access -> CDC / read replica
    db_writer = "db_writer"        # write/REWRITE data access -> Extract Product Lines + ACL
    copybook = "copybook"          # shared copybook -> canonical DTO + anti-corruption layer


class SeamSignals(BaseModel):
    """Raw, Cypher-computed signals (un-normalized). Scoring normalizes + weights."""
    business: float        # business-criticality proxy (fan-in + entry-point reach)
    isolation: float       # 1 - shared-state coupling (fewer shared resources = higher)
    testability: float     # reader-only + low control-flow complexity proxy
    data_ownership: float  # fraction of touched resources this program exclusively owns
    risk: float            # writer + side-effect (billing/audit) + churn proxy


class SeamScore(BaseModel):
    weighted: float
    normalized: dict[str, float] = Field(default_factory=dict)  # signal -> [0,1]


class TransitionPattern(BaseModel):
    name: str
    summary: str


class SeamCandidate(BaseModel):
    program: str
    seam_type: SeamType
    signals: SeamSignals
    score: SeamScore
    transition: TransitionPattern
    evidence_map: EvidenceMap = Field(default_factory=dict)
    identity_drift_writer: bool = False  # writer that must stay single-system
    rationale: str = ""                  # LLM-written, groundedness-gated (Task 8)


class SeamSet(BaseModel):
    repo_id: str
    candidates: list[SeamCandidate]      # ranked desc by score.weighted
    duplicate_capabilities: list[list[str]] = Field(default_factory=list)
    dead_paragraphs: list[str] = Field(default_factory=list)
