from __future__ import annotations

from pydantic import BaseModel, Field

EvidenceMap = dict[str, list[str]]


class InvestScore(BaseModel):
    independent: int = Field(ge=1, le=5)
    negotiable: int = Field(ge=1, le=5)
    valuable: int = Field(ge=1, le=5)
    estimable: int = Field(ge=1, le=5)
    small: int = Field(ge=1, le=5)
    testable: int = Field(ge=1, le=5)


class Story(BaseModel):
    id: str
    title: str
    seam: str                       # the seam (program) this story migrates
    depends_on: list[str] = Field(default_factory=list)
    invest: InvestScore | None = None
    evidence_map: EvidenceMap = Field(default_factory=dict)
    context: str | None = None          # bounded context (from domain-design), if known
    topology: str | None = None         # "module" | "microservice", if known


class StoryDAG(BaseModel):
    repo_id: str
    stories: list[Story]
