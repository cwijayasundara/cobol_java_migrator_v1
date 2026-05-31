from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# Reuse the foundation lineage contract: requirement_id -> [graph entity ids / source refs].
DesignEvidenceMap = dict[str, list[str]]


class BoundedContext(str, Enum):
    """The four CardDemo bounded contexts derived from seams + data ownership
    (master plan Phase 5). Assignment is deterministic (context_map.py), not LLM."""
    account_management = "account_management"
    card_management = "card_management"
    transaction_processing = "transaction_processing"
    bill_pay_reporting = "bill_pay_reporting"


Deployment = Literal["modular_monolith", "microservice"]


class ServiceDesign(BaseModel):
    slice_id: str
    deployment: Deployment = "modular_monolith"   # modular monolith is the default
    context: BoundedContext
    owned_resources: list[str]                     # VSAM/file/table this service OWNS (writes)
    transition_pattern: str                        # e.g. extract_product_lines+legacy_mimic
    components: list[str]                           # planned Java components
    evidence_map: DesignEvidenceMap = Field(default_factory=dict)


class ADR(BaseModel):
    number: int
    title: str
    status: Literal["proposed", "accepted", "superseded"] = "accepted"
    context: str
    decision: str
    consequences: str
    evidence_refs: list[str] = Field(default_factory=list)


class DesignResult(BaseModel):
    design: ServiceDesign
    adrs: list[ADR]
    rating: Literal["high", "medium", "low"]
    weighted_score: float
