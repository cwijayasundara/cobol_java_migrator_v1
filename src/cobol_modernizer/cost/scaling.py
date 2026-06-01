"""Size-adaptive agent budgets, shared by the LLM stages (BRD, codegen).

COBOL codebases span tiny utilities to thousands of programs, so a single global
turn budget / model is always wrong for someone. These helpers scale the work to
its size: a small slice gets a small turn budget on a cheap+fast model; a large
one gets more turns on a stronger model — bounded so neither starves nor runs away
on cost. Callers own the actual numbers (env knobs); this is just the policy."""
from __future__ import annotations

from cobol_modernizer.cost.tiering import TIER_MODELS


def turns_for(n_units: int, *, lo: int, hi: int, base: int = 12, per: int = 6) -> int:
    """Agent turn budget scaled to work size (`base + n_units//per`), clamped to
    [lo, hi]. The structured-output emission itself costs a turn under
    claude-agent-sdk 0.2.87, so `lo` must leave room to explore AND emit."""
    return max(lo, min(hi, base + max(0, n_units) // max(1, per)))


def model_for_size(n_units: int, *, threshold: int, small_tier: str = "haiku",
                   large_tier: str = "sonnet", pinned: str | None = None) -> str:
    """Pick a model by work size: `small_tier` at/under `threshold`, else
    `large_tier`. `pinned` (an explicit model id from env/args) always wins, so
    auto-tiering never overrides an operator's deliberate choice."""
    if pinned:
        return pinned
    tier = small_tier if n_units <= threshold else large_tier
    return TIER_MODELS[tier]
