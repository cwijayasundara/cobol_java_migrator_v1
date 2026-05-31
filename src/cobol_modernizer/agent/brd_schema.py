from __future__ import annotations

from pydantic import BaseModel, Field

from cobol_modernizer.brd.schema import BRDSection, EvidenceMap


class BRDDraft(BaseModel):
    """What a subsystem agent and the reduce step emit. repo_id/model/strategy are
    added by our code, not the LLM, so they are absent here."""
    sections: list[BRDSection]
    evidence_map: EvidenceMap = Field(default_factory=dict)


def brd_draft_schema() -> dict:
    return BRDDraft.model_json_schema()
