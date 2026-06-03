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


def _is_retryable(result: EnrichmentResult, *, runner) -> bool:
    """A failure is worth re-issuing (with escalation) only when it looks like the
    unit ran out of room rather than hitting a hard error: a TIMEOUT (the wait_for
    tripped) OR an empty payload because the harness hit its turn cap. An
    `error: <type>` exception or a generic empty (no turn-cap, e.g. parse / bad
    schema) is NON-retryable — re-issuing would just burn the same budget again."""
    if result.ok or not result.cause:
        return False
    if result.cause.startswith("timeout"):
        return True
    if result.cause.startswith("error:"):
        return False  # a real exception — fail fast, don't retry
    # Empty payload: only retry when the harness diagnostics say it hit the turn cap.
    calls = getattr(runner, "calls", None)
    if calls and calls[-1].get("hit_turn_cap"):
        return True
    return False


async def _run_once(*, runner, system: str, prompt: str, schema: dict[str, Any],
                    model: str, timeout_s: float, label: str,
                    max_turns: int) -> EnrichmentResult:
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


async def run_batched_result(*, runner, system: str, prompt: str, schema: dict[str, Any],
                             model: str, timeout_s: float, label: str,
                             max_turns: int = 2, attempts: int = 1,
                             escalate: bool = True) -> EnrichmentResult:
    """Shared escalation primitive for fan-out units (backlog story, tech-design
    context, story codegen). Issues one timeout-guarded structured call and, when a
    caller OPTS IN via `attempts>1`, loops a bit harder before giving up: on a
    RETRYABLE failure (a timeout, or an empty payload because the harness hit its
    turn cap) it re-issues the call with an ESCALATED `timeout_s` and `max_turns`
    (each ×1.5, rounded, per attempt when `escalate=True`), up to `attempts` total,
    returning the first `ok=True` result.

    Backward compatibility is a hard constraint: `attempts=1` (the default) is
    byte-identical to a single `_run_once` call — exactly one structured call, no
    retry, the same typed result on success / timeout / empty. NON-retryable causes
    (a real `error: <type>` exception, or a generic empty with no turn-cap) fail fast
    after the first attempt even when `attempts>1`. This NEVER raises: on exhaustion
    it returns the last typed failure (payload `{}`), preserving the silent-degrade
    contract for non-gating callers via `run_batched`."""
    attempts = max(1, int(attempts))
    cur_timeout = timeout_s
    cur_turns = max_turns
    result = await _run_once(
        runner=runner, system=system, prompt=prompt, schema=schema, model=model,
        timeout_s=cur_timeout, label=label, max_turns=cur_turns)
    for attempt in range(2, attempts + 1):
        if result.ok or not _is_retryable(result, runner=runner):
            break
        if escalate:
            cur_timeout = cur_timeout * 1.5
            cur_turns = round(cur_turns * 1.5)
        logger.warning(
            "enrichment %s retryable failure (%s); attempt %d/%d "
            "(timeout_s=%.0f, max_turns=%d)",
            label, result.cause, attempt, attempts, cur_timeout, cur_turns)
        result = await _run_once(
            runner=runner, system=system, prompt=prompt, schema=schema, model=model,
            timeout_s=cur_timeout, label=label, max_turns=cur_turns)
    return result


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
