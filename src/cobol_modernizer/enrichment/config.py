"""Model + timeout resolution for the LLM enrichment stages. Enrichment is
narrative (not a hard judgement) on a serial path, so it defaults to Sonnet — never
Opus. Per-stage env override wins, then the global model pin, then Sonnet."""
from __future__ import annotations

import os

from cobol_modernizer.cost.tiering import GLOBAL_ENV, SONNET

_MODEL_ENV = {"seams": "SEAM_ENRICH_MODEL", "plan": "PLAN_ENRICH_MODEL",
              "design": "DESIGN_ENRICH_MODEL"}


def enrich_model(stage: str) -> str:
    stage_env = _MODEL_ENV.get(stage, "")
    return (stage_env and os.getenv(stage_env)) or os.getenv(GLOBAL_ENV) or SONNET


def enrich_timeout_s(stage: str, default: float = 180.0) -> float:
    return float(os.getenv(f"{stage.upper()}_ENRICH_TIMEOUT_S", str(default)))
