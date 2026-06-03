"""Large-repo cost + resume gates (Task 10 of the story-sliced codegen engine).

Two small, PURE policies the story orchestrator consults:

  1. BUDGET — hard per-story limits so a runaway story stops early instead of
     burning the whole LLM/wall-time budget on one slice. The dimensions are:
       - max tokens          (env ``STORY_MAX_TOKENS``, default 200000)
       - max wall time       (REUSES patch_agent's ``STORY_CODEGEN_TIMEOUT_S``)
       - max repair attempts (REUSES patch_agent's ``STORY_REPAIR_MAX_ATTEMPTS``)
       - max concurrent jobs (= 1; the policy CONSTANT only — locking is already
         enforced by ``jobs.runner`` keyed on (kind, wid); this module does NOT
         re-implement it).

  2. RESUME — the SINGLE source of truth for "skip an already-done story on a
     re-run". A story is skippable when its prior persisted ``story_codegen_status``
     record is in an ACCEPTED terminal state AND its ``context_hash`` is unchanged.
     ``story_runner._should_skip`` DELEGATES here so there is exactly one policy.

This module is PURE: it reads ``os.environ`` (via patch_agent's helpers) but does
NO Neo4j / LLM / Maven / disk / session I/O. The story runner gathers telemetry
(token usage, wall time) and the prior record, then asks this module what to do.

INTERPRETATION (per the plan, "generated tests still pass"): the persisted record
is written at the moment a story is decided. A prior ``passed`` means the targeted
tests were GREEN when recorded; with an unchanged ``context_hash`` the inputs that
drove that pass are identical, so we treat a prior ``passed`` as skippable without
re-running Maven. ``generated-unverified`` (toolchain absent) and ``skipped`` are
likewise skippable on unchanged inputs. The accepted set is
``story_plan.ACCEPTED_STORY_STATUSES`` — the SAME set ``build_stories._gate_stage``
uses, imported (not re-listed) so the two never drift.
"""
from __future__ import annotations

from dataclasses import dataclass

from cobol_modernizer.codegen.patch_agent import (
    _env_int, story_repair_max_attempts, story_timeout_s,
)
from cobol_modernizer.codegen.story_plan import ACCEPTED_STORY_STATUSES

# Story-scoped token budget. DISTINCT env name from the slice-level CODEGEN_* knobs
# (mirrors patch_agent's STORY_* naming) so per-story tuning never shadows them.
STORY_MAX_TOKENS_ENV = "STORY_MAX_TOKENS"
DEFAULT_STORY_MAX_TOKENS = 200_000

#: Per-workspace max concurrent story jobs. This is a POLICY CONSTANT only — the
#: actual one-job-per-workspace lock is already enforced by ``jobs.runner`` keyed on
#: ``(kind, wid)``; budget.py does NOT re-implement locking, it just states the
#: contract so callers/reviewers have a single named value to assert against.
MAX_CONCURRENT_STORY_JOBS = 1


# --------------------------------------------------------------------------- #
# Budget                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StoryBudget:
    """Hard per-story limits the runner consults to stop a runaway story early.

    A non-positive ``max_tokens`` / ``max_wall_s`` DISABLES that dimension's gate
    (treated as "no cap") so an operator can opt a dimension out via env without
    special-casing it at every call site. ``max_concurrent_jobs`` is informational
    (the real lock lives in ``jobs.runner``)."""

    max_tokens: int
    max_wall_s: float
    max_repair_attempts: int
    max_concurrent_jobs: int = MAX_CONCURRENT_STORY_JOBS

    def tokens_exceeded(self, tokens_used: int) -> bool:
        """True once ``tokens_used`` is strictly OVER the cap (at-limit is allowed).
        A non-positive cap disables the gate."""
        return self.max_tokens > 0 and tokens_used > self.max_tokens

    def wall_exceeded(self, wall_s: float) -> bool:
        """True once ``wall_s`` is strictly OVER the cap. Non-positive cap disables."""
        return self.max_wall_s > 0 and wall_s > self.max_wall_s

    def repair_attempts_exceeded(self, attempts: int) -> bool:
        """True once ``attempts`` is strictly OVER the repair cap. (The runner's loop
        also bounds attempts directly; this is the shared predicate for callers that
        want to consult the budget rather than re-derive the comparison.)"""
        return attempts > self.max_repair_attempts

    def exceeded(self, *, tokens_used: int, wall_s: float) -> bool:
        """The combined early-stop predicate: True if EITHER the token or the
        wall-time budget is over. The runner consults this between passes to abort a
        runaway story before issuing the next (expensive) LLM call."""
        return self.tokens_exceeded(tokens_used) or self.wall_exceeded(wall_s)


def story_budget_from_env() -> StoryBudget:
    """Build a :class:`StoryBudget` from the environment. PURE (only os.environ reads,
    via the shared patch_agent helpers). Tokens reuse patch_agent's ``_env_int`` so
    the warn-on-bad-value behavior matches; wall time and repair attempts REUSE
    patch_agent's existing knobs (``STORY_CODEGEN_TIMEOUT_S`` /
    ``STORY_REPAIR_MAX_ATTEMPTS``) — they are NOT duplicated here."""
    return StoryBudget(
        max_tokens=_env_int(STORY_MAX_TOKENS_ENV, DEFAULT_STORY_MAX_TOKENS),
        max_wall_s=story_timeout_s(),
        max_repair_attempts=story_repair_max_attempts(),
    )


# --------------------------------------------------------------------------- #
# Resume                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResumeDecision:
    """The outcome of the resume predicate: whether to skip + a human-readable reason
    (logged by the runner so an operator can see WHY a story was/was not skipped)."""

    skip: bool
    reason: str


def _decide(prior_record: dict | None, current_context_hash: str) -> ResumeDecision:
    """The canonical resume decision over a persisted ``story_codegen_status`` record.

    Skip iff the prior record is in an ACCEPTED terminal state
    (``ACCEPTED_STORY_STATUSES`` — passed / generated-unverified / skipped) AND its
    recorded ``context_hash`` equals the current one. A missing record, a missing
    recorded hash, a changed hash, or a non-accepted status all RE-RUN."""
    if not prior_record:
        return ResumeDecision(False, "no prior record — first run")
    status = prior_record.get("status")
    if status not in ACCEPTED_STORY_STATUSES:
        return ResumeDecision(
            False, f"prior status {status!r} not accepted — re-run")
    prior_hash = prior_record.get("context_hash")
    if not prior_hash:
        return ResumeDecision(
            False, "prior record has no context_hash — cannot prove unchanged inputs")
    if prior_hash != current_context_hash:
        return ResumeDecision(
            False, "context_hash changed — inputs differ, re-run")
    return ResumeDecision(
        True, f"accepted ({status}) + unchanged context_hash — skip")


def should_skip(prior_record: dict | None, current_context_hash: str, *,
                as_decision: bool = False) -> bool | ResumeDecision:
    """SINGLE source-of-truth resume predicate. Returns a bool by default; pass
    ``as_decision=True`` to get the full :class:`ResumeDecision` (skip + reason) for
    logging. ``story_runner._should_skip`` delegates here so there is exactly one
    resume policy in the codebase."""
    decision = _decide(prior_record, current_context_hash)
    return decision if as_decision else decision.skip
