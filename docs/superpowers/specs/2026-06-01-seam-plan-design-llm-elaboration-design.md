# Design: LLM Elaboration for Seam / Plan / Design Stages

**Date:** 2026-06-01
**Status:** Approved (brainstorming) — pending implementation plan
**Author:** Claude + cwijay

## Problem

Three journey stages — **seams**, **plan**, **design** — produce shallow output. They
are fully deterministic (no LLM): the backend emits Cypher-derived scores and
templated structures, and the UI drops even some of what is computed.

Concretely (from a code map of `controlplane/analysis.py` + the underlying modules):

- **Seams** (`rank_candidates`): each `SeamCandidate` has a `rationale` field that is
  **always empty** — only the async `build_seam_set` path fills it (via the LLM helper
  `awrite_rationale`), which the stage never calls. The 5 computed `signals` and
  `evidence_map` are produced but not surfaced.
- **Plan** (`stories_from_seam_set` + `derive_dependencies`): `Story.invest` is
  **always `None`** — only the LLM `judge_story` / `build_story_dag` path fills it.
  Stories are `"Migrate {program}"` + derived `depends_on`, with no description or
  acceptance criteria. `analysis.py` notes the LLM INVEST judge is "intentionally
  skipped here." The seam→story **dependency map** (`depends_on` edges) and a linear
  **`topo_order`** already exist deterministically (`planner/dag.py`), but: (a) the UI
  barely renders them ("after S1, S2"), (b) there is no **delivery-wave** grouping
  (which stories can ship in parallel), and (c) nothing explains *why* an edge exists
  or how to *sequence the rollout*. Delivery planning is the most valuable plan
  output and is currently absent.
- **Design** (`assign_context` + `default_adrs_for_writer_slice` + `judge_design`):
  ADRs are **3 canned templates** with `{slice}`/`{resource}` interpolation;
  `components` are hardcoded `["{prog}Service", "{prog}Repository"]`; `evidence_map`
  is a minimal `{"DR-1": [prog]}`. **No LLM path exists at all** for design.

## Goal

Add LLM-generated narrative detail to all three stages **without** sacrificing the
speed and reliability of the deterministic stages, and without reintroducing the
fragility we just hardened out of the BRD pipeline.

## Locked decisions (from brainstorming)

1. **Augment, not replace.** The deterministic scores / DAG / context assignment stay
   as the backbone. The LLM only *adds* narrative fields on top. If the LLM is slow,
   fails, or drifts, the stage degrades to *exactly today's output* — never worse.
2. **Two-phase delivery.** The deterministic stage POST returns immediately (stage
   passes, gate unblocks, structure usable now). A separate background "enrich" job
   adds the narrative, which the UI merges when ready. Enrichment is non-blocking and
   optional.
3. **Batched fan-out.** One (or a few, via chunking) structured-LLM call per stage
   enriches *all* items at once — bounded cost/latency regardless of repo size.
   Rejected: per-item calls (the fan-out explosion seen in the BRD map phase).
4. **Prompt-grounded.** Enrichment is grounded in the already-computed deterministic
   data fed into the prompt — a single structured call, **not** a graph-tool agentic
   loop. Reuses the hardened harness; no 30-turn exploration cost.

## Architecture

```
POST /api/workspaces/{id}/{stage}            deterministic result NOW (unchanged)
POST /api/workspaces/{id}/{stage}/enrich     202; starts jobs.runner job "{stage}-enrich"
                                               → re-run fast deterministic compute for items
                                               → ONE batched structured-LLM call adds narrative
                                               → validate grounding → store result by item id
GET  /api/workspaces/{id}/{stage}/enrichment  poll job status + result (mirrors blueprint_status)

UI: render deterministic immediately → merge enrichment by item id when its job completes
```

`{stage}` ∈ {`seams`, `plan`, `design`}.

Enrichment is stored as the `jobs.runner` job result, keyed by item id — in-memory,
single-process, matching the existing `jobs.py` posture (its docstring already notes a
multi-worker deployment would back this with a table). On restart, an un-re-run
enrichment is simply absent and the screen shows deterministic-only until re-triggered.
No new persistence table in this scope.

### Why this shape

- Augment + two-phase ⇒ deterministic stages keep their instant, reliable behavior;
  enrichment can never block a gate or empty a stage.
- Batched + prompt-grounded ⇒ one structured call reusing `SdkAgentRunner`; no agentic
  loop, no per-item fan-out, no graph-tool turns.
- Stage independence ⇒ one enricher failing never touches the other two.

## Components

New package `src/cobol_modernizer/enrichment/`. Each enricher is a pure async function:
`(deterministic_output, known_refs, *, runner, model, timeout_s) -> dict[item_id, narrative]`.
Each makes one batched `runner.run_structured` call (chunked into a few calls if the
item set is large; chunking is logged). All parsing is defensive (case/enum tolerant,
skip-malformed) following `agent/brd_judge.py`'s `_norm_*` / `_parse_*` helpers.

### `enrich_seams`
- **Input:** ranked candidates (program, seam_type, signals, score, evidence_map).
- **Output per program:** `rationale` (1–2 sentences: why it ranks here + migration
  risk), `cited_refs` (validated ⊆ `known_refs`), `grounded` (bool).
- Generalizes the existing per-candidate `seam/rationale.py:awrite_rationale` into one
  batched call; same grounding contract ("cite only provided refs").

### `enrich_plan`
Two complementary outputs — per-story and plan-level (delivery planning):
- **Per-story** (`{story_id: ...}`): `invest` (6 dims 1–5, with the existing
  groundedness floor: ungrounded ⇒ valuable/estimable capped at 2), `description`
  (what/why), `acceptance_criteria` (list), `groundedness_failures` (list). Populates
  the existing-but-unused `Story.invest` (`planner/schema.py`) and adds new narrative
  fields. Batched generalization of `planner/invest.py:judge_story`.
- **Plan-level delivery narrative** (the "plan the delivery accordingly" view):
  `edge_rationale` (`{"S3->S1": "S1 establishes the ACCT-MASTER writer S3 reads"}`,
  grounded in seam/data-ownership evidence) and `wave_narrative` (per delivery wave:
  what it delivers, what it de-risks, reader/writer + blast-radius sequencing
  guidance). Grounded only in the provided seam evidence.

### Deterministic plan-stage additions (NOT LLM)
The dependency map is graph math and stays deterministic for reliability. Add
`delivery_waves(dag) -> list[list[str]]` to `planner/dag.py`: level-set grouping via
the same Kahn's-algorithm pass as `topo_order` — each wave is the set of stories whose
dependencies are all satisfied by prior waves, i.e. the stories that can be migrated in
parallel. The `plan` stage returns `delivery_waves` alongside the existing `topo_order`
and `stories`. The LLM `wave_narrative`/`edge_rationale` augments this; if enrichment is
absent, the waves + DAG still render.

### `enrich_design`
- **Input:** each `ServiceDesign` (slice_id, context, owned_resources), its template
  ADRs, and the external-writers map.
- **Output per slice_id:** elaborated `adrs` (richer context/decision/consequences +
  `alternatives`), `component_descriptions`, `api_surface`, `data_model_notes`,
  `cited_refs` (validated ⊆ `known_refs`).
- Net-new (no existing LLM design path). Grounded in `owned_resources` + program refs.

### Endpoints
- `controlplane/analysis.py`: add `POST /{wid}/seams/enrich`, `GET /{wid}/seams/enrichment`,
  and the same pair for `plan`. The `design` endpoints go alongside the existing
  `run_design`. All follow the blueprint POST-202 + GET-poll shape, fast-validate first
  (404/409 on missing workspace / unparsed graph), then hand to `jobs.runner`.

### Schema additions
- `seam/schema.py`: `rationale` already exists; add `cited_refs`, `grounded` if needed
  on the enrichment payload (not the deterministic candidate).
- `planner/schema.py`: `Story.invest` already exists; new narrative is returned in the
  enrichment payload (not by mutating the deterministic `Story`), keeping the
  deterministic schema stable. A small `StoryNarrative`/`SeamNarrative`/`DesignNarrative`
  Pydantic model per stage defines the enrichment contract; the plan enrichment also
  carries a `PlanDeliveryNarrative` (`edge_rationale`, `wave_narrative`). The
  deterministic `delivery_waves` is part of the plan stage's normal (non-enrichment)
  response.

## Reliability & error handling

- Reuse the hardened `SdkAgentRunner`: robust enum/case-tolerant parsing, skip-malformed
  rows, per-call timing/turn logging via `label`.
- **`asyncio.wait_for` timeout** around each enrich call (no stage has a timeout today;
  this is a direct BRD lesson). On timeout/exception → empty enrichment → deterministic
  render. Configurable via `{STAGE}_ENRICH_TIMEOUT_S`.
- **Grounding enforced:** cited refs validated against `known_refs`; ungrounded items
  flagged (`grounded=false`) and shown with a warning badge; hallucinated identifiers
  are never merged into displayed evidence.
- **Model:** Sonnet default for all three (narrative is not a hard judgement, and Opus
  is slow on a serial path). Override via `SEAM_ENRICH_MODEL` / `PLAN_ENRICH_MODEL` /
  `DESIGN_ENRICH_MODEL`. Size-tiering to Haiku for small repos is a noted follow-on, not
  in this scope.

## Frontend

`SeamStudio` / `IncrementPlanner` / `DesignStudio`: render the deterministic result as
now, plus an explicit **"Add detail"** button (enrichment is **not** auto-triggered —
the user decides when to spend the LLM call, consistent with this project's
cost-consciousness). The button drives the enrich job via the backoff `useJob`, showing
an "enriching…" state, then merges narrative by item id:
- Seams: `rationale` line under each candidate.
- Plan: render the DAG as **delivery waves** (parallel tracks grouped by `delivery_waves`,
  with dependency edges shown), each wave annotated with its `wave_narrative` and edges
  with `edge_rationale`; per-story INVEST bars + `description` + `acceptance_criteria`.
  This replaces the flat "after S1, S2" list with an actual delivery plan.
- Design: elaborated ADRs + `component_descriptions` / `api_surface` /
  `data_model_notes` under each slice.

Ungrounded fields get a subtle warning badge. `web/src/lib/api.ts` gains
`start{Stage}Enrich` / `get{Stage}Enrichment` helpers + types.

## Testing

- **Unit** (per enricher, `FakeRunner`): happy path; malformed/capitalized/ungrounded
  model output → graceful degradation + correct grounding flags. Mirrors
  `tests/unit/test_brd_judge_robust_parsing.py`.
- **Unit** (`delivery_waves`, no LLM): correct level-set grouping (independent stories
  share a wave; dependents land in later waves); single-node and diamond DAGs; agrees
  with `topo_order` (every story in exactly one wave, deps in strictly earlier waves).
- **Endpoint** (`jobs.runner.inline=True` + stubbed enricher): 202 → poll → merged
  result; enricher failure → deterministic-only, job status `failed` surfaced. Mirrors
  the blueprint endpoint tests.
- **Frontend** (vitest + MSW): deterministic-then-enriched merge, enriching state,
  ungrounded badge. Mirrors `BlueprintStudio.test.tsx`.

## Out of scope (YAGNI)

- Persisting enrichment to a Neo4j/DB table (keep the in-memory job posture).
- Size-tiering the enrichment model (noted follow-on).
- Surfacing the dropped *deterministic* fields (Axis A) generally — this spec is Axis B
  only. (Exception: the plan stage's DAG + `delivery_waves` visualization IS in scope —
  it's the deterministic substrate the delivery narrative attaches to, and a new field
  rather than a previously-dropped one.)
- Graph-tool agentic enrichment (explicitly rejected in favor of prompt-grounded).

## Open questions

None blocking. Chunk size N for batched calls and per-stage timeout defaults will be
chosen during implementation (sensible defaults, env-overridable). Enrichment is
user-triggered via an explicit button (not auto-run on stage completion).
