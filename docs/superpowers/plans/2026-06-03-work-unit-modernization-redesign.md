# Work-Unit Modernization Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> or `superpowers:subagent-driven-development` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the COBOL-to-Java/Spring Boot pipeline so large codebases such as
`source_code_to_analyse/aws-mf-mod-carddemo` complete reliably, with bounded token
spend, resumable progress, verifiable artifacts, and no hidden partial success. This
is an architectural rewrite of the orchestration/context layer, not a blank-repo
rewrite.

**Decision:** Keep the current repo. Do not rewrite from scratch. Preserve the parser,
Neo4j graph ingestion, artifact schemas, cockpit, and story-sliced codegen direction.
Replace the stage execution model with a deterministic work-unit pipeline where LLMs
are bounded workers over explicit context packs.

**SDK strategy:** Do not make Claude Agent SDK, DeepAgents, or OpenAI Agents SDK the
core architecture. Add an internal `AgentRuntime` adapter boundary and keep Claude as
the first adapter. OpenAI Agents SDK can be added for tracing/sessions/guardrails;
DeepAgents can be used for optional review/repair workflows. The product contract is
the work-unit ledger + context packs + gates, not the vendor runtime.

---

## Architecture

### Core principles

1. **Graph first, deterministic first.** Python/Neo4j computes anything derivable:
   entrypoints, CICS/SQL/file access, reader/writer ownership, seam scores, dependency
   DAGs, copybook layouts, and evidence refs.
2. **LLM calls are work units.** Every expensive generation task is split into small,
   persisted, independently retryable units.
3. **Context packs are explicit artifacts.** A model receives the exact BRD/story/DDD/
   design/source evidence needed for one unit. No whole-repo prompts.
4. **Gates fail loud.** Partial outputs can be persisted as partial, but a required
   stage cannot silently become `done` after turn-cap, timeout, or fallback output.
5. **Cache by input hash.** If a unit's inputs are unchanged, reuse the previous
   verified output.
6. **Provider-agnostic runtime.** Agent SDKs are adapters behind a stable internal
   result shape.

### Target pipeline order

1. Ingest COBOL/copybooks/JCL/CICS/SQL.
2. Normalize graph facts.
3. Build static capability inventory.
4. Generate BRD by capability work units.
5. Generate backlog by BRD-requirement groups.
6. Generate domain design by bounded-context/aggregate units.
7. Identify seams deterministically; use LLM only for rationale.
8. Generate implementation plan and technical design by service/story-wave units.
9. Scaffold Spring Boot deterministically.
10. Generate code story-by-story, test-first.
11. Verify with build, architecture, lineage, and equivalence gates.

### New shared components

| Component | Responsibility |
| --- | --- |
| `WorkUnitLedger` | Durable unit status, input hash, attempts, token/cost, payload, failure cause. |
| `ContextPackBuilder` | Builds bounded, provenance-rich inputs per unit. |
| `AgentRuntime` | Provider-neutral structured-call interface. |
| `StageOrchestrator` | Plans units, schedules bounded concurrency, caches by hash, retries, reduces outputs. |
| `GateRunner` | Deterministic validation for each artifact type. |
| `BenchmarkHarness` | Measures wall time, calls, tokens, cost, cache hits, turn caps, coverage. |

---

## Work-Unit Model

Each expensive unit is stored with:

```text
id
workspace_id
repo_slug
stage
unit_type
unit_key
input_hash
status
attempt
model
timeout_s
max_turns
token_usage_json
cost_usd
started_at
finished_at
payload_json
error_cause
parent_unit_ids_json
artifact_id
```

Allowed statuses:

```text
pending
running
succeeded
failed
skipped
cached
deferred
```

The unique cache key is:

```text
workspace_id + stage + unit_type + unit_key + input_hash
```

---

## Stage Redesign

### BRD

Work units:
- capability summary
- functional requirements per capability
- non-functional/risk/constraints pass
- reduce/merge
- groundedness judge

Gates:
- every requirement cites real refs
- every cited ref exists
- no invented IDs
- coverage threshold per capability

### Backlog

Work units:
- epics from BRD capability group
- stories per epic
- acceptance criteria per story group
- dependency derivation deterministic
- top-up uncovered BRD requirements

Gates:
- every BRD requirement covered
- every story has ACs
- every AC cites evidence
- story DAG acyclic

### Domain Design

Work units:
- context decomposition
- aggregate discovery per context
- command/use-case model per aggregate
- persistence mapping per owned resource
- domain events and integration boundaries
- COBOL-to-domain mapping

Gates:
- every story maps to one context
- every writer resource has one owner
- every aggregate has at least one grounded method/invariant
- no context emits invented refs

### Seams

Mostly deterministic:
- reader/writer classification
- data ownership
- isolation
- fan-in/fan-out
- testability
- risk

LLM unit:
- rationale only, over precomputed seam evidence

Gates:
- ranked seams have deterministic score inputs
- identity-drift writers are flagged
- reader-only candidates are distinguishable from writers

### Technical Design

Work units:
- service design per bounded context
- API contracts per story group
- persistence contracts per owned resource
- integration contracts per dependency
- deployment/ADR summary

Gates:
- every story delivered by a service
- every service cites context/story/evidence
- every writer resource has one technical owner
- access patterns are valid enum values

### Codegen

Existing story-sliced direction is kept, but each story becomes a ledger-backed unit.

Work units:
- tests for story
- implementation for story
- repair attempt
- build/quality result
- equivalence result

Gates:
- tests cite AC IDs
- production files cite story and COBOL refs
- Maven/Spring tests pass or are explicitly `generated-unverified`
- equivalence passes for fixture-backed stories

---

## Implementation Phases

### Phase 1: Ledger Foundation

- [x] Add `WorkUnitStatus`, `WorkUnit`, and `WorkUnitLedger` domain models.
- [x] Add persistence table/migration for work units.
- [x] Add repository methods: `create`, `mark_running`, `mark_succeeded`,
      `mark_failed`, `find_cached`, `list_by_stage`.
- [x] Add unit tests for cache-key semantics and status transitions.
- [x] Add API read endpoint for stage work-unit progress.

### Phase 2: Runtime Adapter

- [x] Add `AgentRuntime` protocol with provider-neutral `AgentResult`.
- [x] Wrap current `SdkAgentRunner` behind `ClaudeAgentRuntime`.
- [x] Preserve existing `run_batched_result` behavior through the adapter.
- [x] Add tests with a fake runtime for timeout, turn-cap, structured success,
      and token accounting.

### Phase 3: Context Pack Framework

- [x] Add `ContextPack` schema with `input_hash`, `refs`, `sections`, `source_slices`.
- [x] Add deterministic builders for backlog, domain, technical design, and story codegen.
- [x] Add max-size diagnostics without silently truncating required evidence.
- [x] Add tests for stable hashes and provenance preservation.

### Phase 4: Domain Design First

This is the first heavy stage to port because current logs show `HIT_TURN_CAP` and
150-225s calls.

- [x] Convert `domain.decompose` to typed result and ledger unit.
- [x] Split `domain.tactical` into aggregate/use-case/persistence/event/mapping units.
- [x] Add bounded concurrency and per-unit retries.
- [x] Add `incomplete` stage result when required units fail.
- [x] Add cockpit progress from ledger units.

### Phase 5: Backlog and Technical Design Port

- [x] Move existing decomposed backlog units onto the ledger.
- [x] Move technical-design per-context calls onto the ledger.
- [x] Replace fallback-to-done behavior with `partial`/`incomplete` gate state.
- [x] Add cache reuse by input hash.

### Phase 6: Codegen and Verify Port

- [x] Persist aggregate story codegen work units.
- [x] Persist story test/implementation/repair/build sub-units.
- [x] Persist per-story equivalence sub-units.
- [x] Add restart-fresh versus resume mode explicitly.
- [x] Add per-story equivalence units.
- [x] Add per-story verify repair units.

### Phase 7: Benchmark Harness

- [x] Add benchmark command for `carddemo-mini`.
- [x] Add explicit guard that skips `aws-mf-mod-carddemo` unless large-repo
      benchmarking is deliberately re-enabled.
- [x] Record wall time, tokens, cost, calls, turn caps, cache hits, coverage,
      and pass/fail gate state per stage.
- [x] Emit benchmark output as a generated JSON artifact under `benchmark_out/`.

---

## Acceptance Criteria

- [x] Large stages expose unit progress, not opaque long-running jobs.
- [x] A timeout/turn-cap on one unit does not erase the whole stage.
- [x] Required stage outputs cannot be marked `done` if required units failed.
- [x] Re-running unchanged units uses cached verified outputs.
- [x] Domain design no longer performs one broad tactical call per context.
- [x] Backlog, DDD, technical design, and codegen share the same unit status model.
- [x] Agent provider can be changed by adapter without rewriting stage logic.
- [x] `aws-mf-mod-carddemo` benchmark is explicitly deferred by user request to
      avoid large-repo token burn; `carddemo-mini` has benchmark numbers first.

## Non-Goals

- Do not rewrite parser/extractor/Neo4j ingestion from scratch.
- Do not migrate the whole app to DeepAgents or OpenAI Agents SDK in one step.
- Do not remove Claude Agent SDK until an adapter replacement is proven.
- Do not add broad whole-repo prompts.
- Do not hide required failures behind deterministic fallbacks marked as complete.

## Implementation Mode Entry Point

Start with Phase 1. The first patch should add a pure tested work-unit ledger model
and repository. After that, port Domain Design because it is the slowest confirmed
stage from the user logs.
