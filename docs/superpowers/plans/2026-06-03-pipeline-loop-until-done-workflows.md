# Pipeline Loop-Until-Done + Build/Verify Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every pipeline stage robust on large codebases — no fixed 300s timeout cliff, "loop until done" generation, always re-triggerable (fresh restart) without wedging — and turn **build** and **verify** into Fan-Out-and-Synthesize + Repeat-Until-Done workflows (per "A harness for every task": claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code).

**Architecture:** A shared retry-with-escalation primitive under the bounded structured call; remove outer hard-timeout walls and fixed round caps in favor of per-unit budgets + loop-until-coverage-complete-or-no-progress; stale-job recovery so a wedged run never blocks a re-trigger; build = dependency-wave parallel fan-out + repeat-until-done with pass-with-deferred; verify = per-story fan-out + synthesize verdict + decompose-further + LLM repair, persisted as a versioned artifact with a GET.

**Tech Stack:** `enrichment/base.py` (bounded structured call), `controlplane/jobs.py` (JobRunner), `backlog/generator.py` + `technical_design/generator.py` (already decomposed), `codegen/story_runner.py`/`build_stories.py`/`budget.py` (build), `equivalence/lab.py` + `controlplane/verify.py` (verify), `codegen/patch_agent.py` (reused for verify LLM repair), Neo4j/SQLAlchemy artifact stores, Next.js cockpit, pytest with stub runners.

**User rulings (locked):** (1) Re-trigger = **always restart fresh** (no cross-run resume; just don't wedge). (2) Timeouts = **hybrid** — decompose-on-timeout for build+verify, retry-with-escalation + generous budgets for backlog+tech-design. (3) Verify = **full + LLM repair**. (4) Build failed story = **pass-with-deferred**. Defaults: golden masters stay bring-your-own (verify runs when supplied); build budget = **pooled with a per-story cap** (hybrid).

---

## Audit baseline (what's already satisfied — do NOT redo)

- **Re-trigger already works on all 8 stages** from the UI (run buttons never disabled; `jobs.runner` only blocks `running→running`; artifacts auto-version `max+1`; GET loads latest). Blueprint, seams, plan, domain, technical-design need NO re-trigger change.
- Backlog + technical_design are already decomposed (Fan-Out-and-Synthesize + per-epic/per-context); they need the timeout/round-cap cliffs removed, not a rewrite.
- Build already resumes within a run via `context_hash`; it is **sequential + one-pass** and needs fan-out + repeat-until-done.
- The likely reason re-trigger *felt* broken: a job stuck in `running` (backend killed mid-job / an uncaught 300s timeout) wedges the stage — fixed by Task 2.

---

## Phase 1 — Shared resilience primitive

### Task 1: Retry-with-escalation in the bounded structured call

**Files:**
- Modify: `src/cobol_modernizer/enrichment/base.py`
- Test: `tests/unit/test_enrichment_base_result.py` (extend)

- [ ] **Step 1: Write failing tests.** Add an optional retry to `run_batched_result(..., attempts: int = 1, escalate: bool = True)`:
  - `attempts=1` (default) → today's behavior exactly (one call, no retry) — assert byte-compatible.
  - On a `timeout` or empty-payload-with-`hit_turn_cap` cause AND `attempts>1`: re-issue the call with ESCALATED `timeout_s` and `max_turns` (e.g. ×1.5 each per attempt), up to `attempts` total, returning the first `ok=True` result; if all fail, return the typed failure (never raise — preserve the `{}`-on-final-failure contract).
  - A non-retryable failure (e.g. `error: <type>` that isn't timeout/turn-cap) does NOT retry (fail fast).
  - `run_batched` (bare-dict) keeps `attempts=1` semantics unchanged (non-gating enrichers unaffected).
  Use a stub runner that fails the first N calls then succeeds; assert call count + escalated args.

- [ ] **Step 2: Implement.** Wrap the existing single-call body in a bounded loop; escalate `timeout_s`/`max_turns` per attempt; reuse the existing cause classification. Keep `EnrichmentResult` shape. Document that escalation is the shared "loop a bit harder before giving up" mechanism every fan-out unit inherits.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_enrichment_base_result.py -q`

---

### Task 2: Stale-job recovery (re-trigger never wedges)

**Files:**
- Modify: `src/cobol_modernizer/controlplane/jobs.py`
- Test: `tests/unit/test_controlplane_jobs.py` (create if absent; else extend)

- [ ] **Step 1: Write failing tests.** `jobs.runner.start(kind, wid, fn)` currently returns the existing job if one is `running` for `(kind, wid)`, blocking re-trigger. Add stale detection: a job whose `status=="running"` but whose `started_at` is older than `JOB_STALE_AFTER_S` (env, default e.g. 1800) OR whose worker thread is no longer alive is treated as **dead** — `start` supersedes it (marks the stale one `failed` with a "superseded/stale" error and queues fresh). A genuinely-live running job still blocks (no double-run). Test: stale running job → re-trigger starts fresh; live running job → re-trigger returns the live one.

- [ ] **Step 2: Implement.** Track thread liveness (the runner already holds the worker) and/or `started_at` age; on `start`, if the prior job is stale/dead, reset it and proceed. Log the supersession. Keep the one-live-job-per-workspace guarantee.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_controlplane_jobs.py -q`

---

## Phase 2 — Kill the 300s cliffs (backlog + technical design)

### Task 3: Backlog — uncapped completeness loop + per-unit budgets

**Files:**
- Modify: `src/cobol_modernizer/backlog/generator.py`, `src/cobol_modernizer/controlplane/backlog.py`
- Test: `tests/unit/test_backlog_generator.py` (extend)

- [ ] **Step 1: Write failing tests.** The orchestrator's completeness loop currently exits at `BACKLOG_MAX_ROUNDS` (default 3). Change exits to: full coverage OR `N` consecutive no-progress rounds (`BACKLOG_NO_PROGRESS_ROUNDS`, default 2), with `BACKLOG_MAX_ROUNDS` raised to a large *safety* bound (default 100, not a normal stop). Each per-epic/per-round call uses the Task-1 retry-with-escalation (`attempts` from `BACKLOG_UNIT_ATTEMPTS`, default 2). Tests: a slow-but-progressing fixture covers everything across many rounds (not stopped at 3); a no-progress fixture stops after `BACKLOG_NO_PROGRESS_ROUNDS`; a per-unit timeout on round 1 retries (escalated) and still completes.

- [ ] **Step 2: Implement.** Replace the round-cap exit; thread `attempts`/`escalate` into the `generate_epics`/`generate_stories_for_epic` calls via `run_batched_result`. In `controlplane/backlog.py`, the outer `BACKLOG_TIMEOUT_S=300` `asyncio.wait_for`/budget must NOT cap the whole loop — bound per-unit, not the whole job (the JobRunner already lets a long job run). Keep fail-loud only when the epics call itself produces nothing.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_backlog_generator.py tests/integration/test_controlplane_backlog_api.py -q`

---

### Task 4: Technical design — per-context budgets + retry, no outer wall

**Files:**
- Modify: `src/cobol_modernizer/technical_design/generator.py`, `src/cobol_modernizer/controlplane/technical_design.py`
- Test: `tests/unit/test_technical_design_generator.py` (extend)

- [ ] **Step 1: Write failing tests.** Replace the single outer `TECHNICAL_DESIGN_TIMEOUT_S=300` wall with per-context budgets (`TECH_DESIGN_CONTEXT_TIMEOUT_S` already exists) so the outer wall can't kill a partially-complete design. Each per-context call uses Task-1 retry-with-escalation (`TECH_DESIGN_UNIT_ATTEMPTS`, default 2). A context that times out retries (escalated) ONCE before being skipped/falling back. Tests: a per-context timeout retries then succeeds; all-contexts-fail still yields the deterministic fallback (existing contract preserved).

- [ ] **Step 2: Implement.** Thread `attempts`/`escalate` into `generate_service_for_context`; remove the outer `asyncio.wait_for(300)` cap in favor of per-context budgets; keep the deterministic fallback + typed cause.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_technical_design_generator.py tests/integration/test_controlplane_technical_design_api.py -q`

---

## Phase 3 — Build as a Fan-Out-and-Synthesize + Repeat-Until-Done workflow

### Task 5: Dependency-wave parallel fan-out

**Files:**
- Modify: `src/cobol_modernizer/codegen/story_runner.py` (`run_story_plan`)
- Modify: `src/cobol_modernizer/controlplane/build_stories.py` (`_real_story_build_step`)
- Test: `tests/unit/test_story_runner.py` (extend)

- [ ] **Step 1: Write failing tests.** `run_story_plan` is a sequential `for item in items` loop. Group items into dependency WAVES (wave 0 = no unmet deps; wave k = deps all in waves < k) and run each wave's stories via `asyncio.gather` (bounded by `BUILD_MAX_CONCURRENCY`, default 4), each with its OWN `SdkAgentRunner` (no token/cost crosstalk). `completed_summaries` is computed from PRIOR waves only (a wave's stories don't see each other's). Tests: a 3-wave plan runs wave-by-wave; within-wave stories run concurrently (semaphore-bounded; assert max in-flight); a story only starts after its deps' wave completes; ordering/merge still feeds the deterministic DAG.

- [ ] **Step 2: Implement.** Wave-group from `depends_on`; per-wave `asyncio.gather` under a semaphore; per-wave completed-summaries; preserve per-story persistence + telemetry + the gate logic. Keep `run_story` unchanged (the unit).

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_story_runner.py -q`

---

### Task 6: Repeat-until-done + pass-with-deferred + pooled budget

**Files:**
- Modify: `src/cobol_modernizer/codegen/story_runner.py`, `src/cobol_modernizer/codegen/budget.py`, `src/cobol_modernizer/codegen/story_plan.py` (status enum)
- Test: `tests/unit/test_story_runner.py`, `tests/unit/test_story_codegen_budget.py` (extend)

- [ ] **Step 1: Add the `deferred` status.** Add `StoryCodegenStatus.deferred` (value `"deferred"`) — a story that exhausted its per-story retry/repair budget without being accepted, but isn't a hard error. Update `ACCEPTED_STORY_STATUSES`? NO — deferred is NOT accepted, but it must NOT wedge the build (see Task 7 gate). Keep `passed`/`generated-unverified`/`skipped` accepted.

- [ ] **Step 2: Repeat-until-done loop.** Wrap the wave pass (Task 5) in an outer `while`: after a full pass, collect `failed` stories, rebuild their context packs, and re-run ONLY those; loop until all accepted OR a pass yields no newly-accepted story (no-progress) OR the pooled budget is exhausted. A story that stays `failed` after `BUILD_MAX_STORY_ATTEMPTS` (default 3) passes → mark `deferred`. Tests: a story failing pass 1 but passing pass 2 → final accepted; a permanently-failing story → `deferred` after the attempt bound, loop terminates (no infinite loop), other stories unaffected.

- [ ] **Step 3: Pooled budget (hybrid).** Change `budget.py` from per-story isolated 200k to a build-level pool (`BUILD_TOKEN_POOL`, default sized from story count) with a per-story cap (`STORY_MAX_TOKENS` retained) — a story can't exceed its cap, but the build stops spawning new attempts when the pool is exhausted. Tests: pool exhaustion stops further attempts (no runaway); a single story can't exceed its per-story cap.

- [ ] **Step 4: Verify.** `uv run pytest tests/unit/test_story_runner.py tests/unit/test_story_codegen_budget.py -q`

---

### Task 7: Build gate (pass-with-deferred) + restart-fresh re-trigger

**Files:**
- Modify: `src/cobol_modernizer/controlplane/build_stories.py` (`_gate_stage`, `run_story_build`), `src/cobol_modernizer/controlplane/build.py`
- Test: `tests/integration/test_controlplane_story_build_api.py`, `tests/integration/test_controlplane_build_api.py` (extend)

- [ ] **Step 1: Pass-with-deferred gate.** `_gate_stage` marks the build `passed` when every story is in {`passed`,`generated-unverified`,`skipped`,`deferred`} AND at least one is genuinely built — i.e. `deferred` stories do NOT fail the gate, but the status artifact MUST expose `pass_count`/`deferred_count`/`pending` so the operator sees real progress. A `failed`/`error` story (distinct from `deferred`) still fails the gate. Tests: a run with some `deferred` stories → gate `passed` with deferred surfaced; a run with a true `error` story → gate fails.

- [ ] **Step 2: Restart-fresh re-trigger.** Per the ruling, a re-trigger (POST /build or POST /build/stories) regenerates ALL stories fresh — do NOT skip via cross-run `context_hash`. Make the within-RUN dedup explicit (don't regenerate a story already accepted *in this run*'s repeat loop) but a NEW trigger starts a NEW run that ignores prior runs' accepted state. Add `BUILD_RESUME=0` default (fresh) with an optional `force`/resume flag reserved for later. Tests: two sequential POSTs both regenerate fully (the second doesn't skip everything as already-done).

- [ ] **Step 3: Verify.** `uv run pytest tests/integration/test_controlplane_story_build_api.py tests/integration/test_controlplane_build_api.py -q`

---

### Task 8: Build cockpit — waves, deferred, progress

**Files:**
- Modify: `web/src/components/screens/StoryBuildLab.tsx`, `web/src/lib/api.ts`
- Test: `web/src/components/screens/StoryBuildLab.test.tsx` (extend)

- [ ] **Step 1: Render the workflow progress.** Show dependency waves, per-story status incl. the new `deferred` (distinct colour, e.g. slate/amber-outline), pass-count / deferred-count / pending, and attempts-per-story. A "force full rebuild" affordance is optional (reserved). Add the new status fields to the api types.

- [ ] **Step 2: Verify.** `cd web && npm run test -- StoryBuildLab && npx tsc --noEmit`

---

## Phase 4 — Verify as a Fan-Out-and-Synthesize + Repeat-Until-Done workflow (+ LLM repair)

### Task 9: Async equivalence + versioned persisted report + GET

**Files:**
- Modify: `src/cobol_modernizer/equivalence/lab.py` (make `run_equivalence` async-wrappable), `src/cobol_modernizer/controlplane/verify.py`
- Create: a `verify` storage helper (Artifact kinds `verify_report`, `equivalence_check`)
- Test: `tests/integration/test_controlplane_verify_api.py` (create/extend), `tests/unit/test_equivalence_lab.py` (extend)

- [ ] **Step 1: Persist + GET (closes verify's re-trigger gap).** Today verify is synchronous, persists no versioned artifact, has no GET, and the verdict is lost on refresh. Persist `Artifact(kind="verify_report", version=max+1, evidence_map={per_story_verdicts, defect_summary, coverage})` and add `GET /api/workspaces/{wid}/verify/status` returning the latest. Tests: a verify run persists a versioned report; GET loads the latest; a second run bumps the version.

- [ ] **Step 2: Make equivalence async-wrappable.** Wrap `run_equivalence` so it can run under `asyncio.gather` with a per-unit soft timeout (Task 10). Keep the existing synchronous single-slice path working.

- [ ] **Step 3: Verify.** `uv run pytest tests/integration/test_controlplane_verify_api.py tests/unit/test_equivalence_lab.py -q`

---

### Task 10: Per-story fan-out + soft timeout + synthesized verdict

**Files:**
- Modify: `src/cobol_modernizer/controlplane/verify.py`
- Test: `tests/integration/test_controlplane_verify_api.py` (extend)

- [ ] **Step 1: Fan out per story.** If a backlog exists, fan out equivalence + story_behavior PER STORY (each story's ACs cite different COBOL seams) via `asyncio.gather` (bounded by `VERIFY_MAX_CONCURRENCY`, default 4); else fall back to the single `slice_name`. Each check wrapped with a SOFT `VERIFY_EQUIVALENCE_TIMEOUT_S` (default ~60s) using the `EnrichmentResult`-style ok/cause pattern — on overrun return a partial sub-verdict, NOT a hard kill. Persist `Artifact(kind="equivalence_check", story_id, version, evidence_map={verdict, defect_count, defects_json})` per story.

- [ ] **Step 2: Synthesize.** Workspace passes iff all stories pass equivalence AND story_behavior; upsert the `equivalence` + `story_behavior` gates (`gates_util.upsert_gate`, keeping human-resolved gates immutable); roll the per-story sub-verdicts into the `verify_report`. Tests: a 3-story fan-out with one failing → workspace fails, per-story verdicts persisted; a soft-timeout story → partial verdict, not a crash.

- [ ] **Step 3: Verify.** `uv run pytest tests/integration/test_controlplane_verify_api.py -q`

---

### Task 11: Decompose-further repeat-until-done

**Files:**
- Modify: `src/cobol_modernizer/controlplane/verify.py`, `src/cobol_modernizer/equivalence/lab.py`
- Test: `tests/integration/test_controlplane_verify_api.py` (extend)

- [ ] **Step 1: Decompose-further loop.** For each failing/timed-out story, split its `candidate_records` per program/context and re-run equivalence on narrower sub-slices to localize defects (`VERIFY_DECOMPOSE_FURTHER=1`); a parent passes iff all sub-verdicts pass. Bound by `VERIFY_MAX_REPAIR_ATTEMPTS` (default 2) and stop on no-progress (loop-until-done, never a hard timeout kill). Tests: a story failing whole but passing all sub-slices → localizes which sub-slice actually fails; the loop terminates on no-progress/attempt-bound.

- [ ] **Step 2: Verify.** `uv run pytest tests/integration/test_controlplane_verify_api.py -q`

---

### Task 12: LLM-driven repair of failing Java (reuse the codegen patch agent)

**Files:**
- Create: `src/cobol_modernizer/controlplane/verify_repair.py` (or extend verify.py) + endpoint `POST /api/workspaces/{wid}/verify/repair/{story_id}`
- Modify: reuse `src/cobol_modernizer/codegen/patch_agent.py` / `repair_loop.py`
- Test: `tests/integration/test_controlplane_verify_api.py` (extend)

- [ ] **Step 1: Repair contract.** On a confirmed equivalence defect for a story (the COBOL oracle and Java disagree), feed the failing AC + the defect (expected vs actual) + the current Java + the story context pack into the EXISTING `patch_agent.generate_story_implementation` (repair_feedback shape) to regenerate the Java for that story, write it into the scaffolded module, and re-run equivalence (bounded by `VERIFY_MAX_REPAIR_ATTEMPTS`). This is the repeat-until-done loop closing the green/red gap with code regeneration, not just localization. Requires golden-master records (bring-your-own — 409 clearly if absent). Tests (stubbed patch agent + stubbed equivalence): a defect → repair regenerates Java → re-run passes → report updated; repair exhausts attempts → story stays failed with the defect surfaced.

- [ ] **Step 2: Verify.** `uv run pytest tests/integration/test_controlplane_verify_api.py -q`

---

### Task 13: Verify cockpit — per-story verdicts, defects, lazy-load, repair

**Files:**
- Modify: `web/src/components/screens/EquivalenceLab.tsx`, `web/src/lib/api.ts`
- Test: `web/src/components/screens/EquivalenceLab.test.tsx` (extend)

- [ ] **Step 1: Render the verify workflow.** Lazy-load the latest persisted `verify_report` on mount (today the verdict is transient/lost on refresh); render per-story verdicts + defect counts + sub-slice localization; a "repair" action per failing story (POST .../verify/repair/{story_id}); re-run always available. Add the new api types/endpoints.

- [ ] **Step 2: Verify.** `cd web && npm run test -- EquivalenceLab && npx tsc --noEmit`

---

## Acceptance Criteria

- [ ] No stage hard-fails at a fixed 300s wall: backlog/tech-design bound per-unit + retry-with-escalation; build/verify decompose-on-timeout; large codebases run to completion ("loop until done").
- [ ] Backlog completeness loop runs until coverage-complete or genuine no-progress (not a fixed round cap).
- [ ] A wedged/stale `running` job no longer blocks a re-trigger.
- [ ] Re-trigger of any stage restarts fresh (new version), and the UI run button is always available.
- [ ] Build runs stories in dependency-wave parallel fan-out, repeats until all accepted or no-progress, passes-with-deferred (one bad story never wedges the build), under a pooled budget with a per-story cap.
- [ ] Verify fans out per story, synthesizes a workspace verdict, decomposes-further to localize defects, repairs failing Java via the codegen patch agent (when golden masters are supplied), and persists a versioned `verify_report` loadable via GET + the cockpit.
- [ ] Full suite green after each phase: `uv run pytest tests/unit tests/integration -q` (JDK25 env, excluding the pre-existing Docker/Neo4j-testcontainer tests) + `cd web && npm run test && npx tsc --noEmit`.

## Non-Goals

- Do NOT add cross-run RESUME (the ruling is restart-fresh); a `force`/resume flag is reserved but unbuilt.
- Do NOT build a golden-master capture stage (bring-your-own oracle stays; verify 409s clearly without records).
- Do NOT touch the already-robust deterministic stages (seams, plan) or the already-satisfied re-trigger paths (blueprint/domain/tech-design UI).
- Do NOT introduce caps/truncation on any artifact (the no-cap invariant from the prior plan holds).

## Implementation Order

1. Retry-with-escalation primitive (Task 1) — force multiplier.
2. Stale-job recovery (Task 2) — unblocks re-trigger.
3. Backlog cliffs (Task 3), Technical-design cliffs (Task 4) — directly retire the named 300s walls.
4. Build workflow (Tasks 5–8) — highest user value.
5. Verify workflow (Tasks 9–13) — largest net-new; verify persistence (Task 9) alone closes verify's re-trigger gap early.
