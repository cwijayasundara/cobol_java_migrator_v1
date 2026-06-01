# Design: Blueprint "Improve" — instruction-directed, graph-grounded BRD refinement

**Date:** 2026-06-01
**Status:** Approved (brainstorming) — pending implementation plan
**Author:** Claude + cwijay

## Problem

The Blueprint stage generates a versioned BRD (map-reduce draft → judge → retry) and
shows the latest rendered HTML. There is no way to *refine* an existing BRD — the only
action is "Generate blueprint", which produces a fresh BRD from scratch. Users want to
steer the BRD ("expand the non-functional requirements", "add more data-integration
detail", "make requirements more testable") and get an improved version without
regenerating blindly.

## Goal

Add a user-directed **Improve** action: given the current BRD and a free-text
instruction, produce an improved BRD — **grounded in the parsed graph** (it may pull
new entities/relationships to genuinely add detail) — re-judged for grounding/quality,
and saved as a **new version**. Reuse the hardened BRD machinery so it stays as fast and
reliable as the generate path.

## Locked decisions (from brainstorming)

1. **User-directed instruction.** Improve takes a free-text instruction (not a one-click
   judge-feedback pass). The instruction steers the refinement.
2. **Graph-grounded (agentic).** Improve gets the same graph-navigation tools the BRD
   draft agent uses, so it can add *new grounded* detail (not just reword existing
   text). It is therefore an agentic loop, re-judged for hallucinations.
3. **New version.** Each Improve produces a new BRD version (storage already
   auto-increments). Minimal version UX to start: the screen shows the new latest
   version (no version-browser yet).
4. **Reuse all BRD guardrails.** Size-adaptive turn budget, per-call timeout,
   timing/label instrumentation, Sonnet model (env-overridable), re-judge on Haiku,
   background job + poll.
5. **Approach 1 (dedicated path).** A separate `agenerate_brd_improvement` reusing the
   graph tools / harness / judge / storage — NOT a parameterized `agenerate_brd_graph` —
   so generate and improve stay independently testable.

## Architecture & data flow

```
POST /api/workspaces/{id}/blueprint/improve   body: {"instruction": "<text>"}
  → 202; start jobs.runner job "blueprint-improve":
      1. load the latest BRD for the repo (structured sections+evidence_map if present,
         else fall back to the stored rendered HTML as text)
      2. run the improve agent: graph MCP tools + an IMPROVE_SYSTEM prompt seeded with
         the current BRD + the instruction → emits a full improved BRDDraft
      3. re-judge via ajudge (Haiku tier) — groundedness + quality
      4. render HTML + BRDStorage.save(...) → NEW version (auto-incremented)
      5. return {repo_slug, brd_id, version, rating, weighted_score, model, token_usage}
GET  /api/workspaces/{id}/blueprint/improve    → poll the "blueprint-improve" job
GET  /api/workspaces/{id}/blueprint/html       → serves latest (now the improved version)

UI: BlueprintStudio shows an instruction <textarea> + "Improve" button ONCE a BRD exists;
    a second useJob drives the improve endpoints; on done, refresh the iframe to the new
    version (version-busted URL) and update the shown version/rating.
```

### Why this shape
- Mirrors the generate background-job pattern (POST 202 + poll) and the enrich pattern,
  so it composes with the existing cockpit polling (`useJob`).
- Reuses the graph tools + harness + judge + auto-versioning storage — the improve agent
  is essentially "one BRD draft agent seeded with the prior BRD + an instruction".
- Generate and improve are separate functions/endpoints → each independently testable.

## Components

### `src/cobol_modernizer/agent/brd_improve.py` (new)
`agenerate_brd_improvement(deps, *, current_brd, instruction, runner, model, max_turns,
min_turns=None, advisor=None, advisor_max_uses=3) -> tuple[BRDDraft, Strategy]`
- Builds the graph MCP server via `build_graph_server(deps, advisor=…)` and uses
  `GRAPH_TOOL_NAMES` (reuse — identical to the draft agent).
- `IMPROVE_SYSTEM` prompt: "You are refining an EXISTING Business Requirements Document.
  Apply the user's instruction. Use the graph tools to add only grounded detail (real
  entity ids / file paths you inspect). PRESERVE correct existing content and every
  still-valid evidence pointer. Do not invent entities. Emit the full improved BRDDraft
  (the same 11 sections)."
- Prompt body embeds the current BRD (sections + evidence_map as JSON, or the HTML text
  fallback) and the instruction.
- `runner.run_structured(..., label="brd-improve", schema=brd_draft_schema())` with the
  size-adaptive turn budget (`cost.scaling.turns_for`), wrapped in `asyncio.wait_for`
  (per-call timeout — the BRD harness has no built-in timeout; wrap here, mirroring the
  enrichment `run_batched` reliability lesson).
- Returns `(BRDDraft, Strategy.single_shot)`. On empty/failed output, raises (so the job
  fails and the prior version is left intact) — does NOT return an empty draft to save.

### `src/cobol_modernizer/brd/pipeline.py` (extend)
`improve_brd_graph_sync(repo_id, instruction, *, client=None, repo_path=None,
model=None, max_turns=None, storage=None) -> BRDResult`
- Mirrors `generate_brd_graph_sync`: resolve client/repo_path/deps; resolve model
  (`resolve_model("brd")`, env-overridable) and the judge model (Haiku, via the existing
  size-tiered judge resolution).
- Load the latest BRD via `BRDStorage`; reconstruct the current BRD (structured if the
  node has `sections`/`evidence_map`, else seed from `html`). If no BRD exists, raise
  (the endpoint maps this to 409 before queueing).
- Run `agenerate_brd_improvement`; build a `BRD`; `ajudge(brd, deps, judge_model)`;
  `render_html`; `storage.save(...)` (new version). Reuse `_log_timing`.

### `src/cobol_modernizer/brd/storage.py` (extend)
- `save(...)`: also persist `sections` (JSON) and `evidence_map` (JSON) on the `:BRD`
  node, taking an added `brd: BRD` (or `sections`/`evidence_map`) parameter. The
  generate path passes its `result.brd`; improve does too.
- `get_latest`/`get` return these fields when present.
- Add `reconstruct_draft(node) -> BRDDraft | None`: build a `BRDDraft` from the stored
  `sections`/`evidence_map`; return `None` (caller falls back to `html`) for legacy
  nodes without structured data.

### `src/cobol_modernizer/controlplane/blueprint.py` (extend)
- `POST /workspaces/{wid}/blueprint/improve`: validate workspace + `ANTHROPIC_API_KEY`;
  require a non-empty `instruction` (else 400); require an existing BRD for the repo
  (else 409 "generate a blueprint first"); start `jobs.runner` job `"blueprint-improve"`
  that calls `improve_brd_graph_sync`. Returns the standard job view (202).
- `GET /workspaces/{wid}/blueprint/improve`: poll the `"blueprint-improve"` job.
- Reuse the existing `GET /blueprint/html` for the (now improved) latest version.

### `web` (extend)
- `api.ts`: `startBlueprintImprove(id, instruction)` → POST with `{instruction}` body;
  `getBlueprintImproveStatus(id)` → GET poll. (Same `EnrichJob`-style `{status,result,error}`.)
- `BlueprintStudio.tsx`: when a BRD result exists, show an instruction `<textarea>` +
  "Improve" button driven by a second `useJob`; while busy show "Improving…"; on done,
  bump a `version` query param on the iframe `src` to force a reload of the new HTML and
  update the displayed version/rating from the job result.

## Error handling & guardrails

- **No existing BRD** → 409 (validated synchronously before queueing).
- **Empty/whitespace instruction** → 400.
- **Agent empty / timeout / exception** → job `failed`; the prior latest version is
  untouched (we only `save()` a valid improved draft). Surfaced via the poll endpoint.
- **Grounding** enforced by the reused `ajudge` groundedness gate (hallucinated refs
  floor accuracy), so an improved BRD that drifts is rated down rather than silently
  trusted.
- **Latency/cost:** size-adaptive turns + `asyncio.wait_for` timeout
  (`BLUEPRINT_IMPROVE_TIMEOUT_S`, sane default) + label instrumentation; Sonnet draft /
  Haiku judge.

## Testing

- **Unit (`agenerate_brd_improvement`, FakeRunner):** the current BRD + instruction reach
  the prompt; returns a valid `BRDDraft`; raises/propagates on empty output (so nothing
  bad is saved).
- **Unit (storage):** `save` persists `sections`/`evidence_map`; `get_latest` returns
  them; `reconstruct_draft` rebuilds a draft and returns `None` for a legacy HTML-only
  node (HTML fallback path).
- **Integration (endpoints, `jobs.runner.inline` + stub improve):** 202 → poll → new
  version; 409 when no BRD; 400 on empty instruction; a failing improve leaves the prior
  version intact (no new version created).
- **Frontend (vitest + MSW):** the instruction box + "Improve" button appear only after a
  BRD exists; improve job → iframe refresh + updated version/rating.

## Out of scope (YAGNI)

- Version browser / diff UI (minimal version UX: show new latest only).
- One-click judge-feedback auto-improve (we chose user-directed instruction).
- Section-targeted editing UI (the instruction steers; the agent edits where relevant
  and emits the full BRD).
- Backfilling structured `sections` onto pre-existing BRD nodes (handled by the HTML
  fallback in `reconstruct_draft`).

## Open questions

None blocking. The improve agent's turn floor/timeout defaults and whether to add a
dedicated `BRD_IMPROVE_MODEL` env (vs reusing `BRD_AGENT_MODEL`) are implementation
details with sane defaults, env-overridable.
