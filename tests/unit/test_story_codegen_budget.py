"""Unit tests for the story-codegen budget + resume policy (Task 10).

PURE module: no Neo4j / LLM / Maven / disk. Only `os.environ` is touched (and
only via `monkeypatch`). Two policies are covered:

  * Budget — per-story token/wall-time/repair-attempt limits built from env
    (defaults + overrides) and a per-dimension `exceeded` predicate.
  * Resume — the SINGLE source-of-truth `should_skip` over a prior persisted
    `story_codegen_status` record + the current `context_hash`.
"""
from __future__ import annotations

from cobol_modernizer.codegen.budget import (
    DEFAULT_BUILD_MAX_STORY_ATTEMPTS, DEFAULT_STORY_MAX_TOKENS,
    MAX_CONCURRENT_STORY_JOBS, BuildBudget, StoryBudget, ResumeDecision,
    build_budget_from_env, build_max_story_attempts, should_skip,
    story_budget_from_env,
)
from cobol_modernizer.codegen.story_plan import (
    ACCEPTED_STORY_STATUSES, StoryCodegenStatus,
)


# --------------------------------------------------------------------------- #
# Budget — build from env (defaults + overrides)                              #
# --------------------------------------------------------------------------- #
def test_budget_defaults_from_env(monkeypatch):
    monkeypatch.delenv("STORY_MAX_TOKENS", raising=False)
    monkeypatch.delenv("STORY_CODEGEN_TIMEOUT_S", raising=False)
    monkeypatch.delenv("STORY_REPAIR_MAX_ATTEMPTS", raising=False)
    b = story_budget_from_env()
    assert b.max_tokens == DEFAULT_STORY_MAX_TOKENS
    # wall-time REUSES patch_agent's STORY_CODEGEN_TIMEOUT_S (default 120.0)
    assert b.max_wall_s == 120.0
    # repair attempts REUSE patch_agent's STORY_REPAIR_MAX_ATTEMPTS (default 2)
    assert b.max_repair_attempts == 2
    assert b.max_concurrent_jobs == MAX_CONCURRENT_STORY_JOBS == 1


def test_budget_overrides_from_env(monkeypatch):
    monkeypatch.setenv("STORY_MAX_TOKENS", "50000")
    monkeypatch.setenv("STORY_CODEGEN_TIMEOUT_S", "30")
    monkeypatch.setenv("STORY_REPAIR_MAX_ATTEMPTS", "5")
    b = story_budget_from_env()
    assert b.max_tokens == 50000
    assert b.max_wall_s == 30.0
    assert b.max_repair_attempts == 5


def test_budget_bad_token_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("STORY_MAX_TOKENS", "not-a-number")
    b = story_budget_from_env()
    assert b.max_tokens == DEFAULT_STORY_MAX_TOKENS


# --------------------------------------------------------------------------- #
# Budget — exceeded / within-budget predicate per dimension                   #
# --------------------------------------------------------------------------- #
def _budget(max_tokens=1000, max_wall_s=60.0, max_repair_attempts=2):
    return StoryBudget(max_tokens=max_tokens, max_wall_s=max_wall_s,
                       max_repair_attempts=max_repair_attempts)


def test_within_budget_not_exceeded():
    b = _budget()
    assert b.exceeded(tokens_used=10, wall_s=1.0) is False


def test_tokens_exceeded():
    b = _budget(max_tokens=1000)
    assert b.exceeded(tokens_used=1001, wall_s=0.0) is True
    assert b.tokens_exceeded(1001) is True
    assert b.tokens_exceeded(1000) is False  # at-limit is allowed


def test_wall_time_exceeded():
    b = _budget(max_wall_s=60.0)
    assert b.exceeded(tokens_used=0, wall_s=60.1) is True
    assert b.wall_exceeded(60.1) is True
    assert b.wall_exceeded(60.0) is False


def test_repair_attempts_exceeded():
    b = _budget(max_repair_attempts=2)
    assert b.repair_attempts_exceeded(2) is False
    assert b.repair_attempts_exceeded(3) is True


def test_zero_or_negative_token_limit_disables_token_gate():
    # A non-positive limit means "no token cap" — never exceeded on tokens.
    b = _budget(max_tokens=0)
    assert b.tokens_exceeded(10_000_000) is False
    assert b.exceeded(tokens_used=10_000_000, wall_s=0.0) is False


# --------------------------------------------------------------------------- #
# Resume — accepted-status set shared with the build gate                     #
# --------------------------------------------------------------------------- #
def test_accepted_status_set_is_the_gate_set():
    # The resume "skippable prior status" set is the SAME accepted set the build
    # gate uses (passed / generated-unverified / skipped) — single source of truth.
    assert ACCEPTED_STORY_STATUSES == frozenset({
        StoryCodegenStatus.passed.value,
        StoryCodegenStatus.generated_unverified.value,
        StoryCodegenStatus.skipped.value,
    })


# --------------------------------------------------------------------------- #
# Resume — should_skip predicate                                             #
# --------------------------------------------------------------------------- #
def _record(status, context_hash="h1"):
    return {"status": status, "context_hash": context_hash}


def test_skip_passed_unchanged_hash():
    rec = _record("passed", "h1")
    assert should_skip(rec, "h1") is True


def test_skip_generated_unverified_unchanged_hash():
    rec = _record("generated-unverified", "h1")
    assert should_skip(rec, "h1") is True


def test_skip_prior_skipped_unchanged_hash():
    rec = _record("skipped", "h1")
    assert should_skip(rec, "h1") is True


def test_no_skip_on_changed_hash():
    rec = _record("passed", "OLD")
    assert should_skip(rec, "NEW") is False


def test_no_skip_on_failed_prior_status():
    rec = _record("failed", "h1")
    assert should_skip(rec, "h1") is False


def test_no_skip_on_blocked_prior_status():
    rec = _record("blocked", "h1")
    assert should_skip(rec, "h1") is False


def test_no_skip_on_missing_record():
    assert should_skip(None, "h1") is False


def test_no_skip_on_record_missing_context_hash():
    # A prior accepted record with NO recorded context_hash can't prove the inputs
    # are unchanged, so it must re-run rather than skip silently.
    assert should_skip({"status": "passed"}, "h1") is False


def test_resume_decision_carries_reason():
    d = should_skip(_record("passed", "h1"), "h1", as_decision=True)
    assert isinstance(d, ResumeDecision)
    assert d.skip is True
    assert d.reason

    d2 = should_skip(_record("failed", "h1"), "h1", as_decision=True)
    assert d2.skip is False
    assert "not accepted" in d2.reason.lower() or "failed" in d2.reason.lower()


# --------------------------------------------------------------------------- #
# Pooled build budget — a build-level token POOL + retained per-story cap        #
# --------------------------------------------------------------------------- #
def test_build_budget_default_pool_sized_from_story_count(monkeypatch):
    # No env override: the pool defaults to story_count * STORY_MAX_TOKENS, and the
    # retained per-story cap stays STORY_MAX_TOKENS.
    monkeypatch.delenv("BUILD_TOKEN_POOL", raising=False)
    monkeypatch.delenv("STORY_MAX_TOKENS", raising=False)
    b = build_budget_from_env(story_count=3)
    assert b.max_pool_tokens == 3 * DEFAULT_STORY_MAX_TOKENS
    assert b.per_story_max_tokens == DEFAULT_STORY_MAX_TOKENS


def test_build_budget_pool_override_from_env(monkeypatch):
    monkeypatch.setenv("BUILD_TOKEN_POOL", "12345")
    monkeypatch.setenv("STORY_MAX_TOKENS", "7000")
    b = build_budget_from_env(story_count=10)
    assert b.max_pool_tokens == 12345
    assert b.per_story_max_tokens == 7000


def test_build_budget_bad_pool_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("BUILD_TOKEN_POOL", "not-a-number")
    monkeypatch.delenv("STORY_MAX_TOKENS", raising=False)
    b = build_budget_from_env(story_count=2)
    assert b.max_pool_tokens == 2 * DEFAULT_STORY_MAX_TOKENS


def test_build_budget_zero_story_count_pool_is_non_negative(monkeypatch):
    monkeypatch.delenv("BUILD_TOKEN_POOL", raising=False)
    monkeypatch.delenv("STORY_MAX_TOKENS", raising=False)
    b = build_budget_from_env(story_count=0)
    assert b.max_pool_tokens == 0
    # A zero/empty pool is exhausted immediately (no headroom to spawn new attempts).
    assert b.pool_exhausted(tokens_used=0) is True


def test_build_budget_pool_exhausted_predicate():
    b = BuildBudget(max_pool_tokens=1000, per_story_max_tokens=500)
    assert b.pool_exhausted(tokens_used=0) is False
    assert b.pool_exhausted(tokens_used=999) is False
    assert b.pool_exhausted(tokens_used=1000) is True   # at-limit: no headroom left
    assert b.pool_exhausted(tokens_used=1001) is True


def test_build_budget_non_positive_pool_disables_pool_gate_except_zero():
    # A NEGATIVE pool means "no pool cap" (operator opt-out), like the per-story gates.
    b = BuildBudget(max_pool_tokens=-1, per_story_max_tokens=500)
    assert b.pool_exhausted(tokens_used=10_000_000) is False


def test_build_budget_yields_per_story_budget_with_retained_cap():
    # The pooled budget hands out a per-story StoryBudget whose token cap is the
    # retained per-story cap — so a single story can never exceed it.
    b = BuildBudget(max_pool_tokens=10_000, per_story_max_tokens=500,
                    per_story_wall_s=42.0, per_story_repair_attempts=3)
    sb = b.story_budget()
    assert isinstance(sb, StoryBudget)
    assert sb.max_tokens == 500
    assert sb.max_wall_s == 42.0
    assert sb.max_repair_attempts == 3
    assert sb.tokens_exceeded(501) is True


# --------------------------------------------------------------------------- #
# BUILD_MAX_STORY_ATTEMPTS — the outer repeat-until-done attempt cap            #
# --------------------------------------------------------------------------- #
def test_build_max_story_attempts_default(monkeypatch):
    monkeypatch.delenv("BUILD_MAX_STORY_ATTEMPTS", raising=False)
    assert build_max_story_attempts() == DEFAULT_BUILD_MAX_STORY_ATTEMPTS == 3


def test_build_max_story_attempts_override(monkeypatch):
    monkeypatch.setenv("BUILD_MAX_STORY_ATTEMPTS", "5")
    assert build_max_story_attempts() == 5


def test_build_max_story_attempts_clamped_to_at_least_one(monkeypatch):
    # A non-positive / bad value must never let the outer loop run zero passes.
    monkeypatch.setenv("BUILD_MAX_STORY_ATTEMPTS", "0")
    assert build_max_story_attempts() == 1
    monkeypatch.setenv("BUILD_MAX_STORY_ATTEMPTS", "-4")
    assert build_max_story_attempts() == 1
    monkeypatch.setenv("BUILD_MAX_STORY_ATTEMPTS", "not-a-number")
    assert build_max_story_attempts() == DEFAULT_BUILD_MAX_STORY_ATTEMPTS
