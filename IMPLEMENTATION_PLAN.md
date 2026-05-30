# COBOL → Java/Spring Boot Migration Platform — Implementation Plan

> Validated against the two design docs in `docs/`, the partial implementation at
> `/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0`,
> and six Martin Fowler legacy-modernization articles.
> Headline workload: **AWS CardDemo** (≈39 programs / 41 copybooks).
> Goals: **performant, token-economical, scales to large COBOL estates.**

---

## 0. Executive summary of the validation

Both design docs are **architecturally sound and unusually well-aligned with Fowler doctrine**. The platform correctly inverts the naive "code-gen agent" framing into a **deterministic graph core + bounded agents + hard human gates**, and treats a *validated functional blueprint (BRD), not Java code,* as the first-class deliverable (Fowler: *black-box-to-blueprint*).

The catch is **scope realism**. The designs are coherent with the partial impl at the **analysis tier** (graph ingestion, map/reduce BRD, LLM-as-judge, groundedness gate, model tiering, read-only graph tools — all working today) but **mostly fiction at the delivery tier**. Concretely:

| Capability | Status in partial impl |
|---|---|
| ProLeap COBOL → AST → JSON → Neo4j (Program/Section/Paragraph/Copybook + CALLS/CONTAINS/IMPORTS) | **WORKING** |
| Map/reduce BRD + LLM judge + groundedness gate + retry | **WORKING** |
| Model tiering `resolve_model(role)` (Haiku/Sonnet/Opus), worker+advisor budget, prompt caching, cost buckets | **WORKING** |
| Graph-as-context compression (`get_source_slice` reads only `start_line..end_line`) | **WORKING** |
| **Data-flow / IO edges** (DataItem, MOVE, READS/WRITES, EXEC CICS, EXEC SQL, GO TO) | **MISSING — deferred to v2** |
| **Seam discovery / scoring** | **MISSING** (and depends on the absent edges above) |
| **COBOL → Java codegen, build lab, ArchUnit/SpotBugs** | **MISSING — 100% net-new** |
| **Equivalence lab / COBOL execution / dual-run** | **MISSING — execution strategy unspecified in both docs** |
| **CardDemo run end-to-end** | **NEVER RUN** — no perf/scale/error-resilience benchmark |
| UI | **2 pages / 8 components**, not the designed 11-stage cockpit |

**The single highest-severity finding:** the design's central differentiator — deterministic, graph-based **seam discovery** — is scored on `data_ownership`, `isolation`, `testability`, and `risk` signals that **require data-flow / file-IO / CICS edges the v1 walker does not produce.** Per Fowler's *uncovering-mainframe-seams*, the **reader-vs-writer** distinction is *the* pivotal decision (CDC for readers vs Extract-Product-Lines for writers; identity-drift hazard). Without those edges the platform can compute fan-in/fan-out coupling but **cannot classify a data access as read or write, cannot detect side-effecting handoffs (billing/audit), and would silently fall back to LLM guessing** — reintroducing hallucination risk in a regulated financial domain.

**Verdict:** keep the architecture; re-sequence the build so (1) CardDemo actually runs end-to-end on the existing core, (2) the v2 graph enrichment becomes the *critical path* that unblocks everything, and (3) seam math runs in **Cypher/Neo4j-GDS, never in prompts** — which protects both correctness *and* token economy.

---

## 1. Vision & non-negotiables

**Vision.** A graph-first, agent-driven platform that converts a COBOL estate into a chain of *validated artifacts*: business outcomes → code-context graph → functional blueprint (BRD) → seams → story clusters → Spring Boot services → behavior-verified cutovers. We **build on the working `source_graphs_v1.0` analysis core**; we do not redesign from scratch.

**Non-negotiables** (each traced to a Fowler pattern and to ground truth):

1. **The Neo4j graph is the source of truth; agents read through tools, never raw dumps.** *(Code-as-Data / relevant-subtree.)* Already real — protect it. This is the load-bearing token-economy decision.
2. **Every claim carries lineage; nothing is invented.** *(Preserve Lineage + Triangulate.)* Already real: BRD `evidence_map` + deterministic groundedness gate (`brd_judge.py`) that floors `accuracy=2` on any hallucinated reference. Extend this contract to seams, stories, designs, tests, and generated code.
3. **Strangler-fig, never big-bang; macro before micro.** *(Legacy-displacement via seams; break-monolith.)* One low-risk seam migrated end-to-end and verified, then broaden. Modular monolith by default; promote to microservices only when data ownership + independent release + ops autonomy are proven.
4. **Determinism where determinism is possible.** Seam scoring computed in **Cypher/Neo4j-GDS over real graph edges**, not LLM guessing. The LLM only writes rationale over precomputed evidence.
5. **Outcome parity, not feature parity.** *(uncovering-mainframe-seams.)* Behavior proven by dual-run/golden-master diffing against a *defined* COBOL execution environment; BRDs must separate *required* behavior from *accidental* legacy behavior (avoids the feature-parity trap).
6. **Human-in-the-loop with hard gates.** *(GenAI-as-assistant.)* No stage advances past an unmet gate without explicit, **attributed** risk acceptance (RBAC/approver identity is non-negotiable in a card domain).
7. **Token economy is a first-class budget, not a report.** Model tiering, prompt caching, map/reduce, incremental re-ingest, and **per-workspace/per-run hard cost caps with a kill-switch** (new — closes a named gap).
8. **Preserve the working core verbatim:** `tools=[]`, `setting_sources=[]`, `json_schema` output; read-only Cypher enforcement; single versioned JSON contract as the *only* Python↔Java coupling; COBOL graceful degradation; `parser.py` stays COBOL-agnostic.

---

## 2. Target architecture

```
                          ┌──────────────────── UI (Next.js 15 / React 19) ─────────────────────┐
                          │ Journey Rail · Stage Header+Gates · Workspace · Agent Console · Drawer │
                          └───────────────────────────────────────────────────────────────────────┘
                                                   │ SSE (events) + REST
┌──────────────┐   ┌──────────── FastAPI control plane (extend api.py) ────────────┐
│ COBOL source │   │ repos · jobs · stages · artifacts · approvals · run stream · cost │
└──────┬───────┘   └──┬──────────┬───────────┬────────────┬───────────┬─────────┬────┘
       ▼              ▼          ▼            ▼            ▼           ▼         ▼
┌────────────┐  ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ ┌──────────┐
│ ProLeap     │  │ Graph svc│ │ Moderniz.│ │ Artifact│ │ Build   │ │ Equiv. │ │ Postgres │
│ extractor   │─▶│ Neo4j+GDS│◀│ Agent rt │ │ svc     │ │ Lab     │ │ Lab    │ │ (NEW)    │
│ (+v2 edges) │  │ read-only│ │ SdkRunner│ │ versioned│ │ Java25/ │ │ GnuCOBOL│ │ runs/    │
│             │  │ Cypher   │ │ +graphMCP│ │ HTML/JSON│ │ Maven + │ │ + diff │ │ gates/   │
│             │  │          │ │          │ │          │ │ ArchUnit│ │ harness│ │ approvals│
└────────────┘  └────┬─────┘ └────┬─────┘ └─────────┘ └─────────┘ └────────┘ └──────────┘
                     ▼            ▼
               ┌─────────┐  ┌──────────┐
               │ Neo4j   │  │ Postgres │   Neo4j = code graph only.
               │ (graph) │  │ run+audit│   Postgres = AgentRun/Gate/Artifact/Workspace/Approval/Budget.
               └─────────┘  └──────────┘   + Object store: source snapshots, slices, generated projects, golden files.
```

**Component responsibilities & data flow**

- **COBOL extractor (ProLeap JAR).** v1 (working): Program/Section/Paragraph/Copybook + CALLS/CONTAINS/IMPORTS. **v2 (critical path):** emit `DataItem` (WORKING-STORAGE/LINKAGE + copybook fields), `READS`/`WRITES` (file/VSAM, with mode), `EXECUTES_CICS`/`EXECUTES_SQL` (resource + read/write intent), `MOVES_TO`, `GO TO` control-flow edges. **Single versioned JSON contract remains the only coupling** (bump to `schemaVersion: 2`, mismatch raises).
- **Neo4j + GDS.** Source of truth. Add GDS for centrality/community at scale. Field-level data lives in the graph but is **never materialized into prompts** — seam math runs as Cypher aggregations.
- **Graph-compressed LLM context.** In-process MCP graph server, read-only tools, line-slice retrieval. Per-phase compression: raw traversals → signed summaries + source refs + token budgets.
- **Agentic BRD/spec reverse-engineering.** Map/reduce BRD with judge + groundedness gate + retry (working). Extend the same harness to seam-rationale, story, and design agents.
- **Java/Spring Boot generation.** Per approved story cluster only. TDD: tests from BRD+golden data → code → compile → run → ArchUnit/SpotBugs/Error Prone/Checkstyle → equivalence. Repair loop feeds logs back. "Compilable" is never sufficient.
- **Verification (Equivalence Lab).** GnuCOBOL (batch) + CICS shim/recorded-I/O fixtures (online) vs Spring Boot; diff stdout, file/VSAM effects, DB state with explicit tolerance rules (COMP-3, scale, date, EBCDIC).
- **UI.** 11-stage cockpit, one user-visible Modernization Agent, approval overlay, SSE streaming, Evidence Drawer.
- **Postgres (new).** AgentRun/Gate/Artifact/Workspace/Approval/Budget + audit + RBAC. (Neo4j is for the code graph, not run/audit/version state.)

**Model tiering (`resolve_model(role)`)**

| Work | Model | Why |
|---|---|---|
| Enrichment, ask-codebase | **Haiku 4.5** | High volume, cheapest |
| BRD map workers, seam rationale, story split, code/test gen (triage), equivalence triage | **Sonnet 4.6** | Throughput synthesis |
| BRD reduce/judge, hard decomposition, architecture design, repair-loop hard failures, advisor escalation | **Opus 4.8** | Reserved for planning/judging/hard calls; budgeted (`ADVISOR_MAX_USES`) |

**Caching & incremental ingestion.** Stable system+tool prefixes → cache hits on 2nd+ worker; optional 1h TTL for batch. **Content-hash each program/copybook; skip unchanged; cache enrichment/summaries keyed by `source_hash + prompt_version`.** This also yields a churn overlay for free (Fowler: *decouple what changes frequently*).

---

## 3. Phased roadmap

Ordering principle: land an **end-to-end thin slice on CardDemo early** (one low-fan-in, read-only program → dark-launched Spring Boot service → diff-verified), proving the full machinery before touching ledger/posting logic. Per Fowler *warm up with a decoupled capability* and *migrate in atomic evolutionary steps*.

### Phase 0 — CardDemo baseline + persistence + cost guardrails
- **Goal:** Make the headline workload actually run end-to-end through the *existing* analysis core, and add the missing run/audit substrate.
- **Deliverables:** (a) CardDemo (39/41) ingested → graph → BRD, with a benchmark (parse time, memory, error resilience on injected bad files, nested-copybook depth). (b) Postgres schema for `Workspace/JourneyStage/AgentRun/Artifact/Gate/Approval/Budget`. (c) Per-workspace & per-run **cost caps + kill-switch** in a policy module; Verifier aborts + requests approval on threshold crossing. (d) Content-hash incremental ingestion.
- **Reuses:** `ingestion.py`, `cobol/parser.py`, `brd/pipeline.py`, `brd_judge.py`, `harness.py`, `models.py:resolve_model`, FastAPI `api.py`.
- **Exit criteria:** CardDemo ingests in a benchmarked time with no crash on ≥10 injected parse errors; a grounded BRD renders with a judge score; re-ingest of an unchanged repo re-pays ~0 LLM cost; a synthetic runaway run is killed by the cap.

### Phase 1 — v2 graph enrichment (the critical path; unblocks everything downstream)
- **Goal:** Extend the ProLeap walker so the graph carries the data-flow / IO / CICS-SQL signals seam scoring requires. *Until this exists, Phases 4+ are **blocked**, not "later."*
- **Deliverables:** `DataItem`, `READS`/`WRITES` (mode), `EXECUTES_CICS`/`EXECUTES_SQL` (resource + intent), `MOVES_TO`, `GO TO` edges; JSON contract → `schemaVersion: 2`. A Cypher/GDS library that classifies each data access **reader vs writer**, computes fan-in/fan-out, shared-state coupling, and side-effect (billing/audit) detection.
- **Reuses:** `CobolWalker.java` (extend at the line-36 boundary that currently scopes out data-flow), `ExternalResolver.java`, `cobol/mapping.py`, the JSON-contract pattern.
- **Exit criteria:** On CardDemo, every VSAM access (ACCTDAT/CARDDAT/TRANSACT) is classified reader/writer in-database; CICS I/O for the CICS programs is represented; a Cypher query returns ranked reader-only programs as seam candidates — **with zero LLM in the scoring path.**

### Phase 2 — Thin vertical slice: pick the seam, build the rails (CardDemo account-view)
- **Goal:** Prove the entire pipeline on ONE low-fan-in, read-only program (e.g., account/card view), all the way to a dark-launched Spring Boot service. This is the v1 product acceptance test.
- **Deliverables:** Seam-ranking surfaces the account-view program as a safe first slice; a focused BRD for that slice; a story cluster; a generated Spring Boot service (read path via CDC/replica or anti-corruption adapter); CI/observability; **dark launch** with output diffing.
- **Reuses:** entire analysis core + Phase 1 graph + Phase 0 persistence; `GraphView.tsx` for the explorer.
- **Exit criteria:** the slice runs in parallel with COBOL on captured inputs and **diff-matches** within tolerance; a human approved BRD→seam→story→design→code at each gate; cost stayed under cap.

### Phase 3 — Equivalence Lab foundation (COBOL execution)
- **Goal:** Make outcome-parity real, since dual-run is the linchpin and is currently absent in both designs.
- **Deliverables:** Commit to **GnuCOBOL for batch** + a **CICS shim / recorded-I/O fixtures for online**; define tolerance-rule format and COMP-3/numeric/date precision rules; golden-file capture harness; diff reporting tied to source seam on failure.
- **Reuses:** Phase 2 diff harness, object store for golden files.
- **Exit criteria:** the Phase 2 slice is verified by the Lab (not ad hoc); a deliberately injected numeric-precision defect is caught and produces a defect ticket linked to the source seam.

### Phase 4 — Seam engine + increment planner (broaden)
- **Goal:** Generalize from one slice to a ranked, scored seam backlog and dependency-ordered delivery waves.
- **Deliverables:** Seam scoring `0.25·business + 0.20·isolation + 0.20·testability + 0.20·data_ownership − 0.15·risk` over **Cypher-computed** evidence (LLM writes rationale only); transition-pattern recommendation per seam type (Batch IO→Spring Batch adapter; API/CICS→facade routed by transaction ID; DB reader→CDC, writer→Extract Product Lines + ACL; copybook→canonical DTO + anti-corruption layer). Story planner (INVEST-judged, acyclic DAG); **dead-code/duplicate lens** (COBOL dead-paragraph + capability-level semantic dedup) so *required vs accidental* behavior is **enforced, not asserted**.
- **Reuses:** map/reduce harness, judge pattern, co-change edges for churn overlay.
- **Exit criteria:** CardDemo seam backlog ranked with explainable evidence; identity-drift writers correctly flagged single-system; story DAG is acyclic; a known duplicate capability is flagged.

### Phase 5 — Design + codegen workbench (writer-path slices)
- **Goal:** Migrate a stateful/writer slice (e.g., a posting or balance-update path) under Extract Product Lines + Legacy Mimic write-back.
- **Deliverables:** Service design (modular monolith default; bounded contexts from seams/data-ownership: Account Mgmt, Card Mgmt, Transaction Processing, Bill Pay/Reporting); ADRs; full TDD codegen with ArchUnit/SpotBugs/Error Prone/Checkstyle; repair loop; Legacy Mimic adapter writing results back to the mainframe format.
- **Reuses:** Phases 1–4; Build Lab.
- **Exit criteria:** a writer slice passes compile + tests + architecture rules + equivalence with no identity drift; old COBOL path retired or fully fronted by an anti-corruption layer.

### Phase 6 — Deployment automation + canary, then iterate
- **Goal:** Safe cutover and repeatable broadening.
- **Deliverables:** Docker/CI, smoke/health, perf baseline vs Equivalence Lab, **canary release** with rollback; evolutionary-architecture fitness functions tracking target-state progress.
- **Exit criteria:** one slice canaried to production behind a routing enabling-point with rollback proven; the migration is **stoppable-safe at any commit**.

---

## 4. Token-economy engineering tactics

1. **Graph-as-context (not dump).** Line-slice retrieval via read-only MCP tools; raw source in object store, summaries as node properties. *Defeats whole-codebase ingestion — the single biggest cost lever and the exact anti-pattern Fowler's black-box-to-blueprint warns against.*
2. **Seam math in Cypher/GDS, not prompts.** Reader/writer, fan-in/out, coupling, side-effects computed in-database; the LLM receives ranked summaries + slices only. **Critical:** the v2 graph multiplies nodes/edges 1–2 orders of magnitude (thousands of `DataItem` nodes from 41 copybooks) — keeping that data out of the context window is what stops enrichment from breaking the compression model.
3. **Model tiering** via `resolve_model(role)` — Haiku breadth, Sonnet synthesis, Opus only for reduce/judge/hard-failure/advisor (budgeted `ADVISOR_MAX_USES`, off by default).
4. **Worker+advisor escalation** — cheap workers escalate one hard call (≤700 tokens) to Opus, cutting expensive judge-retry loops.
5. **Prompt caching** — stable system+tool prefixes; optional 1h TTL for batch; 4-bucket token + `total_cost_usd` tracking already wired.
6. **Map/reduce with bounded fan-out** — community detection capped (`BRD_MAX_SUBSYSTEMS=12`); subagents only for independent scopes (one subsystem/seam/story-cluster/service-module).
7. **Dedup/memoization** — content-hash + `prompt_version` cache keys; capability-level semantic dedup so duplicate COBOL logic is migrated once.
8. **Incremental re-ingest** — skip unchanged programs/copybooks; recompute only affected subgraphs; reuse stored summaries.
9. **Scope expensive non-token work** — equivalence dual-runs one approved seam/story-cluster at a time (the compute/data sink is the Lab, not the LLM).
10. **Cost caps + kill-switch** — per-workspace and per-run hard budgets in the policy engine; UI surfaces the *cap*, not just the running total.

---

## 5. Verification & behavior-parity strategy

- **The BRD is the oracle.** Required behavior (validated, SME-confirmed, grounded) is the contract; *accidental legacy behavior* (dead code, quirks) is explicitly excluded via the dead-code/dedup lens. Tests assert the BRD, not the COBOL line-by-line.
- **Characterization tests from captured behavior.** Per seam, capture representative COBOL inputs/outputs (Feathers-style) before flipping any enabling point.
- **Golden-master dual run.** GnuCOBOL (batch) and Spring Boot run the same fixtures; diff stdout, file/VSAM effects, and DB state. Online flows use a CICS shim or recorded-I/O fixtures.
- **Tolerance rules are explicit.** COMP-3 packed-decimal, numeric scale, date formats, EBCDIC. A failing diff produces a defect ticket linked to its source seam.
- **Outcome parity, not feature parity** — compare *outcomes over time* (external-observer + intermediary views).
- **Hard gates, in order:** Parse → Graph → BRD (groundedness floor) → Stories (acyclic DAG) → Design (service owns its data) → Code (Java compile + Spring Boot tests + ArchUnit + SpotBugs/Error Prone/Checkstyle) → Equivalence (golden-master within tolerance) → Deploy (smoke/health/perf/rollback).
- **Dark launch → canary** before cutover; **Legacy Mimic** write-back keeps un-migrated COBOL running; **identity-drift writers stay single-system** until fully extracted.

---

## 6. UI workstream

- **Shell:** continue from `source_graphs_v1.0/web` (Next.js 15 App Router, React 19, Tailwind). Routes: `/workspaces`, `/workspaces/[id]/journey/[stage]`, `/workspaces/[id]/artifacts/[artifactId]`. Keep agent execution in FastAPI, never in Next server functions.
- **Five-region cockpit:** Journey Rail (11 stages, status colors) · Stage Header+Gates (status pills + **cost-vs-cap** pill) · Main Workspace (graph / BRD / seam matrix / story DAG / design canvas / build run / equivalence report) · Agent Console (single user-visible Modernization Agent; readable tool-call events, full logs inspectable) · Evidence Drawer (source spans, graph nodes, JCL steps, copybooks, fixtures, runtime observations, judge feedback, lineage).
- **Key screens:** Portfolio Dashboard, Repository Intake, Graph Explorer (reuse `GraphView.tsx` + COBOL filters, seam overlay, path finder, lineage), Blueprint Studio, Seam Studio (blast radius, reader/writer, testability), Increment Planner, Design Studio, Build Lab, Equivalence Lab.
- **HITL checkpoints (5-mode operating model):** read-only (no approval) → artifact generation (approve BRD/seams/stories/designs before codegen) → workspace mutation (stage approval + scoped workspace) → build/verify (gate not overridable without **attributed** risk acceptance) → deployment (explicit approval). RBAC: approver identity required.
- **Streaming:** SSE for AgentRun events (plans, tool calls, costs, results, failure states); checkpointed/resumable sessions pinned to a graph snapshot + artifact versions.
- **Approval overlay:** on write/expensive-job/network/code-execution/deploy, surface command, path, risk, expected result, and **budget impact**.

---

## 7. Risks & open questions

1. **v2 graph explosion vs compression model (top engineering risk).** Field-level `DataItem` + MOVE/CICS edges multiply nodes/edges 1–2 orders of magnitude; `networkx` in-process clustering and `GET /api/graph?limit=200` will not scale. **Mitigation:** seam math in Cypher/GDS, never in prompts; never materialize field-level data into context.
2. **Seam determinism depends entirely on Phase 1.** If v2 edges slip, seam scoring silently falls back to LLM guessing — reintroducing hallucination/identity-drift hazard in a financial domain. **Mitigation:** Phases 4+ are *blocked*, not deferred, until Phase 1 exits.
3. **COBOL execution for equivalence is unproven.** GnuCOBOL dialect fidelity vs the mainframe (CICS, VSAM semantics, COMP-3) is uncertain. **Open:** is a recorded-I/O fixture approach sufficient for online flows, or is a true emulator / mainframe test env needed for NFR parity?
4. **CardDemo never run end-to-end.** Performance, nested-copybook depth, multi-error resilience all untested — Phase 0 must de-risk this first.
5. **Scope realism.** ~80% of the delivery tier is greenfield; treat Phases 3–6 as new build, not increments on existing code.
6. **Clean-room / context-poisoning** is absent from both designs — recommend adopting (don't tell the agent the expected answer) given the regulated domain.
7. **Other open questions:** quantified judge thresholds and equivalence tolerances (undefined); VSAM/DB2→relational data-migration strategy (undetailed); per-client seam-weight calibration; cross-repo/system-library CALL enrichment (dangling stubs today); concurrency limits and SLAs.

**Reusable core to protect (do not regress):** graph-as-context-compression, `resolve_model(role)` tiering, worker+advisor budget, groundedness-floor judge, `tools=[]`/`setting_sources=[]`/`json_schema` determinism, read-only Cypher enforcement, single-JSON-contract language-extractor isolation, COBOL graceful degradation.

---

## Appendix — source files this plan builds on

Partial impl (`/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0`):
`src/code_context_graph/agent/harness.py`, `.../agent/models.py` (`resolve_model`), `.../brd/pipeline.py`, `.../agent/brd_judge.py` (groundedness gate), `.../agent/graph_tools.py`, `.../ingestion.py`, `.../cobol/mapping.py`, `.../api.py`, `web/src/components/GraphView.tsx`; extractor `tools/cobol-extractor/src/main/java/com/codecontextgraph/cobol/CobolWalker.java`; design plans under `docs/superpowers/plans/`.

Designs under review: `docs/cobol-modernization-platform-design.html`, `docs/ui-agentic-architecture.html`.

Fowler references: patterns-legacy-displacement, legacy-modernization-gen-ai, black-box-to-blueprint, LegacySeam, uncovering-mainframe-seams, break-monolith-into-microservices.
