"""Shared plumbing for the batched LLM enrichers: a timeout-guarded structured call
that NEVER raises (returns {} on timeout/error, so a stage degrades to
deterministic-only), and a groundedness filter for cited refs."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_batched(*, runner, system: str, prompt: str, schema: dict[str, Any],
                      model: str, timeout_s: float, label: str,
                      max_turns: int = 2) -> dict[str, Any]:
    """One batched structured-output call, tool-free, with a hard timeout. The
    harness already swallows its own errors to {}, but it has no timeout — wrap it so
    a hung subprocess can't hang the enrich job forever."""
    try:
        return await asyncio.wait_for(
            runner.run_structured(system=system, prompt=prompt, server=None,
                                  allowed_tools=[], model=model, max_turns=max_turns,
                                  schema=schema, label=label),
            timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("enrichment %s timed out after %.0fs", label, timeout_s)
        return {}
    except Exception:  # noqa: BLE001 — never let enrichment crash a stage
        logger.exception("enrichment %s failed", label)
        return {}


def ground_refs(cited: Any, known_refs: set[str]) -> tuple[list[str], bool]:
    """Keep only cited refs that exist in the graph; 'grounded' is True iff every
    cited ref was known AND at least one ref was cited (mirrors awrite_rationale)."""
    cited_list = [c for c in (cited or []) if isinstance(c, str)]
    grounded = [c for c in cited_list if c in known_refs]
    return grounded, (len(grounded) == len(cited_list) and len(cited_list) > 0)
