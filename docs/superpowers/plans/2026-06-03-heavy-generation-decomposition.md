# Heavy-Generation Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop heavy LLM artifact generators (backlog, technical design) from timing out / returning `{}` → 502 on large COBOL repos, by replacing the single unbounded mega-call with bounded, decomposed SDK orchestration (a deterministic map-reduce over small `run_batched` calls) — **without capping or truncating any artifact (BRD, backlog, DDD, design, or code) or dropping any relevant evidence.**

**Architecture:** Three layers, applied first to backlog then generalized to technical design. (1) **Scope inlined evidence by RELEVANCE, never by a numeric cap** — the current bug is dumping *every* repo ref into one prompt; the fix is to inline only the refs a unit's BRD requirements actually cite (lossless: nothing relevant is dropped, nothing irrelevant is dumped). Call size is bounded by decomposition, not by truncation. (2) **Decompose the one-shot output** — generate epics, then stories-per-epic in bounded parallel SDK calls each with its own timeout/turn budget, then run the *already-deterministic* dependency DAG as the reduce. Decomposition is what lets output be arbitrarily large and complete (more epics/stories across more calls) instead of squeezed into one call. (3) **Fail loud, not empty** — surface the concrete cause (timeout / turn-cap / parse / api-error) instead of a bare `{}`. This mirrors the just-shipped story-sliced codegen engine (`codegen/story_runner.py` + `patch_agent.py`) and the patterns already used by `domain/tactical.py` (`asyncio.gather` per context) and `brd/pipeline.py` (size-aware fan-out).

**No-cap principle (hard constraint):** Nothing in this plan truncates a generated artifact or the count of epics/stories/ACs/code, and nothing drops a *relevant* graph ref to hit a number. The whole-graph dump is removed by *relevance partitioning* + *decomposition*, not by a length limit. There is no `*_MAX_REFS`, no `[:N]` truncation, no output cap. Per-call timeouts remain only as safety nets (they should never fire once a call is properly scoped); they bound a hung call, not the size of a result.

**Tech Stack:** `enrichment/base.py::run_batched` (the bounded structured-output primitive over `SdkAgentRunner.run_structured`), Pydantic backlog/technical-design schemas, Neo4j artifact store, FastAPI control-plane routers, `asyncio.gather` for bounded fan-out, pytest with stub runners.

---

## Confirmed root causes (from the diagnosis workflow)

1. **DOMINANT — unbounded graph inlining.** `controlplane/backlog.py:89` runs `_GRAPH_REFS_Q` (every `CodeEntity.qualified_name`, no LIMIT) and `backlog/generator.py:138` inlines `json.dumps(known_refs)` verbatim (~2k–4k refs ≈ 11k tokens for `aws-mf-mod-carddemo`). The model must reason over the whole repo surface. **Backlog is the unbounded outlier — `technical_design` already caps the analogous list at `[:200]` (`controlplane/technical_design.py:107`).**
2. **DOMINANT — one-shot mega-output.** `backlog/generator.py:145` makes ONE `run_batched` call emitting all epics + all stories + all ACs under a single 300s global timeout. No partial progress; one slow pass zeroes the stage. `asyncio.wait_for` fires → `{}` (`enrichment/base.py:25`).
3. **CONTRIBUTING — fail-empty, not fail-loud.** `run_batched` swallows timeout/turn-cap/parse/api-error to a bare `{}` (`base.py:25-30`); `run_backlog` turns that into a generic 502 (`backlog.py:102-107`) that hides which it was.
4. **MINOR — `max_turns=6`** can be hit on heavy reasoning, also → `{}` (relieved by scoping + decomposition).

**At risk (same shape):** `technical_design/generator.py` (HIGH — partially mitigated by its 200-cap + fallback). `enrichment/{seams,design,plan}.py` (LOW — non-gating, degrade gracefully, out of scope). **Already robust (do not touch):** `codegen/*` (per-story loop), `domain/tactical.py` (`gather` per context), `brd/pipeline.py` (size-aware fan-out).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/cobol_modernizer/enrichment/refs.py` (new) | Deterministic, pure `relevant_refs(scope, known_refs)` — selects the refs a given scope (BRD sections, or one epic's requirement subset) actually cites. Lossless, NO numeric cap/truncation. Shared by every heavy generator. |
| `src/cobol_modernizer/enrichment/base.py` (modify) | Add a typed-cause result (`EnrichmentResult` / `run_batched_result`) alongside the existing `{}`-returning `run_batched` (keep the silent-degrade path for non-gating enrichers). |
| `src/cobol_modernizer/backlog/generator.py` (modify) | Split the mega-schema into `EPICS_SCHEMA` + `STORIES_SCHEMA`; add `generate_epics` and `generate_stories_for_epic`; turn `generate_backlog_payload` into the map-reduce orchestrator. |
| `src/cobol_modernizer/controlplane/backlog.py` (modify) | Pass *scoped* refs to the prompt, keep *full* refs for grounding; surface the typed cause in the 502. |
| `src/cobol_modernizer/technical_design/generator.py` + `controlplane/technical_design.py` (modify) | Replace the inline `[:200]` with the shared `relevant_refs`; surface typed cause; decompose per bounded-context where it fits. |
| `tests/unit/test_enrichment_refs.py`, `tests/unit/test_enrichment_base_result.py`, `tests/unit/test_backlog_generator.py` (new/extend), `tests/integration/test_controlplane_backlog_api.py` (extend), `tests/unit/test_technical_design_generator.py` (extend) | Tests. |

**Env knobs (new, documented in code):** `BACKLOG_EPIC_TIMEOUT_S` (default 120), `BACKLOG_STORY_TIMEOUT_S` (default 120), `BACKLOG_MAX_CONCURRENCY` (default 4), `BACKLOG_STORY_MAX_TURNS` (default 6). Reuse existing `BACKLOG_TIMEOUT_S`/`BACKLOG_MAX_TURNS`/`BACKLOG_MODEL` where they still apply. **No `*_MAX_REFS` knob exists — evidence is scoped by relevance, never capped.** (Timeouts are per-call hung-call safety only, not output limits.)

---

## Task 1: Shared deterministic relevance-scoping helper (Phase A core) — NO CAP

**Files:**
- Create: `src/cobol_modernizer/enrichment/refs.py`
- Test: `tests/unit/test_enrichment_refs.py`

The current bug is inlining the WHOLE graph (every `CodeEntity`). The fix is to inline only the graph refs the in-scope BRD content actually cites — the BRD was already graph-grounded during Blueprint, so its requirements carry exactly the relevant evidence refs. This is LOSSLESS (every relevant ref is kept) and naturally bounded by the spec, not by a number. There is NO cap and NO top-up with irrelevant refs.

- [ ] **Step 1: Write failing tests.** `relevant_refs(scope, known_refs)` must:
  - Walk `scope` (a list of BRD section/requirement dicts, OR one epic's requirement subset — arbitrarily nested dicts/lists) and collect EVERY string leaf that is a member of `set(known_refs)` — these are the graph refs the in-scope BRD content cites. Keep ALL of them (no cap), order-preserving (first-seen during a deterministic walk), deduped.
  - Return ONLY refs in `known_refs` (it filters the *known* set; never invents a ref).
  - Be PURE: no I/O, no LLM, no Neo4j. Deterministic.
  - Edge cases tested: empty scope → `[]`; scope cites refs NOT in known_refs → those excluded; a scope citing the same ref twice → collapsed once; a scope citing 500 distinct known refs → returns all 500 (NO truncation — assert length is exactly 500); refs nested inside `requirements[].evidence_refs` and inside free-text/other keys are both found.
  - Add an explicit test asserting the function has NO `cap`/limit parameter and never shortens the relevant set.

- [ ] **Step 2: Implement.** `relevant_refs(scope: Any, known_refs: list[str]) -> list[str]`. Build `known = set(known_refs)`; recursively walk `scope` (dict values + list items) collecting any `str` leaf in `known`, order = first-seen, deduped. Return the full list. No cap, no padding. Mirror the module/docstring style of `enrichment/base.py`; document that bounding is achieved by decomposition (per-unit scope), not truncation.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_enrichment_refs.py -q`

---

## Task 2: Inline only BRD-relevant refs in the backlog prompt; keep full refs for grounding (Phase A wiring) — NO CAP

**Files:**
- Modify: `src/cobol_modernizer/backlog/generator.py` (`build_backlog_prompt`, `generate_backlog_payload` signature)
- Modify: `src/cobol_modernizer/controlplane/backlog.py` (`run_backlog`, ~lines 89–108)
- Test: `tests/unit/test_backlog_generator.py` (extend), `tests/integration/test_controlplane_backlog_api.py` (extend)

- [ ] **Step 1: Write failing test.** Assert that for a large `known_refs` list (e.g. 1000 refs) where the BRD sections cite a specific subset, the refs inlined into the prompt are EXACTLY the BRD-relevant subset (via `relevant_refs`) — not the whole 1000, and NOT a numeric-capped slice — while the set passed to `parse_backlog_payload` for grounding is still the FULL `known_refs`. Include a case where the BRD cites 500 refs and assert all 500 are inlined (no truncation). (Test the wiring in `run_backlog` with an injected `generate` stub that captures the `known_refs` kwarg, plus a direct test of the prompt content.)

- [ ] **Step 2: Implement.** In `run_backlog` (`controlplane/backlog.py`): after building `known_refs` (full, line 89), compute `relevant = relevant_refs(sections, known_refs)` and pass `known_refs=relevant` to the `generate(...)` call (the PROMPT input). Keep `parse_backlog_payload(..., known_refs=set(known_refs))` on the FULL set (grounding correctness unchanged — line 108). Add a `logger.info` recording `len(known_refs)` (full graph) vs `len(relevant)` (inlined). `build_backlog_prompt`/`generate_backlog_payload` keep taking `known_refs` (now the relevant subset) — no schema/contract change there. NO cap anywhere.

- [ ] **Step 3: Regression — grounding/coverage unchanged.** Add/confirm a test that `parse_backlog_payload` still grounds story/AC evidence_refs against the FULL set, and `brd_logic_coverage` is computed on the full evidence (coverage ratio unaffected by which refs were inlined into the prompt).

- [ ] **Step 4: Verify.** `uv run pytest tests/unit/test_backlog_generator.py tests/integration/test_controlplane_backlog_api.py -q`

---

## Task 3: Typed fail-loud result from `run_batched` (Phase B)

**Files:**
- Modify: `src/cobol_modernizer/enrichment/base.py`
- Modify: `src/cobol_modernizer/controlplane/backlog.py` (the 502 detail)
- Test: `tests/unit/test_enrichment_base_result.py` (new)

- [ ] **Step 1: Read first.** Read `src/cobol_modernizer/agent/harness.py` to see what diagnostics `SdkAgentRunner` exposes after a call (it records `.calls` with per-call info, and computes things like a turn-cap flag / `api_error_status`). Use what's actually available — do not invent fields.

- [ ] **Step 2: Write failing tests.** Add `run_batched_result(...) -> EnrichmentResult` where `EnrichmentResult` is a small dataclass/Pydantic `{payload: dict, ok: bool, cause: str | None}`. Tests with a stub runner:
  - timeout (stub sleeps past `timeout_s`) → `ok=False`, `cause` contains `"timeout"`, `payload={}`.
  - empty result (stub returns `{}` with no exception — simulates turn-cap/parse/api-error) → `ok=False`, `cause` distinguishes it from timeout (e.g. `"no output (turn cap / parse / api error)"`, enriched with any `runner.calls[-1]` diagnostics like turn-cap/`api_error_status` when present).
  - success (stub returns a non-empty dict) → `ok=True`, `cause=None`, `payload=<dict>`.
  - Assert the EXISTING `run_batched` still returns the bare `dict` (unchanged contract) — implement it as `(await run_batched_result(...)).payload` so the silent-degrade path for non-gating enrichers (`seams/design/plan`) is untouched.

- [ ] **Step 3: Implement.** Refactor `run_batched` to delegate to `run_batched_result`; the latter catches `asyncio.TimeoutError` → `cause="timeout"`, catches other `Exception` → `cause="error: <type>"`, and on an empty `payload` from the runner sets `ok=False` with a turn-cap/parse cause (reading `runner.calls[-1]` diagnostics if available). Keep `ground_refs` as-is.

- [ ] **Step 4: Surface in backlog.** In `controlplane/backlog.py`, switch the gating call to `run_batched_result` (via the generator — see Task 5 note) and make the 502 detail echo the concrete `cause` instead of the generic string. Non-gating enrichers keep calling `run_batched`.

- [ ] **Step 5: Verify.** `uv run pytest tests/unit/test_enrichment_base_result.py tests/unit/test_backlog_generator.py -q`

---

## Task 4: Decompose backlog generation — epics call + per-epic stories call (Phase C, part 1)

**Files:**
- Modify: `src/cobol_modernizer/backlog/generator.py`
- Test: `tests/unit/test_backlog_generator.py` (extend)

- [ ] **Step 1: Split the schema.** From `BACKLOG_SCHEMA`, derive two smaller schemas: `EPICS_SCHEMA` (`{epics: [...]}` only — id/title/outcome/brd_requirement_ids/evidence_refs) and `STORIES_SCHEMA` (`{stories: [...]}` only — the existing story object incl. nested `acceptance_criteria`, each story carrying its `epic_id`). Keep `BACKLOG_SCHEMA` for backward-compat / the legacy single-call path (do not delete).

- [ ] **Step 2: Write failing tests** for two new bounded functions with a stub runner:
  - `generate_epics(*, runner, model, timeout_s, max_turns, brd_sections, relevant_refs, known_requirement_ids) -> EnrichmentResult` — prompt asks ONLY for epics; returns the typed result; the prompt inlines `relevant_refs` (the BRD-relevant set from Task 1, lossless — NOT the whole graph, NOT a capped slice).
  - `generate_stories_for_epic(*, runner, model, timeout_s, max_turns, epic, brd_sections_for_epic, relevant_refs, known_requirement_ids) -> EnrichmentResult` — prompt is scoped to ONE epic (its id/title/outcome + the BRD requirements that epic cites) and asks for stories+ACs for that epic only; `relevant_refs` here is `relevant_refs(brd_sections_for_epic, known_refs)` — every ref that epic's requirements cite, in full. Each emitted story must set `epic_id` to this epic's id.
  Assert: each is a bounded single `run_batched_result` call; the per-epic prompt does NOT contain other epics' content; AC-citation instructions preserved; NO ref truncation (a per-epic call citing many refs inlines them all).

- [ ] **Step 3: Implement** both functions plus their system/prompt builders (reuse `BACKLOG_SYSTEM`'s grounding rules; add focused per-step system prompts). Each uses its own `timeout_s`/`max_turns` args.

- [ ] **Step 4: Verify.** `uv run pytest tests/unit/test_backlog_generator.py -q`

---

## Task 5: Backlog map-reduce orchestrator (Phase C, part 2)

**Files:**
- Modify: `src/cobol_modernizer/backlog/generator.py` (`generate_backlog_payload`)
- Test: `tests/unit/test_backlog_generator.py` (extend)

- [ ] **Step 1: Write failing tests** for the new orchestrator behavior of `generate_backlog_payload` (keep its public signature compatible with `run_backlog`'s call: `*, runner, model, timeout_s, brd_sections, known_refs, known_requirement_ids, max_turns`). With a stub runner scripted to return canned epics then canned per-epic stories:
  - It calls `generate_epics` once, then `generate_stories_for_epic` once per returned epic (assert call counts / per-epic scoping).
  - Per-epic story calls run with bounded concurrency (`asyncio.gather` under a semaphore of `BACKLOG_MAX_CONCURRENCY` — this limits parallel in-flight calls, NOT the number of stories produced).
  - It MERGES into the legacy raw shape `{"epics": [...], "stories": [...]}` that `parse_backlog_payload` already consumes (so the reduce — `derive_story_dependencies` in `controlplane/backlog.py` — is untouched).
  - PARTIAL FAILURE: if ONE epic's story call fails (typed `ok=False`), that epic contributes no stories but the others still merge (logged); the run still returns a non-empty payload.
  - FAIL-LOUD: if the epics call itself fails, OR every epic's stories fail (zero stories total), return an empty/typed-failure payload so `run_backlog` raises a 502 with the concrete cause (do NOT silently persist an empty backlog).

- [ ] **Step 2: Implement** `generate_backlog_payload` as: `scoped_refs = known_refs` (already scoped by the caller in Task 2); `epics_res = await generate_epics(...)`; if not `ok` → return failure; then `await asyncio.gather(*[bounded generate_stories_for_epic(epic) ...])` under a semaphore of `BACKLOG_MAX_CONCURRENCY`; merge epics + all stories; attach the epic→story ids; return the merged dict (or a typed failure when zero stories). Per-unit timeouts from `BACKLOG_EPIC_TIMEOUT_S`/`BACKLOG_STORY_TIMEOUT_S`. Keep the old single-call body available under a clearly-named helper (e.g. `_generate_backlog_oneshot`) reachable via an env flag `BACKLOG_GEN_MODE=decomposed|oneshot` (default `decomposed`) for fallback/debug — mirroring `CODEGEN_MODE`.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_backlog_generator.py -q`

---

## Task 6: Wire orchestrator + typed cause into the control plane (Phase C wiring)

**Files:**
- Modify: `src/cobol_modernizer/controlplane/backlog.py`
- Test: `tests/integration/test_controlplane_backlog_api.py` (extend)

- [ ] **Step 1: Write failing tests** (extend the existing backlog API test, which already injects a `generate` stub and a FakeNeo4j):
  - A successful decomposed run persists a backlog whose stories span multiple epics, runs `derive_story_dependencies`, and publishes the coverage gates (existing assertions still hold — the merged payload feeds the unchanged reduce).
  - A typed failure from the generator surfaces as a 502 whose detail includes the concrete `cause` (timeout / turn-cap / parse), not the generic string.
  - Scoped-refs-to-prompt / full-refs-to-grounding wiring (from Task 2) still holds.

- [ ] **Step 2: Implement.** Ensure `run_backlog` consumes the orchestrator's typed result (Task 3/5) and echoes `cause` in the 502; confirm `relevant_refs` is applied to the prompt input and the full set to grounding; no change to `derive_story_dependencies`, `brd_logic_coverage`, or `BacklogStorage.save`.

- [ ] **Step 3: Verify.** `uv run pytest tests/integration/test_controlplane_backlog_api.py tests/unit/test_backlog_generator.py -q`

---

## Task 7: Generalize to technical design (Phase D)

**Files:**
- Modify: `src/cobol_modernizer/technical_design/generator.py`
- Modify: `src/cobol_modernizer/controlplane/technical_design.py` (~line 107, the `[:200]`)
- Test: `tests/unit/test_technical_design_generator.py` (extend), `tests/integration/test_controlplane_technical_design_api.py` (extend)

- [ ] **Step 1: Read first.** Read `technical_design/generator.py` + `controlplane/technical_design.py` to confirm the single-`run_batched` shape, the `[:200]` cap site, and the existing `fallback_technical_design_payload`.

- [ ] **Step 2: Write failing tests.**
  - Replace the hard-coded `[:200]` TRUNCATION with `relevant_refs(brief_or_sections, known_refs)` (shared helper from Task 1) — the inlined set becomes the relevant refs (lossless), NOT a numeric slice. Assert the `[:200]` cap is gone and that a brief citing >200 relevant refs inlines all of them (no truncation); grounding (if any) stays on the full set.
  - The technical-design gating failure path surfaces a typed `cause` (Task 3 result) rather than a bare 500/empty.
  - (Decomposition) IF the technical design emits per-service/per-bounded-context structures, add a per-context bounded generation via `asyncio.gather` (mirror `domain/tactical.py`) behind `TECH_DESIGN_GEN_MODE=decomposed|oneshot` (default `decomposed`); each context call is bounded + typed, scoped to that context's relevant refs (lossless). If, after reading, the technical-design output is NOT cleanly partitionable per context without a larger refactor, STOP and report — implement only the relevance-scoping (removing `[:200]`) + typed-cause generalization, and record the per-context decomposition as a documented follow-up rather than forcing it.

- [ ] **Step 3: Implement** the chosen subset (relevant_refs + typed cause are required; per-context decomposition if clean).

- [ ] **Step 4: Verify.** `uv run pytest tests/unit/test_technical_design_generator.py tests/integration/test_controlplane_technical_design_api.py -q`

---

## Acceptance Criteria

- [ ] Backlog prompt never inlines the whole graph — it inlines only the BRD-relevant refs (lossless, NO numeric cap/`[:N]`); grounding/coverage still uses the full set (ratio unchanged on a fixed fixture). A fixture where the BRD cites 500 refs inlines all 500.
- [ ] No artifact or evidence is capped/truncated: there is no `*_MAX_REFS` knob, no `[:N]` slice on refs, and no limit on the number of epics/stories/ACs produced (a `grep` for `MAX_REFS` / `[:200]` in the touched generators returns nothing).
- [ ] Backlog generation runs as epics-call + bounded-parallel per-epic story calls + the existing deterministic `derive_story_dependencies` reduce — no single call emits the whole backlog, and total output is unbounded (more epics ⇒ more calls, not a bigger single call).
- [ ] A backlog generation failure surfaces a concrete cause (timeout / turn-cap / parse / api-error) in the 502, not a bare `{}`.
- [ ] One slow/failing epic does not zero the whole backlog (partial-progress); only zero-total-stories or an epics-call failure fails the stage (loudly).
- [ ] `technical_design` uses the shared `relevant_refs` scoping (its `[:200]` truncation removed) and surfaces typed causes; per-context decomposition done where clean, else recorded as follow-up.
- [ ] Non-gating enrichers (`seams/design/plan`) still degrade silently to `{}` (their `run_batched` contract is untouched).
- [ ] Full suite green: `uv run pytest tests/unit tests/integration/test_controlplane_backlog_api.py tests/integration/test_controlplane_technical_design_api.py -q` (JDK25 env).

## Non-Goals

- **Do NOT cap or truncate anything.** No `*_MAX_REFS`, no `[:N]` on refs, no limit on epics/stories/ACs/code. Call size is bounded by relevance-scoping + decomposition only. Dropping a *relevant* ref to hit a number is forbidden.
- Do not decompose the non-gating enrichers (`seams/design/plan`) — they're small-scope and already degrade gracefully.
- Do not change `derive_story_dependencies`, `brd_logic_coverage`, or the storage/render layers — the decomposition only changes how the raw payload is *produced*, not how it's reduced/persisted.
- Do not touch the already-robust generators (`codegen/*`, `domain/tactical.py`, `brd/pipeline.py`).
- Do not require a live LLM/Neo4j in unit tests — stub the runner and inject the `generate` seam, as the existing tests do.

## Implementation Order

1. Shared `relevant_refs` helper (Task 1).
2. Scope backlog prompt, keep full grounding (Task 2). **← backlog unblocked on large repos here.**
3. Typed fail-loud result (Task 3).
4. Epics + per-epic story calls (Task 4).
5. Map-reduce orchestrator (Task 5).
6. Control-plane wiring + typed 502 (Task 6).
7. Generalize to technical design (Task 7).
