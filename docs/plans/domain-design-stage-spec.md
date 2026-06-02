# Domain Design Stage — Design Spec

> **Status:** design (brainstormed 2026-06-02, approved). This is the *spec* — the binding
> description of WHAT the Domain Design stage is and the contracts it must honor. The
> task-by-task implementation plan is produced separately (writing-plans) and references
> this doc as canonical for schemas and gates.
>
> **One-line:** turn the BRD + the deterministic code graph into a business-capability-aligned
> decomposition — bounded contexts, a per-context module-vs-microservice recommendation with a
> strangler-fig extraction order, and full DDD tactical design per context — replacing today's
> mechanical 1:1 writer→slice mapping as the design source of truth.

---

## 1. Motivation

COBOL is procedural (records + paragraphs); the target is modern OO Spring Boot. Today's `design`
stage (`controlplane/analysis.py::_compute_designs`) emits **one service "slice" per writer
program** and assigns a bounded context from a **hardcoded** `RESOURCE_CONTEXT` dict in
`design/context_map.py` (`account_management`, `card_management`, `transaction_processing`,
`bill_pay_reporting` — CardDemo-specific). That is two problems at once:

1. **Like-for-like monolith.** A 1:1 program→service mapping reproduces the COBOL structure in
   Java. No business-capability grouping, no judgment about what should be one service vs many.
2. **CardDemo hardcoding** — violates the project's "keep it generic, no CardDemo hardcoding" rule.

Separately, the existing **"Improve"** button (design *enrichment*, `enrichment/design.py`) only
*annotates* the deterministic design with LLM prose (ADR context/consequences, component
sentences, API-surface sketch) and stores the result **in-memory only** (`controlplane/jobs.py`
`JobRunner._jobs` dict) — so it never changes the design, the additions are easy to miss, and the
result is lost on restart. It is not a decomposition step.

This stage replaces that gap with a real decomposition + OO-design step.

## 2. Goals & non-goals

**Goals**
- Derive bounded contexts *generically* from the BRD + graph (no resource→context dictionary).
- Per context, recommend `module` (in a modular monolith) vs `microservice`, with a transparent
  score from the **existing** seam signals, plus a strangler-fig extraction order.
- Per context, produce **full DDD tactical design**: aggregates, entities, value objects, domain
  services, repository interfaces, domain events, API surface, and an explicit
  COBOL-copybook/record → domain-object mapping (the anti-anemic step).
- Persist every version durably (fixes the ephemeral "Improve" problem) with an `evidence_map`.
- Stay verifiable: boundaries are LLM-proposed, but **deterministic gates enforce hard invariants**
  and **every claim cites real graph entities**.

**Non-goals**
- Generating Java (stays in `build`).
- Changing how seam signals or the graph are computed (Phases 1/4 own that).
- Anything CardDemo-specific in code or tests.

## 3. Pipeline placement & relationship to existing stages

```
parse → blueprint(BRD) → seams → [ domain-design  (NEW) ] → plan → build → verify
```

- **Retires** `design/context_map.py`'s hardcoded `RESOURCE_CONTEXT` / `assign_context`. Contexts
  are derived per run.
- **Demotes but keeps** `_compute_designs` (writer-slice + data-ownership gate): it becomes (a) a
  grounded *input signal* to Phase 1 (it already computes `owned_resources` + the data-ownership
  judge) and (b) a no-LLM *fallback* when the LLM is unavailable. With the hardcoded dict removed,
  the fallback assigns a context *generically* — one context per maximal data-ownership cluster
  (programs grouped by the resources they exclusively write), named from the dominant resource —
  so the fallback is also CardDemo-free. The cockpit design view switches to the new
  `:DomainDesign` artifact.
- `plan` (`planner/`) still derives a story per seam, but each story is **tagged with its context +
  topology decision** (`Story.context`, `Story.topology`), and delivery waves respect the
  per-context extraction order. The Story schema gains two optional fields; the DAG derivation is
  unchanged. This keeps Phase-4/5/6 downstream contracts intact.

## 4. Inputs (all already exist — no new ingestion)

| Input | Source | Used for |
|---|---|---|
| BRD `sections[].body_markdown`, `evidence_map` | `:BRD` Neo4j node (`controlplane/blueprint.py`) | business-capability alignment + naming |
| Writers → owned resources | `WRITES` edges (Cypher) | data ownership, coverage gate |
| Cross-program reads of owned resources | `READS` edges | inter-context dependencies, identity-drift |
| Call graph | `CALLS` edges | coupling evidence |
| Co-change clusters | `CO_CHANGED_WITH` edges (git) | conceptual-coupling evidence |
| Per-program seam signals (`isolation`, `data_ownership`, `business`, `risk`) | `seam/signals.py` | topology recommendation |
| Deterministic writer-slices | `_compute_designs` | grounded baseline / fallback |

A new **`graph_coupling_summary(slug)`** read function (Cypher-only, in `domain/inputs.py`)
assembles a compact JSON of the above for the Phase-1 prompt. It MUST be bounded in size (top-N
programs by `business`, resource adjacency, co-change edges above a confidence floor) so the
decomposition prompt stays well under the context window — see §11.

## 5. Phase 1 — Decomposition (one gated LLM call)

`domain/decompose.py::decompose(...)`. The LLM proposes, from the BRD + `graph_coupling_summary`,
a `DecompositionMap`. **The LLM owns the boundaries; gates own correctness.**

### 5.1 Output schema (`domain/schema.py`)

```python
class ContextDependency(BaseModel):
    target: str                      # context name it depends on
    style: Literal["sync", "async"]  # call vs event
    reason: str                      # grounded justification
    cited_refs: list[str]            # graph entities evidencing the dependency

class TopologyDecision(BaseModel):
    deployment: Literal["module", "microservice"]
    score: float                     # extract-as-service score (see 5.2)
    inputs: dict[str, float]         # the signal values that produced score (transparency)
    rationale: str

class BoundedContextDecl(BaseModel):
    name: str                        # derived, e.g. "Posting" — NOT from a dictionary
    business_capability: str         # one-line capability, aligned to a BRD section
    member_programs: list[str]       # writer (and reader) programs in this context
    owned_resources: list[str]       # resources this context writes (exclusive)
    depends_on: list[ContextDependency]
    topology: TopologyDecision
    extraction_rank: int             # 1 = extract first (strangler-fig)
    identity_drift: bool             # other contexts READ this context's owned data
    cited_refs: list[str]            # BRD requirement ids + graph entities

class DecompositionMap(BaseModel):
    repo_slug: str
    contexts: list[BoundedContextDecl]
    unassigned_programs: list[str]   # must be empty to pass the coverage gate
    cited_refs: list[str]
```

### 5.2 Topology recommendation (deterministic, computed — not LLM)

Per context, aggregate the member programs' seam signals (mean), then:

```
extract_score = 0.30·isolation_mean + 0.25·data_ownership_mean
              + 0.20·business_mean  − 0.15·risk_mean
              − 0.10·normalized_inbound_dependency_count
deployment = "microservice" if extract_score ≥ EXTRACT_THRESHOLD else "module"
```

`EXTRACT_THRESHOLD` is a module-level constant (tunable, default ~0.55). `inputs` records each term
so the cockpit can show *why*. Identity-drift contexts (data other contexts read) are biased toward
`module` / late `extraction_rank` ("keep shared / extract last"). Weights mirror the established
Phase-4 seam formula deliberately, for consistency. **The LLM does not choose deployment**; it only
declares membership/capability — the score is computed in Python from real signals.

### 5.3 Extraction order (strangler-fig)

`extraction_rank` is assigned deterministically after the LLM returns: topologically order contexts
by inbound data-dependency readiness (leaf contexts that nothing reads-from first), tie-broken by
`business_mean` desc then `risk_mean` asc. Identity-drift writers ranked last.

### 5.4 Phase-1 gates (deterministic; violation → bounded repair re-prompt)

Mirrors the BRD judge/repair loop (`brd/pipeline.py`), capped at `DOMAIN_MAX_REPAIRS` (default 2):

1. **Coverage** — every writer program from `WRITES` assigned to exactly one context;
   `unassigned_programs` empty.
2. **Data-ownership** — no resource appears in two contexts' `owned_resources`.
3. **Groundedness** — every `member_programs` / `cited_refs` entry resolves to a real graph entity
   (reuse `enrichment/base.py::ground_refs`).
4. **Acyclicity** — the `depends_on` graph is a DAG.

On failure, re-prompt with the specific violations listed; after the cap, fail the job with the
violation report (no silent partial result).

## 6. Phase 2 — Per-context tactical DDD (parallel agents, map-reduce)

`domain/tactical.py`. One focused agent **per context** (like BRD subsystem drafting). Small bounded
job → deep output, no turn-cap starvation, parallelizable via the existing fan-out pattern.

### 6.1 Output schema (per context)

```python
class CobolMapping(BaseModel):
    cobol_ref: str                   # copybook/record/paragraph qualified_name
    maps_to: str                     # aggregate/entity/value-object/method name
    note: str                        # e.g. "2800-UPDATE-ACCOUNT-REC folds into Account.post()"

class Aggregate(BaseModel):
    name: str
    root_entity: str
    invariants: list[str]
    entities: list[str]
    value_objects: list[str]
    methods: list[str]               # behavior (anti-anemic): paragraphs → methods

class ContextDesign(BaseModel):
    context: str                     # FK to BoundedContextDecl.name
    aggregates: list[Aggregate]
    value_objects: list[str]
    domain_services: list[str]
    repositories: list[str]          # interface names (one per aggregate root, typically)
    domain_events: list[str]
    api_surface: str                 # commands/queries/REST sketch
    cobol_mapping: list[CobolMapping]
    cited_refs: list[str]
```

The agent is explicitly instructed to **fold paragraph behavior into aggregate methods** rather than
emit CRUD setters over copybook fields (the anti-anemic rule), grounded ONLY in the context's owned
programs/resources.

### 6.2 Phase-2 gate (per context)

- **Groundedness** — refs resolve.
- **Data coverage** — every `owned_resources` item appears in some aggregate or repository (no
  dropped data store).
- **Anti-anemic check (heuristic)** — flag (warn, not hard-fail) contexts where aggregates have
  invariants/methods count == 0 while owning ≥1 resource; surfaced in the rating.

## 7. Phase 3 — Assemble, validate, persist

`domain/assemble.py`. Combine `DecompositionMap` + all `ContextDesign`s into a `DomainDesign`.

### 7.1 Cross-context invariants
- No aggregate name spans two contexts.
- Every inter-context `depends_on` has a noted integration style (ACL for `sync`, event for `async`)
  — reference the `domain_events` of the producer where `async`.

### 7.2 Persistence — `:DomainDesign` Neo4j node (mirrors `:BRD`)
`controlplane/domain.py` (new), modeled on `controlplane/blueprint.py`:

```
(:DomainDesign {
   id, repo_slug, version, rating, weighted_score,
   contexts_json, designs_json, topology_json, extraction_order_json,
   evidence_map, model, strategy, token_usage, html_path, created_at
})-[:OF_REPO]->(:Repository)
```

Versioned (monotonic `version` per repo); `GET` returns the latest. `evidence_map` is the union of
all `cited_refs` keyed by element id, floored by the groundedness gate. A self-contained HTML render
(`domain/render.py`) is written for the cockpit iframe/detail, consistent with the BRD HTML pattern.

## 8. Refine loop ("Improve", done right)

`POST …/domain-design/refine {instruction}` re-runs Phases 1–3 with the user's instruction prepended
to the Phase-1 system context ("split billing from payments", "merge X and Y"), producing a **new
persisted version**. The cockpit shows a diff vs the prior version (added/removed contexts, topology
flips, moved programs). Unlike today's enrichment: results are **persisted**, **versioned**, and
**actually change the design**.

## 9. API + control plane

All on `controlplane/analysis.py` (the shared router), reusing `JobRunner` + `SdkAgentRunner`:

| Method | Path | Notes |
|---|---|---|
| POST | `/workspaces/{wid}/domain-design` | 202; background job; Phase-2 fan-out via existing parallel pattern |
| GET | `/workspaces/{wid}/domain-design` | latest persisted version (NOT in-memory job state) |
| POST | `/workspaces/{wid}/domain-design/refine` | 202; `{instruction}`; new version |
| GET | `/workspaces/{wid}/domain-design/html` | rendered HTML (cockpit) |
| SSE | existing `…/runs/{runId}/events` | progress: decompose → per-context → assemble |

The `GET` reads the persisted `:DomainDesign`, so a finished design survives restarts (the
job-runner is only for in-flight progress). Job kind: `"domain-design"`.

## 10. Cockpit screen — `DomainStudio`

`web/src/components/screens/DomainStudio.tsx` (+ `lib/api.ts` helpers, `useJob`). Replaces/augments
the current `DesignStudio`:

- **Context map**: boxes per context + dependency arrows (solid = sync/ACL, dashed = async/event).
- **Per-context card**: a `module`/`microservice` badge with the `score` + `inputs` breakdown
  (transparent), `extraction_rank`, `business_capability`, owned resources, identity-drift flag.
- **Extraction roadmap**: contexts ordered by `extraction_rank` (the strangler-fig sequence).
- **DDD detail (expandable)**: aggregates (root + invariants + methods), value objects, domain
  services, repositories, domain events, API surface, and the COBOL→domain mapping table.
- **Refine box**: instruction input → `refine` → poll → diff highlight vs previous version.

## 11. Determinism, generality, grounding (project DNA)

- **No hardcoded contexts** anywhere. Names/capabilities are derived; the topology score is computed
  from real signals; the resource→context dict is deleted.
- **Gates are deterministic** and enforce the hard invariants (§5.4, §6.2, §7.1).
- **Every claim cites real graph refs**, floored by `ground_refs` — the artifact is auditable.
- **Prompt-size discipline**: `graph_coupling_summary` is bounded (top-N by business, adjacency,
  co-change confidence floor). Phase 2's per-context prompts carry only that context's slice of the
  graph, which is what makes the deep design fit — and is the direct fix for the `HIT_TURN_CAP`
  shallowness seen in the single-batch enrichment.

## 12. Testing

- **Injectable runner**: stub `AgentRunner` returning fixture `DecompositionMap` / `ContextDesign`
  (the existing seam/BRD test pattern) — orchestration tested with zero LLM.
- **Pure unit tests per gate**: coverage, data-ownership, groundedness, acyclicity, data-coverage,
  anti-anemic heuristic, topology-score math, extraction-order ordering.
- **Golden decomposition** on a *small synthetic* fixture repo (two writers, one shared reader) —
  asserts two contexts, correct identity-drift flag, correct extraction order. **No CardDemo
  identifiers asserted in code.**
- **Persistence round-trip**: write `:DomainDesign` v1, refine → v2, `GET` returns v2; restart-safe
  (read path independent of `JobRunner`).
- **API**: 202 + poll-to-done + persisted-GET, mirroring existing analysis-endpoint tests.

## 13. Module layout (proposed, new)

```
src/cobol_modernizer/domain/
  __init__.py
  schema.py        # DecompositionMap, BoundedContextDecl, TopologyDecision,
                   # ContextDesign, Aggregate, CobolMapping, DomainDesign
  inputs.py        # graph_coupling_summary(slug) — bounded Cypher read
  decompose.py     # Phase 1: LLM decompose + topology score + extraction order
  tactical.py      # Phase 2: per-context tactical DDD agents (parallel)
  gates.py         # all deterministic gates (coverage/ownership/grounded/acyclic/coverage/anemic)
  assemble.py      # Phase 3: cross-context invariants + DomainDesign assembly
  render.py        # self-contained HTML for the cockpit
src/cobol_modernizer/controlplane/
  domain.py        # :DomainDesign Neo4j persistence (mirrors blueprint.py)
  analysis.py      # +4 endpoints + the "domain-design" job
web/src/components/screens/DomainStudio.tsx
```

`design/context_map.py` hardcoded dict deleted; `_compute_designs` kept as fallback/input.

## 14. Risks & open items

1. **BRD is free-text markdown** — capability alignment depends on BRD quality. Mitigation: the
   decomposition is grounded in the *graph* primarily; BRD drives naming/capability labels. If a
   later phase makes the BRD emit structured capabilities, Phase 1 can consume them directly.
2. **Plan-schema ripple** — adding `Story.context` / `Story.topology` touches `planner/schema.py`
   and any consumer. Keep both optional; default `None` preserves existing behavior.
3. **Cost** — Phase 2 is N parallel agent calls (one per context). Bound N (merge tiny contexts
   below a size floor in Phase 1) and run under the existing per-workspace cost cap / kill-switch.
4. **`graph` gate dependency** — relies on a reasonably complete graph; degrade gracefully when
   `CO_CHANGED_WITH` churn edges are absent (the term drops to 0, as in Phase 4).

## 15. Acceptance criteria

- Running domain-design on a multi-writer repo yields **fewer contexts than writer programs** (real
  grouping, not 1:1) with every writer covered and no shared-write violations.
- Each context carries a computed `module`/`microservice` decision with visible score inputs and a
  strangler-fig `extraction_rank`.
- Each context has ≥1 aggregate with ≥1 invariant/method and a COBOL→domain mapping (anti-anemic).
- The artifact is **persisted + versioned**; `GET` survives a server restart; `refine` produces a
  new version with a visible diff.
- No CardDemo-specific identifiers in `domain/` code or tests; `RESOURCE_CONTEXT` dict removed.
- All gates have passing unit tests; orchestration tested with an injected stub runner.
