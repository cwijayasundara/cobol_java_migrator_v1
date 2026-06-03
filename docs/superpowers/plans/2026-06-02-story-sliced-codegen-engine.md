# Story-Sliced Codegen Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make COBOL-to-Spring-Boot code generation reliable and efficient for larger codebases such as `source_code_to_analyse/aws-mf-mod-carddemo` by replacing the current one-shot code dump (`codegen/generator.py::generate_slice`) with a deterministic scaffold plus a story-by-story coding loop driven by BRD, backlog, DDD, technical design, COBOL graph evidence, compiler feedback, and acceptance tests.

**Architecture:** Treat BRD/backlog/DDD/technical design as the product specification and the COBOL graph as evidence. Generate the Spring Boot structure deterministically from the technical design, then process backlog stories in dependency order. Each story creates failing tests from acceptance criteria, applies a bounded Java patch, runs targeted Maven tests, repairs only failing files, and persists traceability from `story -> acceptance criteria -> COBOL refs -> generated tests/code -> verification`.

**Tech Stack:** FastAPI control-plane routers, Neo4j artifact store (specs), SQLAlchemy `Artifact`/gate tables (transactional codegen state), Pydantic schemas, the existing `SdkAgentRunner`, generated **Spring Boot 4.0.6 / Java 25** Maven projects, pytest, targeted `mvn -Dtest=… test` on the host (graceful-degrade when absent), Next.js cockpit.

---

## Decisions (locked)

These resolve the open design questions; the tasks below assume them.

1. **Compile/test oracle runs on the host, and degrades gracefully.** Per-story verification shells out to host `mvn -Dtest=… test`. If `mvn`/JDK 25 are absent or the toolchain is incompatible, the story is recorded as **`generated-unverified`** (NOT `failed`) and the loop continues. Compile feedback is the oracle *where the toolchain exists*; absence of a toolchain must never fail a build.
2. **Per-story status persists as a SQLAlchemy `Artifact`.** A new artifact kind `story_codegen_status` (one versioned row per workspace, payload keyed by `story_id`) mirrors the existing `generated_test_refs` pattern in `controlplane/build.py` and lives in the same transactional store as jobs/gates. The graph (Neo4j) keeps *specs* (backlog/design/technical design); transactional codegen state does NOT go into Neo4j.
3. **Generated projects target Spring Boot 4.0.6 / Java 25.** The existing `codegen/scaffold.py` pom is pinned to 3.3.4 and must be corrected as part of Task 2.

---

## Root-Cause Map — why codegen "still does not work" today

The current path is a single structured completion (`generate_slice`) run tool-free with a 2-turn budget (`build.py::_codegen_run_plan`). It surfaces failure as one of three modes. Each maps to the task that removes it:

| Current failure (observable) | Where it is raised | Removed by |
| --- | --- | --- |
| `codegen agent produced no output (likely hit the N-turn cap or errored)` — runner swallowed an error/turn-cap to `{}` | `generator.py:163` | Tasks 2+4+6 — deterministic scaffold means the LLM only writes bounded behavior per story; a single story failing no longer zeroes the whole run. |
| `codegen produced no failing test (TDD violated) after N repair attempts` | `generator.py:182` | Task 4 — tests are generated as a *separate, gated* step per story; a story cannot advance to implementation until each AC has an assertion. |
| Wall-clock timeout (`CODEGEN_TIMEOUT_S`, default 120s) on a large repo because one call owns the whole slice | `generator.py:134` / `_run_codegen_call` | Tasks 1+2+6 — work is split into per-story transactions, each with its own bounded timeout; large repos generate a plan without any LLM code call at all. |
| Generated code never compiles / is never run, so "passed" build is unverified | `build.py` deliberately skips `mvn verify` | Task 5 — targeted `mvn test` per story (host, degrade-if-absent). |

**Definition of "fixed" for this plan:** `carddemo-mini` builds story-by-story (no single whole-slice LLM call), every story's tests cite all its ACs, completed stories are not regenerated on retry, and `aws-mf-mod-carddemo` produces a story plan with zero LLM code calls. See Acceptance Criteria.

---

## Current Problem

The build stage already assembles a rich brief — BRD requirements, DDD domain design, backlog, technical design, and a pre-fetched, design-scoped slice source pack (`build.py::_codegen_brief`, `_slice_pack`) — and disables graph tools on the fast path. That part is good. The generator is still too coarse:

1. **One large agent call owns the whole slice.** `generate_slice` asks the model to emit all tests and all Java files as one JSON blob. That is not how Claude Code/Codex stay effective.
2. **No file-system edit loop.** The model does not incrementally inspect, patch, compile, test, and repair a real project.
3. **No story-level checkpointing.** A long run succeeds or fails as one unit; it cannot resume from the last accepted story.
4. **Technical design is consumed as context, not as a scaffold contract.** The scaffold should be generated deterministically from the technical design before the LLM writes behavior.
5. **Acceptance criteria are not the primary build unit.** Tests should be generated per story/AC, then production code should satisfy those tests.
6. **Cost attribution is too coarse.** Larger COBOL repos need per-story token/time/test telemetry. (`SdkAgentRunner` already accumulates `token_usage`/`cost_usd`/`calls`; nothing splits it per story.)

## Target Operating Model

Use this runtime chain:

```text
BRD
  -> backlog epics/stories/acceptance criteria/dependencies
  -> DDD contexts/aggregates/invariants
  -> technical design services/APIs/persistence/integrations
  -> deterministic Spring Boot scaffold
  -> story DAG execution:
       for each story in dependency order:
         build story context pack
         generate failing tests from ACs
         patch Java implementation
         run targeted tests (host mvn; degrade if absent)
         repair failing files
         persist traceability and gate result
```

The LLM is used for bounded behavioral implementation, not for Maven/Spring boilerplate or whole-project generation.

## Efficiency Principles

1. **Scaffold deterministically.** Generate Maven layout, packages, controllers, service shells, repositories, entities, DTOs, exception classes, and configuration from the technical design without an LLM. Shells MUST compile (TODO-bodied) so targeted `mvn test` works before any story runs.
2. **Generate one story at a time.** Story dependencies define order. A story is the smallest codegen transaction.
3. **Tests before code.** Every acceptance criterion must produce at least one JUnit assertion before implementation patches are accepted.
4. **Patch, do not dump.** The model returns a small patch / file-replacement set against the current project, not a full-project JSON blob.
5. **Compile feedback is the oracle — where it exists.** Targeted compile/tests per story; repair prompts include only failing output and touched files. Toolchain absence degrades to `generated-unverified`, never failure.
6. **Graph is evidence, not a chat tool.** Pre-materialize COBOL source snippets and graph facts into a story context pack (reuse the `_slice_pack` approach). Graph tool calls are fallback only.
7. **Reuse the modernization spine.** Do not reinvent DAG ordering, repair, traceability, telemetry, cost tiering, or scaffolding — extend what exists (see Reuse Inventory).
8. **Bound every loop.** Per-story timeout, max patch attempts, max touched files, max token budget, max compiler-log bytes.
9. **Persist every checkpoint.** Completed stories are not regenerated unless inputs change (`context_hash`).

## Reuse Inventory — existing code each task MUST build on

Do not duplicate these; import/extend them.

| Need | Existing code | Used by task |
| --- | --- | --- |
| Story dependency DAG / topological order | `backlog/dependency.py::derive_story_dependencies`, `BacklogDAG` | 1 |
| Story → service mapping | `TechnicalService.story_ids` (explicit link in `technical_design/schema.py`) — NOT heuristic context matching | 1, 3 |
| Maven module + quality-gate scaffold | `codegen/scaffold.py::scaffold_module` (fix SB version) | 2 |
| Design-scoped COBOL source prefetch | `build.py::_slice_pack`, `_target_refs` (cheap Cypher reads, char-budgeted, degrade to `''`) | 3 |
| Structured LLM call | `agent/harness.py::SdkAgentRunner.run_structured(system, prompt, server, allowed_tools, model, max_turns, schema, label)` | 4 |
| Tests-only repair precedent | `codegen/generator.py::_emit_tests_only`; gate-log repair `codegen/repair_loop.py::run_repair_loop` | 4, 6 |
| AC-citation traceability | `build.py::scan_generated_test_refs`, `_record_generated_test_refs`, artifact kind `generated_test_refs` (consumed by Verify's story-behavior gate) | 6 |
| Per-call telemetry | `SdkAgentRunner.token_usage`, `.cost_usd`, `.calls` | 6 |
| Model/turn tiering | `cost/scaling.py::model_for_size`, `turns_for` | 4 |
| Background job + one-job-per-workspace guard | `controlplane/jobs.py::runner.start(kind, wid, fn)` (keyed by `(kind, wid)`) | 7 |
| Router registration | `controlplane/__init__.py` `controlplane_router.include_router(...)` | 7 |

**Existing env knobs to reuse (do NOT introduce parallel `STORY_*` duplicates):** `CODEGEN_TIMEOUT_S`, `CODEGEN_INLINE_TURNS`, `CODEGEN_AGENT_MIN_TURNS`, `CODEGEN_AGENT_MAX_TURNS`, `CODEGEN_PACK_MAX_UNITS`, `CODEGEN_PACK_MAX_CHARS`, `CODEGEN_MODEL`, `CODEGEN_SMALL_TIER`, `CODEGEN_SMALL_UNITS`. New story-specific knobs are listed per task and should extend, not shadow, these.

## File Structure

Create focused modules under `codegen/` rather than expanding `controlplane/build.py`.

| File | Responsibility |
| --- | --- |
| `src/cobol_modernizer/codegen/story_plan.py` | Build `StoryCodegenPlan` from backlog DAG (`derive_story_dependencies`), DDD, technical design, and graph refs. |
| `src/cobol_modernizer/codegen/scaffold_from_design.py` | Deterministically generate the Spring Boot 4.0.6 skeleton from `TechnicalDesign` (reuses `scaffold_module`). |
| `src/cobol_modernizer/codegen/story_context.py` | Build compact per-story context packs (reuses `_slice_pack`): BRD requirements, ACs, DDD aggregate, technical service, COBOL evidence/source. |
| `src/cobol_modernizer/codegen/patch_agent.py` | Bounded LLM patch generation for tests and implementation (via `SdkAgentRunner`). |
| `src/cobol_modernizer/codegen/test_runner.py` | Build + run targeted Maven commands on the host; parse results; degrade if absent. |
| `src/cobol_modernizer/codegen/story_runner.py` | Orchestrate test generation, implementation, targeted Maven run, repair, and traceability persistence. |
| `src/cobol_modernizer/codegen/story_storage.py` | Persist per-story status/telemetry/touched-files/context-hash as `story_codegen_status` Artifact. |
| `src/cobol_modernizer/codegen/budget.py` | Per-story/-workspace budget + resume policy. |
| `src/cobol_modernizer/controlplane/build_stories.py` | Endpoints for plan/status/run-one/run-all story codegen. |
| `web/src/components/screens/StoryBuildLab.tsx` | UI for story DAG codegen progress and per-story verification. |

---

## Task 1: Define Story Codegen Plan

**Files:**
- Create: `src/cobol_modernizer/codegen/story_plan.py`
- Test: `tests/unit/test_story_codegen_plan.py`

- [ ] **Step 1: Write failing tests**

Test that a backlog DAG plus technical design produces ordered story work items with `story_id`, `bounded_context`, `service_name`, `acceptance_criteria_ids`, `cobol_refs`, and dependency IDs. Include a story with no matching `TechnicalService.story_ids` and assert it is marked `blocked`.

- [ ] **Step 2: Implement Pydantic models**

Models: `StoryCodegenItem`, `StoryCodegenPlan`, `StoryCodegenStatus` (enum: `pending`/`running`/`passed`/`failed`/`skipped`/`generated-unverified`/`blocked`).

- [ ] **Step 3: Implement planner**

`build_story_codegen_plan(backlog, domain_design, technical_design) -> StoryCodegenPlan`

Rules:
- Derive order from `derive_story_dependencies` / `BacklogDAG` (reuse — do not re-implement topological sort). Emit items in dependency-respecting order.
- Map story → service via `TechnicalService.story_ids` (explicit link). Fall back to `bounded_context` match only if `story_ids` is empty.
- Collect AC IDs from `UserStory.acceptance_criteria[].id`.
- Collect evidence refs from `story.evidence_refs`, DDD `cobol_mapping[].cobol_ref` (see `build.py::_target_refs`), and `TechnicalService.evidence_refs`.
- Mark stories `blocked` when no service/context mapping exists.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_story_codegen_plan.py -q`

---

## Task 2: Deterministic Spring Boot Scaffold From Technical Design

**Files:**
- Create: `src/cobol_modernizer/codegen/scaffold_from_design.py`
- Modify: `src/cobol_modernizer/codegen/scaffold.py` (correct SB version + factor reusable helpers)
- Test: `tests/unit/test_scaffold_from_design.py`

- [ ] **Step 1: Fix the scaffold version**

`scaffold.py` pom is pinned to Spring Boot `3.3.4`; the project standard is **4.0.6 / Java 25**. Update the pom (and the module docstring that says "3.3") and confirm existing `scaffold_module` tests still pass. This is a prerequisite — a 3.3.4 scaffold will not match the rest of the generated stack.

- [ ] **Step 2: Write failing tests**

Given a `TechnicalDesign` with two services, API contracts, persistence resources, and integrations, assert generated files include:
- `pom.xml` (via reused `scaffold_module`)
- application class
- controller shell per `ApiContract`
- service shell per `TechnicalService`
- repository/entity shell per `PersistenceDesign.resource`
- package names derived from repo slug + service name (reuse `build.py::_base_package` convention)
- **every shell compiles** (TODO-bodied methods that return defaults / throw `UnsupportedOperationException`), so targeted `mvn test` works before any story runs.

- [ ] **Step 3: Implement scaffold generator**

No LLM. Output predictable Java classes with `// TODO(story:<id> service:<name>)` markers linked to service/story IDs. Reuse `scaffold_module` for the Maven layout + quality gates; this module only adds the design-derived `.java` shells.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_scaffold_from_design.py -q`

---

## Task 3: Per-Story Context Pack

**Files:**
- Create: `src/cobol_modernizer/codegen/story_context.py`
- Test: `tests/unit/test_story_context.py`

- [ ] **Step 1: Write failing tests**

Assert the pack includes only:
- story title/body/ACs
- dependent completed story summaries
- mapped DDD aggregate/invariants/methods
- mapped technical service/API/persistence details
- relevant BRD requirements
- prefetched COBOL source snippets for evidence refs

- [ ] **Step 2: Implement context builder**

Reuse `build.py::_slice_pack` for the COBOL source prefetch (it is already design-scoped, char-budgeted, and degrades to `''`). Enforce byte limits:
- default `STORY_CONTEXT_MAX_CHARS=24000`
- default `STORY_SOURCE_MAX_CHARS=12000`

- [ ] **Step 3: Add stable hashing**

`context_hash` (sha256 over the normalized pack inputs) changes only when BRD/story/DDD/technical/COBOL evidence changes. This drives resume/cache (Task 10).

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_story_context.py -q`

---

## Task 4: Test-First Patch Agent

**Files:**
- Create: `src/cobol_modernizer/codegen/patch_agent.py`
- Test: `tests/unit/test_patch_agent.py`

- [ ] **Step 1: Define patch schema**

Reuse the shape of `generator.py::CODEGEN_SCHEMA` (`files[]` with `path`/`kind`/`content`/`evidence`) extended with `story_id`, `acceptance_criteria_ids`, `rationale`. Do not allow arbitrary shell commands. Tests use a stubbed `AgentRunner` (the `run_structured` Protocol in `agent/harness.py`) — no live LLM in unit tests.

- [ ] **Step 2: Implement `generate_story_tests`**

Inputs: story context pack, current project file index.
Output: JUnit tests only (`kind='test'`); every AC ID cited in comments or test names. Mirror `generator.py::_emit_tests_only`'s contract.

- [ ] **Step 3: Implement `generate_story_implementation`**

Inputs: story context pack, failing tests, relevant existing Java files.
Output: bounded file patches/replacements (`kind='main'`).

- [ ] **Step 4: Add timeout and cost controls**

Reuse `model_for_size`/`turns_for` for tiering. New story-scoped defaults (extend, don't shadow, existing knobs):
- `STORY_CODEGEN_TIMEOUT_S=90`
- `STORY_CODEGEN_MAX_TURNS=2`
- `STORY_REPAIR_MAX_ATTEMPTS=2`

- [ ] **Step 5: Verify**

Run: `uv run pytest tests/unit/test_patch_agent.py -q`

---

## Task 5: Targeted Maven Test Runner (host, degrade-if-absent)

**Files:**
- Create: `src/cobol_modernizer/codegen/test_runner.py`
- Test: `tests/unit/test_story_test_runner.py`

- [ ] **Step 1: Toolchain probe + degradation**

Detect host `mvn` and a JDK 25. If either is missing/incompatible, `run_targeted_tests` returns a `ToolchainUnavailable` result so the story runner records **`generated-unverified`** and continues. Tests assert the degraded path never raises.

- [ ] **Step 2: Implement command builder**

Build commands such as:

```bash
mvn -q -Dtest=TransactionPostingServiceTest test
```

Never run full `mvn verify` inside a story unless explicitly requested. Run an offline compile gate (`mvn -q -o -DskipTests compile`) first, because targeted `-Dtest=` requires the **whole module to compile** — one story's broken Java blocks sibling stories' tests. On compile failure, attribute the log to the just-touched files and route to repair before running tests.

- [ ] **Step 3: Parse results**

Return: compile passed/failed, test passed/failed, failing test names, bounded log excerpt (`STORY_MVN_LOG_MAX_BYTES`, default 8192). Parse from surefire output; tolerate missing reports.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_story_test_runner.py -q` (mock `subprocess`; no real Maven in unit tests).

---

## Task 6: Story Runner Orchestration

**Files:**
- Create: `src/cobol_modernizer/codegen/story_runner.py`
- Create: `src/cobol_modernizer/codegen/story_storage.py`
- Test: `tests/unit/test_story_runner.py`

- [ ] **Step 1: Implement lifecycle**

For each story (in plan order):
1. skip if completed and `context_hash` unchanged (Task 10 resume).
2. generate tests (Task 4) → write into the scaffold.
3. run targeted test → expect failure or compile gap (TDD red).
4. generate implementation (Task 4) → write/patch.
5. run targeted test (Task 5).
6. repair bounded failures (reuse the `repair_loop.py` pattern: feed only failing gate + log excerpt + touched files).
7. persist result.

- [ ] **Step 2: Enforce gates**

A story is **accepted** only if: every AC ID appears in generated tests (reuse `scan_generated_test_refs`), targeted tests pass, and generated files cite story ID + COBOL refs. When the toolchain is absent, AC-citation + lineage still gate, and the story is recorded `generated-unverified` (accepted-but-unverified) rather than `passed`.

- [ ] **Step 3: Persist telemetry + traceability**

`story_storage.py` writes a `story_codegen_status` Artifact (Decision 2) keyed by `story_id` with: wall time, model, token usage (`runner.token_usage` delta), cost (`runner.cost_usd` delta), attempts, changed files, test result, `context_hash`, status. Also extend the existing `generated_test_refs` recording so the Verify story-behavior gate keeps working unchanged.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_story_runner.py -q`

---

## Task 7: Control Plane API

**Files:**
- Create: `src/cobol_modernizer/controlplane/build_stories.py`
- Modify: `src/cobol_modernizer/controlplane/__init__.py` (`controlplane_router.include_router(_build_stories_router)`)
- Test: `tests/integration/test_controlplane_story_build_api.py`

- [ ] **Step 1: Add endpoints**

- `GET /api/workspaces/{wid}/build/story-plan`
- `POST /api/workspaces/{wid}/build/stories/{story_id}`
- `POST /api/workspaces/{wid}/build/stories`
- `GET /api/workspaces/{wid}/build/stories`

- [ ] **Step 2: Add fast prechecks**

Require BRD, backlog, domain design, technical design, and source repo (extend `build.py::_precheck`). Return 409 with the missing-stage name, matching existing precheck style.

- [ ] **Step 3: One-running-job guard**

Run story builds through `jobs.runner.start("build-stories", wid, fn)` — the runner already enforces one job per `(kind, wid)`. Do not hand-roll a lock.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/integration/test_controlplane_story_build_api.py -q`

---

## Task 8: Cockpit Story Build UI

**Files:**
- Create: `web/src/components/screens/StoryBuildLab.tsx`
- Modify: `web/src/components/screens/BuildLab.tsx`
- Modify: `web/src/lib/api.ts`
- Test: `web/src/components/screens/StoryBuildLab.test.tsx`

- [ ] **Step 1: Render story DAG build status**

Show: story ID/title, dependencies, status (`pending`/`running`/`passed`/`failed`/`skipped`/`generated-unverified`/`blocked`), AC coverage, touched files, test result, cost/time. Surface `generated-unverified` distinctly (e.g. amber) so users know the toolchain was absent.

- [ ] **Step 2: Add actions**

Buttons: Build next ready story, Build all ready stories, Retry failed story. Follow the existing MSW-mocked test pattern used by other screens.

- [ ] **Step 3: Verify**

Run: `cd web && npm run test -- StoryBuildLab.test.tsx`

---

## Task 9: Migration From Existing Build Endpoint

**Files:**
- Modify: `src/cobol_modernizer/controlplane/build.py`
- Modify: `web/src/components/screens/BuildLab.tsx`
- Test: `tests/integration/test_controlplane_build_api.py`, `tests/unit/test_codegen_generator.py`

- [ ] **Step 1: Keep legacy `POST /build` as a compatibility wrapper**

When `CODEGEN_MODE=story` (default), `POST /build` should: scaffold from technical design if needed, run story-build for the next ready story (or all stories per request flag), and return a summary compatible with the current UI (preserve `_mark_passed("build")` and the `generated_test_refs` recording so Verify is unaffected). `CODEGEN_MODE=legacy_slice` keeps the current `generate_slice` path for fallback/debug.

- [ ] **Step 2: Add explicit mode switch**

`CODEGEN_MODE=story` (default) / `CODEGEN_MODE=legacy_slice`. Keep `_generate_slice_graph` reachable under the legacy mode; do not delete it until the story path is proven on `carddemo-mini`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/integration/test_controlplane_build_api.py tests/unit/test_codegen_generator.py -q`

---

## Task 10: Large-Repo Cost and Resume Gates

**Files:**
- Create: `src/cobol_modernizer/codegen/budget.py`
- Test: `tests/unit/test_story_codegen_budget.py`

- [ ] **Step 1: Implement budget policy**

Per-story max tokens, per-story max wall time, per-workspace max concurrent story jobs (1, via `jobs.runner`), max repair attempts. Reuse `cost/scaling` tiering for model selection.

- [ ] **Step 2: Implement resume policy**

Skip a completed story when: story unchanged, `context_hash` unchanged, and generated tests still pass (or were `generated-unverified` and inputs unchanged). Read prior state from the `story_codegen_status` Artifact.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/test_story_codegen_budget.py -q`

---

## Acceptance Criteria

- [ ] `carddemo-mini` generates Spring Boot code story-by-story with no single whole-slice LLM call (legacy `generate_slice` not invoked under `CODEGEN_MODE=story`).
- [ ] `aws-mf-mod-carddemo` produces a story plan (Task 1) without invoking an LLM for code.
- [ ] Each story's tests cite all its acceptance criteria (verified via `scan_generated_test_refs`).
- [ ] Each story persists traceability to BRD, DDD, technical design, and COBOL refs in the `story_codegen_status` Artifact.
- [ ] A failed story can be retried without regenerating completed stories (resume via `context_hash`).
- [ ] Per-story token/time/test telemetry is visible in the cockpit.
- [ ] Where Maven/JDK 25 is present, targeted `mvn test` runs per story; where absent, stories record `generated-unverified` and the build still completes.
- [ ] Default codegen path has hard timeouts and bounded repair loops.

## Non-Goals

- Do not build a COBOL-to-Java line-by-line transpiler.
- Do not generate a full enterprise app in one LLM response.
- Do not trust generated code without targeted tests (where the toolchain exists).
- Do not let the LLM invent behavior absent from BRD/story/DDD/technical/COBOL evidence.
- Do not move transactional codegen state into Neo4j (it stays in the SQLAlchemy `Artifact` store).

## Implementation Order

Front-load a runnable vertical slice so value lands before the UI:

1. Story codegen plan (Task 1).
2. Deterministic scaffold from technical design, incl. SB-version fix (Task 2).
3. Per-story context pack (Task 3).
4. Test-first patch agent (Task 4).
5. Targeted Maven runner (Task 5).
6. Story runner + storage (Task 6). **← runnable checkpoint:** drive one story end-to-end on `carddemo-mini` behind `CODEGEN_MODE=story` via a throwaway script before building API/UI.
7. Control-plane API (Task 7).
8. Cockpit UI (Task 8).
9. Legacy build compatibility wrapper (Task 9).
10. Large-repo budget/resume gates (Task 10).
