"""Model tiering: resolve_model(role) -> Claude model id (master plan §2).

Covers the 11 roles the full platform needs. Tiers: Haiku for high-volume
breadth, Sonnet for synthesis throughput, Opus reserved for planning/judging/
hard calls.
"""
from __future__ import annotations

import os

# Single global model var (override per-role below). Must be a Claude model id.
GLOBAL_ENV = "COBOL_MOD_LLM_MODEL"

_ROLE_ENV = {
    "enrichment": "ENRICHMENT_MODEL",
    "ask": "ASK_MODEL",
    "equivalence_triage": "EQUIV_TRIAGE_MODEL",
    "brd": "BRD_AGENT_MODEL",
    "seam": "SEAM_MODEL",
    "story": "STORY_MODEL",
    "codegen": "CODEGEN_MODEL",
    "judge": "JUDGE_MODEL",
    "design": "DESIGN_MODEL",
    "repair": "REPAIR_MODEL",
    "advisor": "ADVISOR_MODEL",
}

# Hardcoded Claude fallbacks by tier.
_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"
_OPUS = "claude-opus-4-8"

# Public tier aliases + lookup (for size-based model selection; see cost/scaling.py).
HAIKU, SONNET, OPUS = _HAIKU, _SONNET, _OPUS
TIER_MODELS = {"haiku": _HAIKU, "sonnet": _SONNET, "opus": _OPUS}

_DEFAULTS = {
    "enrichment": _HAIKU,
    "ask": _HAIKU,
    "equivalence_triage": _HAIKU,
    "brd": _SONNET,
    "seam": _SONNET,
    "story": _SONNET,
    "codegen": _SONNET,
    "judge": _OPUS,
    "design": _OPUS,
    "repair": _OPUS,
    "advisor": _OPUS,
}


def resolve_model(role: str) -> str:
    """Resolve the Claude model for a role.

    Precedence: per-role override env var -> global COBOL_MOD_LLM_MODEL ->
    hardcoded Claude default for the role (Sonnet if role unknown).
    """
    role_env = _ROLE_ENV.get(role)
    if role_env and os.getenv(role_env):
        return os.environ[role_env]
    if os.getenv(GLOBAL_ENV):
        return os.environ[GLOBAL_ENV]
    return _DEFAULTS.get(role, _SONNET)
