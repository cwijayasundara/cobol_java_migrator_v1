from __future__ import annotations

from pydantic import BaseModel, Field


class TraceLink(BaseModel):
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    reason: str = ""


class LogicCoverageReport(BaseModel):
    repo_slug: str
    total_refs: int
    covered_refs: list[str] = Field(default_factory=list)
    uncovered_refs: list[str] = Field(default_factory=list)
    exclusions: dict[str, str] = Field(default_factory=dict)
    coverage_ratio: float = 0.0
