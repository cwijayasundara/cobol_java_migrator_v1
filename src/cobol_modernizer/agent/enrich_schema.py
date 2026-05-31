from __future__ import annotations

from pydantic import BaseModel, Field


class EnrichmentTags(BaseModel):
    """Architectural tags for one entity. Defaults let a sparse/empty model response
    degrade gracefully instead of raising."""
    patterns: list[str] = Field(default_factory=list)
    layer: str = "unknown"
    concepts: list[str] = Field(default_factory=list)
    summary: str = ""


def enrichment_tags_schema() -> dict:
    return EnrichmentTags.model_json_schema()
