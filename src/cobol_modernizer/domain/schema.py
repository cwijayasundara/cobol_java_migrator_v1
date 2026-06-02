"""Pydantic models for the Domain Design stage (see docs/plans/domain-design-stage-spec.md).
LLM-facing JSON schemas (DECOMP_SCHEMA, CONTEXT_DESIGN_SCHEMA) intentionally OMIT the
fields Python computes (topology, extraction_rank, identity_drift) — the model proposes
membership/capability only; correctness fields are derived + gated in Python."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextDependency(BaseModel):
    target: str
    style: Literal["sync", "async"]
    reason: str
    cited_refs: list[str] = Field(default_factory=list)


class TopologyDecision(BaseModel):
    deployment: Literal["module", "microservice"]
    score: float
    inputs: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class BoundedContextDecl(BaseModel):
    name: str
    business_capability: str
    member_programs: list[str] = Field(default_factory=list)
    owned_resources: list[str] = Field(default_factory=list)
    depends_on: list[ContextDependency] = Field(default_factory=list)
    topology: TopologyDecision | None = None
    extraction_rank: int = 0
    identity_drift: bool = False
    cited_refs: list[str] = Field(default_factory=list)


class DecompositionMap(BaseModel):
    repo_slug: str
    contexts: list[BoundedContextDecl] = Field(default_factory=list)
    unassigned_programs: list[str] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


class CobolMapping(BaseModel):
    cobol_ref: str
    maps_to: str
    note: str = ""


class Aggregate(BaseModel):
    name: str
    root_entity: str
    invariants: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    value_objects: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)


class ContextDesign(BaseModel):
    context: str
    aggregates: list[Aggregate] = Field(default_factory=list)
    value_objects: list[str] = Field(default_factory=list)
    domain_services: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    domain_events: list[str] = Field(default_factory=list)
    api_surface: str = ""
    cobol_mapping: list[CobolMapping] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


class DomainDesign(BaseModel):
    repo_slug: str
    version: int = 0
    rating: str = "medium"
    weighted_score: float = 0.0
    contexts: list[BoundedContextDecl] = Field(default_factory=list)
    designs: list[ContextDesign] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


DECOMP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contexts": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "business_capability": {"type": "string"},
            "member_programs": {"type": "array", "items": {"type": "string"}},
            "owned_resources": {"type": "array", "items": {"type": "string"}},
            "depends_on": {"type": "array", "items": {"type": "object", "properties": {
                "target": {"type": "string"},
                "style": {"type": "string", "enum": ["sync", "async"]},
                "reason": {"type": "string"},
                "cited_refs": {"type": "array", "items": {"type": "string"}}},
                "required": ["target", "style"]}},
            "cited_refs": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "business_capability", "member_programs"]}},
        "unassigned_programs": {"type": "array", "items": {"type": "string"}},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["contexts"],
}

CONTEXT_DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "aggregates": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "root_entity": {"type": "string"},
            "invariants": {"type": "array", "items": {"type": "string"}},
            "entities": {"type": "array", "items": {"type": "string"}},
            "value_objects": {"type": "array", "items": {"type": "string"}},
            "methods": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "root_entity"]}},
        "value_objects": {"type": "array", "items": {"type": "string"}},
        "domain_services": {"type": "array", "items": {"type": "string"}},
        "repositories": {"type": "array", "items": {"type": "string"}},
        "domain_events": {"type": "array", "items": {"type": "string"}},
        "api_surface": {"type": "string"},
        "cobol_mapping": {"type": "array", "items": {"type": "object", "properties": {
            "cobol_ref": {"type": "string"}, "maps_to": {"type": "string"},
            "note": {"type": "string"}}, "required": ["cobol_ref", "maps_to"]}},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["aggregates"],
}
