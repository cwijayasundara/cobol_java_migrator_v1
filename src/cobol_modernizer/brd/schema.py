from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


EvidenceMap = dict[str, list[str]]
"""requirement_id -> list of graph entity ids and/or source file paths."""


Severity = Literal["low", "medium", "high"]


class Rating(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Strategy(str, Enum):
    single_shot = "single_shot"
    map_reduce = "map_reduce"


class Dimension(str, Enum):
    completeness = "completeness"
    accuracy = "accuracy"
    clarity = "clarity"
    consistency = "consistency"
    actionability = "actionability"


class DimensionScore(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str


class FeedbackItem(BaseModel):
    dimension: Dimension
    severity: Severity
    suggestion: str
    target_section: str


class JudgeReport(BaseModel):
    dimensions: dict[Dimension, DimensionScore]
    weighted_score: float
    rating: Rating
    feedback: list[FeedbackItem]
    groundedness_failures: list[str]  # entity names not present in the graph


class Requirement(BaseModel):
    id: str  # e.g. "FR-1", "NFR-3"
    text: str


class BRDSection(BaseModel):
    title: str
    body_markdown: str
    requirements: list[Requirement] = Field(default_factory=list)


class BRD(BaseModel):
    sections: list[BRDSection]
    evidence_map: EvidenceMap
    repo_id: str
    model: str
    strategy: Strategy


class AttemptRecord(BaseModel):
    attempt: int  # 1-indexed
    rating: Rating
    weighted_score: float
    feedback: list[FeedbackItem]


class BRDResult(BaseModel):
    brd_id: str
    repo_id: str
    version: int
    rating: Rating
    weighted_score: float
    attempts: int
    attempt_history: list[AttemptRecord]
    model: str
    strategy: Strategy
    html_path: str
    created_at: datetime
    token_usage: dict[str, int] = Field(default_factory=dict)
