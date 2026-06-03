"""Shared plumbing for the batched LLM enrichers: a timeout-guarded structured call
that NEVER raises (returns {} on timeout/error, so a stage degrades to
deterministic-only), and a groundedness filter for cited refs."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentResult:
    """Typed outcome of a batched structured call. `ok` is True only when the LLM
    returned a non-empty payload. On failure, `cause` names the concrete reason
    (timeout / turn-cap-or-parse-or-api-error / exception) so a GATING caller can
    surface it; `payload` is always `{}` on failure. Non-gating callers ignore the
    cause and use `run_batched` (which returns just `.payload`)."""

    payload: dict[str, Any]
    ok: bool
    cause: str | None


async def run_batched_result(*, runner, system: str, prompt: str, schema: dict[str, Any],
                             model: str, timeout_s: float, label: str,
                             max_turns: int = 2) -> EnrichmentResult:
    """One batched structured-output call, tool-free, with a hard timeout, returning
    a TYPED result. The harness swallows its own errors to {} (turn cap / parse /
    api error) and has no timeout — wrap it so a hung subprocess can't hang the job
    forever, and distinguish WHICH failure happened for gating callers."""
    try:
        payload = await asyncio.wait_for(
            runner.run_structured(system=system, prompt=prompt, server=None,
                                  allowed_tools=[], model=model, max_turns=max_turns,
                                  schema=schema, label=label),
            timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("enrichment %s timed out after %.0fs", label, timeout_s)
        return EnrichmentResult(payload={}, ok=False, cause=f"timeout after {timeout_s:.0f}s")
    except Exception as exc:  # noqa: BLE001 — never let enrichment crash a stage
        logger.exception("enrichment %s failed", label)
        return EnrichmentResult(payload={}, ok=False, cause=f"error: {type(exc).__name__}")

    if payload:
        return EnrichmentResult(payload=payload, ok=True, cause=None)

    # Empty/falsy payload with NO exception: the harness already swallowed a turn-cap,
    # parse, or api error to {}. Enrich the cause with any per-call diagnostics it left.
    cause = "no output (turn cap / parse / api error)"
    calls = getattr(runner, "calls", None)
    if calls:
        last = calls[-1]
        diag = []
        if last.get("hit_turn_cap"):
            diag.append("hit turn cap")
        if last.get("api_error_status") is not None:
            diag.append(f"api_error_status={last['api_error_status']}")
        if diag:
            cause = f"{cause}: {', '.join(diag)}"
    logger.warning("enrichment %s returned empty payload (%s)", label, cause)
    return EnrichmentResult(payload={}, ok=False, cause=cause)


async def run_batched(*, runner, system: str, prompt: str, schema: dict[str, Any],
                      model: str, timeout_s: float, label: str,
                      max_turns: int = 2) -> dict[str, Any]:
    """Backward-compatible bare-dict wrapper: returns just the payload (so the
    silent-degrade contract for non-gating enrichers — seams/design/plan — is
    unchanged). Gating callers should use `run_batched_result` for the typed cause."""
    result = await run_batched_result(
        runner=runner, system=system, prompt=prompt, schema=schema, model=model,
        timeout_s=timeout_s, label=label, max_turns=max_turns)
    return result.payload


def ground_refs(cited: Any, known_refs: set[str]) -> tuple[list[str], bool]:
    """Keep only cited refs that exist in the graph; 'grounded' is True iff every
    cited ref was known AND at least one ref was cited (mirrors awrite_rationale)."""
    cited_list = [c for c in (cited or []) if isinstance(c, str)]
    grounded = [c for c in cited_list if c in known_refs]
    return grounded, (len(grounded) == len(cited_list) and len(cited_list) > 0)
