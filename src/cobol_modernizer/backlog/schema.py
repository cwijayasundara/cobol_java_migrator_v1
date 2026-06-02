from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    id: str
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)
    golden_fixture_ids: list[str] = Field(default_factory=list)


class Epic(BaseModel):
    id: str
    title: str
    outcome: str
    brd_requirement_ids: list[str] = Field(default_factory=list)
    story_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class UserStory(BaseModel):
    id: str
    epic_id: str
    title: str
    actor: str
    narrative: str
    brd_requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    seam_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    context: str | None = None
    topology: str | None = None


class Backlog(BaseModel):
    repo_slug: str
    version: int = 0
    epics: list[Epic] = Field(default_factory=list)
    stories: list[UserStory] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
