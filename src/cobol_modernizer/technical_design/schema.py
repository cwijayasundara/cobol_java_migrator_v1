from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ApiContract(BaseModel):
    name: str
    method: str
    path: str
    request_model: str = ""
    response_model: str = ""
    details: str = ""


class PersistenceDesign(BaseModel):
    resource: str
    access_pattern: Literal["legacy-mimic", "repository", "event-sourced", "read-replica"]
    owner_service: str = ""
    details: str = ""


class IntegrationContract(BaseModel):
    name: str
    style: Literal["sync", "async", "batch"]
    target: str
    payload: str = ""


class TechnicalService(BaseModel):
    name: str
    bounded_context: str
    deployment: Literal["module", "microservice"]
    story_ids: list[str] = Field(default_factory=list)
    api_contracts: list[ApiContract] = Field(default_factory=list)
    persistence: list[PersistenceDesign] = Field(default_factory=list)
    integrations: list[IntegrationContract] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class TechnicalDesign(BaseModel):
    repo_slug: str
    version: int = 0
    services: list[TechnicalService] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
