"""Pydantic contracts for the LLM enrichment payloads. These are returned BY ID
(program / story_id / slice_id) and merged into the deterministic output in the UI;
the deterministic schemas are never mutated."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SeamNarrative(BaseModel):
    program: str
    rationale: str = ""
    cited_refs: list[str] = Field(default_factory=list)
    grounded: bool = False


class StoryNarrative(BaseModel):
    story_id: str
    invest: dict[str, int] = Field(default_factory=dict)   # 6 dims, 1-5
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    groundedness_failures: list[str] = Field(default_factory=list)


class WaveNote(BaseModel):
    wave: int
    narrative: str = ""


class PlanDeliveryNarrative(BaseModel):
    edge_rationale: dict[str, str] = Field(default_factory=dict)   # "S3->S1" -> why
    wave_narrative: list[WaveNote] = Field(default_factory=list)


class DesignADR(BaseModel):
    number: int
    title: str
    context: str = ""
    decision: str = ""
    consequences: str = ""
    alternatives: str = ""


class DesignNarrative(BaseModel):
    slice_id: str
    adrs: list[DesignADR] = Field(default_factory=list)
    component_descriptions: list[str] = Field(default_factory=list)
    api_surface: str = ""
    data_model_notes: str = ""
    cited_refs: list[str] = Field(default_factory=list)
