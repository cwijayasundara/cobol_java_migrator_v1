# Thoughtworks-Aligned Modernization — End-to-End Integration Design

**Date:** 2026-06-02
**Status:** Approved (brainstorming) → ready for implementation plan
**Predecessor:** `docs/superpowers/plans/2026-06-02-thoughtworks-aligned-modernization.md` (the 10 TDD tasks, all implemented as tested islands)

## Problem

The 10 tasks of the Thoughtworks-aligned plan were implemented verbatim and all 25 unit/integration
tests pass, but the artifact chain is **not wired end-to-end**. Each piece is a tested island:

1. Generators are dead code — `parse_backlog_payload`, `derive_story_dependencies`,
   `brd_logic_coverage`, and `story_behavior_gate` have zero callers outside their own modules.
2. Read-without-write persistence — `build.py`'s `_backlog_brief` / `_technical_design_brief`
   query `:Backlog` / `:TechnicalDesign` nodes that **nothing ever creates**, so the codegen brief
   never actually contains a backlog or technical design.
3. Domain backlog plumbing is a no-op — `decompose()`/`run_domain_design()` accept `backlog_json`,
   but the only real caller (`analysis.py:_domain_run_and_persist`) omits it (always `""`).
4. Technical Design is half-built — only `schema.py` exists; no generator, endpoint, persistence,
   or integration test.
5. Backlog API is a placeholder — `controlplane/backlog.py` is the minimal `"idle"` stub: no
   generation job, no persistence, no retrieval.
6. No UI surface — `web/src` has zero references to backlog, epics, stories, acceptance criteria,
   or technical design.

## Goal

Make the chain `graph → BRD → coverage → epics/stories → story DAG → seams → DDD → technical design
→ codegen → equivalence` **explicit and enforceable at runtime**, with full cockpit UI, following
the existing stage patterns (`blueprint.py` for stage shape, `DomainDesignStorage` for persistence,
`jobs.JobRunner` for background work, the existing gate/approval mechanism for blocking + override).

## Approved Decisions

| Decision | Choice |
| --- | --- |
| Integration scope | **Full e2e including cockpit UI** |
| Gate enforcement | **Block with override** (reuse existing `waived_with_risk` + `risk_accepted`) |
| Backlog placement | **New dedicated `backlog` journey stage** between Blueprint and Plan |
| Technical Design production | **LLM generator**, grounded on graph refs + DDD contexts + story ids |
| Technical Design slot | **Replace the existing `design` stage content**; legacy writer-slice design retired |
| Gate wiring | **Coverage → Blueprint**, **Coverage → Backlog**, **Story-behavior → Verify** |

## Architecture

### Journey stages (12 → 13)

`stages.py` `JOURNEY_STAGES` (backend source of truth) and `web/src/lib/stages.ts` `STAGES`
(mirror) are updated in lockstep. New `backlog` stage inserted after `blueprint`; the `design`
stage keeps its key/label/screen slot but now carries the Technical Design artifact.

```
outcome → intake → parse → graph → explore → blueprint
   → backlog        (NEW; gate_key: backlog_coverage)
   → seams → plan → domain
   → design          (now LLM Technical Design; gate_key: design_data_ownership)
   → build → verify  (verify gains a second gate: story_behavior)
```

- `backlog` ordinal inserts at 7; all later ordinals shift +1.
- `web/src/lib/stages.ts` `PHASES["design"]` band gains `"backlog"`.
- `ADVANCEABLE_STAGES` gains `"backlog"`.

Stage→screen dispatch in `web/src/components/screens/StageScreen.tsx` gains `case "backlog"`.

### Persisted artifacts (Neo4j, mirroring `DomainDesignStorage`)

Two new versioned node types hung off `(:Repository {slug})`, each with a storage class that
copies the BRD/DomainDesign save/get-latest pattern (versioned `CREATE`, `RETURN d.version`):

```
(:Repository {slug})-[:HAS_BACKLOG]->(:Backlog {
    id, repo_slug, version,
    epics_json, stories_json, evidence_map, coverage_json,
    html, model, token_usage, created_at
})

(:Repository {slug})-[:HAS_TECHNICAL_DESIGN]->(:TechnicalDesign {
    id, repo_slug, version,
    services_json, evidence_map,
    html, model, token_usage, created_at
})
```

Property names match what `build.py`'s existing readers already query
(`epics_json`, `stories_json`, `services_json`, `version`), so those readers light up with no change.

### Gates

Gates are `Gate` rows (SQLAlchemy) created/updated by the stage POST handlers (upsert by
`(workspace_id, gate_key)`), not only by `seed.py`. A gate is `passed` when its deterministic check
clears a threshold, otherwise `open` (blocks advance). Override path is the existing
`POST /gates/{gate_id}/approval` with `decision="waived_with_risk"` + `risk_accepted=true`.

| Gate key | Stage | Pass condition |
| --- | --- | --- |
| `brd_logic_coverage` | blueprint | `coverage_ratio ≥ BACKLOG_COVERAGE_MIN` (computed when backlog runs, written back to blueprint stage) |
| `backlog_coverage` | backlog | every story grounded + has acceptance criteria (parser already enforces) AND `coverage_ratio ≥ BACKLOG_COVERAGE_MIN` |
| `design_data_ownership` | design | every writer resource owned by exactly one technical service |
| `story_behavior` | verify | every selected story's acceptance-criterion ids appear in generated test refs AND equivalence verdict == `passed` |

`BACKLOG_COVERAGE_MIN` env var, default `0.8`.

## Components

### 1. Storage layer (new)
- `src/cobol_modernizer/backlog/storage.py` — `BacklogStorage(client)` with `.save(backlog, *, coverage, html, model, token_usage)` and `.get_latest(repo_slug)`. Mirrors `DomainDesignStorage`.
- `src/cobol_modernizer/technical_design/storage.py` — `TechnicalDesignStorage(client)` with `.save(...)` / `.get_latest(...)`.

### 2. Backlog stage (rewrite `controlplane/backlog.py`)
- `POST /api/workspaces/{wid}/backlog` — validates fast, hands to `JobRunner` (`kind="backlog"`). Job:
  1. Read latest `:BRD` → sections + known requirement ids.
  2. Read graph refs (`MATCH (n:CodeEntity {repo}) RETURN n.qualified_name`).
  3. Read seam candidates (existing seam signals) for the DAG step.
  4. `SdkAgentRunner` with `BACKLOG_SYSTEM` → raw payload.
  5. `parse_backlog_payload(raw, repo_slug, known_refs, known_requirement_ids)`.
  6. `derive_story_dependencies(stories, seam_candidates, repo_slug)`.
  7. `brd_logic_coverage(neo4j, repo_slug, brd_sections, evidence_map)`.
  8. `BacklogStorage.save(...)` + render HTML.
  9. Upsert `backlog_coverage` gate (this stage) and `brd_logic_coverage` gate (blueprint stage).
- `GET /api/workspaces/{wid}/backlog` — real status: `{status, result:{epics,stories,coverage_ratio,version}, error}`.
- `GET /api/workspaces/{wid}/backlog/html` — rendered HTML view.
- HTML renderer: `src/cobol_modernizer/backlog/render.py` (`render_html(backlog, coverage) -> str`), self-contained like the BRD/domain renderers.

### 3. Domain consumes backlog (modify `controlplane/analysis.py`)
- `_domain_run_and_persist` reads the persisted backlog (via `BacklogStorage.get_latest`), serializes stories to JSON, and passes `backlog_json=` into `run_domain_design`. No signature changes needed downstream (plumbing already accepts it).

### 4. Technical Design stage (new generator + endpoint; rewire `design`)
- `src/cobol_modernizer/technical_design/generator.py` — `TECHNICAL_DESIGN_SYSTEM`, `build_technical_design_prompt(*, ddd_json, backlog_json, seam_waves_json, graph_summary)`, `parse_technical_design_payload(raw, *, repo_slug, known_refs, known_story_ids, known_contexts)` (grounds `evidence_refs` to graph refs, `story_ids` to known stories, `bounded_context` to known DDD contexts; drops ungrounded).
- `src/cobol_modernizer/technical_design/render.py` — `render_html(design) -> str`.
- `src/cobol_modernizer/controlplane/technical_design.py` — `POST/GET /api/workspaces/{wid}/technical-design` + `/html`, JobRunner `kind="technical_design"`. Reads latest DDD + backlog + seam waves → generator → `TechnicalDesignStorage.save` → upsert `design_data_ownership` gate.
- Existing `design` stage POST in `controlplane/analysis.py` (legacy writer-slice) is **removed/rewired** to call the technical-design job. Legacy writer-slice design code path retired (deleted, not flagged).
- `controlplane/__init__.py` includes the new `technical_design` router.

### 5. Verify story-behavior gate (modify `controlplane/verify.py`)
- After equivalence runs, for each selected story compute `story_behavior_gate(story_id, acceptance_criteria_ids, generated_test_refs, equivalence_verdict)`.
- `generated_test_refs` source: codegen (Task 9) already cites story/AC ids in generated tests; the build job records which AC ids became tests as an `Artifact` (JSON list) the verify stage reads.
- Aggregate per-story results into one `story_behavior` gate on the verify stage (passed iff all stories pass; else open/blocks; waivable).

### 6. UI (full e2e)
- `web/src/components/screens/BacklogStudio.tsx` — Generate button, poll status, render epics → stories → acceptance criteria → dependency DAG, coverage banner, gate/waive control. Follows `BlueprintStudio`/`DomainStudio` fetch+poll pattern. Registered as `case "backlog"` in `StageScreen.tsx`.
- `web/src/components/screens/DesignStudio.tsx` — repurposed to render Technical Design (services with API/persistence/integration contracts + evidence) from the technical-design endpoint; legacy writer-slice rendering removed.
- `web/src/lib/stages.ts`, `web/src/lib/api.ts` (or wherever endpoints/types live) — add backlog + technical-design endpoints, types, and the new stage.
- MSW handlers (`web/src/test/**`) — add mock responses so screen tests stay backend-independent.
- Vitest tests: `BacklogStudio.test.tsx` (new), update `DesignStudio.test.tsx`, update `stageDispatch.test.tsx` for the new stage.

## Data flow

```
BRD (sections + requirement ids) + graph refs + seam candidates
  └─[backlog job]→ Backlog{epics,stories,AC,DAG} + LogicCoverageReport
        ├─ persist :Backlog, gates backlog_coverage + brd_logic_coverage
        ├─→ domain decompose(backlog_json) → DDD contexts
        │     └─[technical-design job]→ TechnicalDesign{services,APIs,persistence}
        │           └─ persist :TechnicalDesign, gate design_data_ownership
        └─→ build _codegen_brief reads :Backlog + :TechnicalDesign
              └─ codegen turns acceptance criteria into JUnit tests (cite story/AC ids)
                    └─ build records generated_test_refs artifact
                          └─[verify]→ equivalence + story_behavior_gate per story
                                └─ gate story_behavior
```

## Error handling

- All Neo4j reads in stage handlers degrade defensively (`_NEO4J_ERRORS` → `None`/empty), matching existing `build.py` readers — a missing upstream artifact degrades gracefully (e.g., domain runs without backlog if none generated; codegen grounds on BRD/design alone).
- Generation jobs follow `JobRunner` error capture (status `error` + message; GET surfaces it).
- Gate upserts are idempotent; re-running a stage recomputes and overwrites the gate's computed status but never silently flips a `waived_with_risk` approval back to open without a new run.
- Ungrounded refs/ids from the LLM are dropped by the parsers (never raise), except the existing
  "story without acceptance criteria" `ValueError`, which the job catches → job `error`.

## Testing strategy

Keep all 25 existing plan tests green. Add:

**Python (pytest):**
- `tests/unit/test_backlog_storage.py` — save/get-latest round-trip (fake Neo4j), version increment.
- `tests/unit/test_technical_design_storage.py` — round-trip.
- `tests/unit/test_backlog_render.py` / `test_technical_design_render.py` — HTML contains epics/stories/services.
- `tests/unit/test_technical_design_generator.py` — prompt builder includes DDD+backlog; parser drops ungrounded refs/story-ids/contexts.
- `tests/integration/test_controlplane_backlog_api.py` — extend: POST runs (inline runner) → persists → GET returns done + coverage; gate created; waive overrides.
- `tests/integration/test_controlplane_technical_design_api.py` — POST→persist→GET; design_data_ownership gate.
- `tests/integration/test_domain_uses_real_backlog.py` — domain job reads persisted backlog and passes non-empty `backlog_json` into decompose.
- `tests/integration/test_verify_story_behavior_gate.py` — verify computes story_behavior gate; blocks then waives.
- `tests/integration/test_build_brief_has_backlog_after_generation.py` — end-to-end: generate backlog+tech-design, then `_codegen_brief` actually contains them.

**Web (Vitest + tsc + next build):**
- `BacklogStudio.test.tsx` (new), `DesignStudio.test.tsx` (updated), `stageDispatch.test.tsx` (updated), MSW handlers.

**Full suite gate:** `uv run pytest` green; `cd web && npm test && npx tsc --noEmit && npx next build` green.

## Out of scope (YAGNI)

- Multi-worker/persistent job queue (current in-process `JobRunner` is fine for the dev cockpit).
- Golden-fixture capture pipeline (the `golden_fixture_ids` field stays; populating it from a running
  legacy system is a separate workstream). Story-behavior gate uses the existing equivalence verdict.
- Re-deriving seams from backlog (seams remain the existing read/write resource analysis; backlog DAG
  consumes them, it does not replace them).

## Self-review notes

- No placeholders/TBD: every component names concrete files and functions that exist or are created.
- Consistency: node property names (`epics_json`, `stories_json`, `services_json`, `version`) match
  `build.py` readers; gate keys match the gate-wiring table; stage keys match `stages.py`/`stages.ts`.
- Scope: one implementation plan; ordered so each step leaves the suite green (storage → generation →
  consumption → gates → UI).
- Ambiguity resolved: Technical Design **replaces** the `design` stage content (legacy deleted, not
  flagged); coverage gate computed in the backlog job and written to both blueprint and backlog stages.
