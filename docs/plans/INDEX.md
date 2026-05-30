# Master Index & Delivery Roadmap

> **For agentic workers:** this is the navigation + sequencing authority over the foundation doc and the 8 phase/workstream plans. Read `00-foundation-and-architecture.md` first (it is the binding spec for all shared contracts), then the phase plan for the wave you are executing. Where a phase plan disagrees with the foundation on a shared contract (schemaVersion fields, Postgres column names, `resolve_model` roles, MCP tool names, package/path naming), **the foundation is canonical** unless this INDEX names a different resolution below.

The COBOL→Java modernization platform is built greenfield under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1` by porting/adapting `source_graphs_v1.0`. The deterministic Neo4j code graph is the source of truth; bounded agents read it only via read-only Cypher MCP tools; every artifact carries an `evidence_map` floored by a groundedness gate; seam math runs in Cypher/GDS (never in prompts); cost is a budgeted first-class concern with hard per-workspace/per-run caps + kill-switch; outcome parity is proven by dual-run; and every stage transition is a hard, attributed-RBAC human gate persisted in Postgres. The critical-path rule the whole roadmap pivots on: **Phase 1 (v2 graph enrichment) is a barrier — master-plan Phases 4+ are BLOCKED, not merely "later", until Phase 1 exits**, because seam discovery scores over the v2 READS/WRITES/EXECUTES_CICS/EXECUTES_SQL/MOVES_TO/GO_TO edges + DataItem nodes Phase 1 produces.

---

## 1. Document catalog

| Doc | Scope | Tasks | Depends on |
|---|---|---|---|
| `00-foundation-and-architecture.md` | Barrier. Greenfield layout; pinned stack; the single versioned `schemaVersion:2` Python↔Java JSON contract + loader; Postgres run/audit/RBAC schema (7 tables); model tiering + cost-cap/kill-switch; read-only MCP graph tool surface; port-map; conventions. | 6 (1.1, 2.1, 3.1, 4.1, 4.2, 4.3, 6.1) | — (it is the barrier) |
| `phase-0-carddemo-baseline-persistence-cost.md` | Run CardDemo end-to-end through the existing core (ingest→graph→grounded BRD); reproducible baseline benchmark (time/mem/≥10-error resilience/copybook depth); Alembic migrations; `CostVerifier`; `PgRepo`; content-hash incremental ingest + enrichment cache. Executes the foundation port-map PORTs for files Phase 0 reuses. | 15 | Foundation (1.1, 2.1, 3.1, 4.1, 4.2, 4.3, 6.1) + the PORT classifications |
| `phase-1-v2-graph-enrichment.md` | **Critical path.** Java `DataFlowWalker`/`CobolIoScanner` emit v2 DataItem + READS/WRITES/EXEC CICS/EXEC SQL/MOVES_TO/GO_TO; `schema.py` v2 labels/rel-MERGE/seam indexes; Cypher reader-vs-writer + fan-in/out + side-effect ranking; the 3 v2 MCP tools; **zero LLM in scoring**. | 9 | Foundation; Phase 0 (Postgres, cost, content-hash ingest, `conftest.py` `neo4j_graph` testcontainer fixture) |
| `phase-2-thin-vertical-slice.md` | One verified reader seam (CardDemo COACTVWC Account-View): slice selection from Phase-1 seam ranking; slice-scoped BRD; INVEST story DAG; COMP-3 codec + ACL; Spring Boot read service; tolerance rules + field-aware differ; dark-launch dual-run; per-stage RBAC gates + cost cap; FastAPI wiring. | 14 (2.1–2.14) | Phase 0, Phase 1, Foundation |
| `phase-3-equivalence-lab.md` | COBOL execution + equivalence: COMP-3/zoned/scale decode, EBCDIC CP037, record layout from graph DataItems, tolerance matcher, field-aware differ→DiffReport, source-seam resolution, `defect_ticket` table + migration, EquivalenceReport verdict, GnuCOBOL batch runner, CICS recorded-I/O shim, golden capture over MinIO, control-plane wiring. | 13 (1–13) | Phase 0, Phase 1, Phase 2, Foundation |
| `phase-4-seam-engine-increment-planner.md` | **Blocked until Phase 1 exits.** Master-plan weighted seam score (`0.25·business+0.20·isolation+0.20·testability+0.20·data_ownership−0.15·risk`) + GDS centrality/community; reader/writer + identity-drift; transition-pattern mapping; dead-paragraph + duplicate-capability detection; seam-rationale agent (groundedness floor); story planner (Kahn-acyclic DAG) + INVEST judge; v2 MCP ops; SeamEngine + story-DAG persistence. | 15 (1–15) | Phase 1 (blocking), Phase 0, Foundation |
| `phase-5-design-codegen-workbench.md` | Writer-path slice (CardDemo CBTRN02C posting/balance update): bounded-context assignment from seam+data-ownership; design groundedness gate; ADRs; Legacy Mimic codec/write-back (RECLN 300/350, no identity drift); Spring Boot scaffold; ArchUnit rules; TDD codegen; `mvn verify`→QualityReport; repair loop (cost-capped); gated pipeline. | 14 (1–14) | Foundation, Phase 1, Phase 4, Phase 3, Build Lab (cross-cutting) |
| `phase-6-deployment-canary.md` | Stoppable-safe cutover: deploy/canary/fitness Postgres tables; RoutingController enabling-point (flip requires passed gate); RollbackGuard; evolutionary-architecture fitness functions; stoppable-safe invariant checker; deterministic Docker build from MinIO artifact; smoke/health; perf baseline vs Equivalence Lab; CanaryOrchestrator; attributed deploy gate; CI. | 12 (6.0–6.11) | Phase 0, Phase 2, Phase 3, Phase 5, Foundation |
| `workstream-ui-cockpit.md` | 11-stage Next.js 15/React 19 cockpit: shell (Journey Rail · Stage Header+gates+cost pill · Main Workspace · single Agent Console · Evidence Drawer); 9 screens; 5-mode HITL + RBAC approval overlay; SSE `AgentRun` streaming; thin layer over `api.py` (agents stay in FastAPI). | 13 (UI-1–UI-13) | Foundation, `api.py` ADAPT (Phase 0), Phase 1 (seam overlay data), Phase 4 (seam scoring/planner), Phase 5 (design/build), Phase 3/5 (equivalence) |

---

## 2. Dependency-ordered delivery waves

The hard rule (master-plan §7 risk 2, restated in Phase-1 §Goal and Phase-4 §Tech-Stack): **Phase 4 and everything that scores over seams is BLOCKED until Phase 1 exits.** Phase 0 and Phase 1 are not optional preliminaries — they are the gate that unblocks the rest. "Parallel" below means *no dependency between the items*, not that they must run concurrently.

### Wave 0 — Foundation barrier (must complete before anything else)
- `00-foundation-and-architecture.md` Tasks 1.1, 2.1, 3.1, 4.1, 4.2, 4.3, 6.1.
- Produces: package skeleton, `schemaVersion:2` contract loader + `models.py` v2 columns/kinds, 7 Postgres tables, `resolve_model`, `CostPolicy`/`CostLedger`/`BudgetExceeded`, `.env.example`, `docker-compose.yml`.
- **Blocks: every other doc.** Nothing in Waves 1+ compiles or imports without it.

### Wave 1 — Phase 0 (baseline + persistence + cost) — single-threaded after Wave 0
- `phase-0` Tasks 1–15. Executes the PORTs (parser, neo4j_client, schema-v1, git_analyzer, cobol driver, BRD pipeline, agent harness, enricher) + the new substrate (Alembic, `CostVerifier`, `PgRepo`, content-hash ingest, CardDemo benchmark).
- Within Wave 1, two independent tracks can proceed in parallel once Task 1 (core PORT) lands:
  - Track A (data path): Tasks 2–4, 10–12 (cobol driver, content-hash, error-injection, benchmark, ingest integration).
  - Track B (control path): Tasks 8, 9 (Alembic migrations, `PgRepo`) + Task 7 (`CostVerifier`).
  - Track C (BRD path): Tasks 5, 6, 13 (BRD pipeline port, enricher cache, grounded-BRD integration).
- **Establishes** the `tests/conftest.py` fixtures (`carddemo_root`; the `neo4j_graph` testcontainer fixture Phase 1 imports). **Unblocks Phase 1.**
- **UI mapping:** Phase 0 control-plane endpoints + Portfolio/Intake/Graph-Explorer-v1/Blueprint-Studio data exist after this wave; UI Tasks UI-1, UI-2, UI-3, UI-5 (shell, client, portfolio, journey rail) and the v1 GraphView (UI-4 without seam overlay) can start in parallel against MSW mocks.

### Wave 2 — Phase 1 (v2 graph enrichment) — THE CRITICAL-PATH BARRIER, single-threaded after Wave 1
- `phase-1` Tasks 1–9. Java contract bump + scanner + DataFlowWalker; Neo4j v2 schema; Cypher seam classification; the 3 v2 MCP tools.
- Two parallel tracks inside Wave 2:
  - Java track: Tasks 1–4 (DataItemJson, CobolIoScanner, CICS/SQL, DataFlowWalker+walker wiring).
  - Python track: Tasks 5–9 (schema v2, queries/seam scoring, graph_ops/graph_tools v2, ingestion v2, integration) — Task 5 onward needs the v2 contract fixture but not the live JAR.
- **Exit of Phase 1 is the barrier flip.** Until `seam_candidates` / `reader_writer_classification` / `data_accesses` return real v2 data, Phases 2, 3, 4, 5, 6 cannot ship their seam-dependent work.
- **UI mapping:** UI-4 seam overlay data becomes real here.

### Wave 3 — Parallel after Phase 1 exits
Three independent streams; no cross-dependency among A/B except where noted:
- **3A — Phase 4 (Seam Engine & Increment Planner)** `phase-4` Tasks 1–15. The first consumer of the barrier; replaces Phase-1's deterministic heuristic score with the master-plan weighted formula and adds GDS + story DAG. Independent of Phase 2/3.
- **3B — Phase 2 (Thin Vertical Slice)** `phase-2` Tasks 2.1–2.14. Reader-seam vertical (COACTVWC). Depends on Phase-1 `seam_candidates` shape; can run alongside Phase 4.
- **3C — Phase 3 (Equivalence Lab)** `phase-3` Tasks 1–13. COBOL-execution + diff foundation. Tasks 1–9 (decode/EBCDIC/layout/tolerance/differ/seam-resolution/defect-ticket/report) are pure-Python and depend only on Phase 1 graph + Phase 0 tables; Tasks 10–12 (GnuCOBOL runner, CICS shim, golden capture) need GnuCOBOL/MinIO infra; Task 13 wires the control plane. Phase 3 consumes Phase 2's candidate-record JSON shape, so 3C's diff-harness reconciliation with 3B should be a synthesis checkpoint.
- **UI mapping:** Seam Studio + Increment Planner (UI-6 seam/plan screens) get real data from 3A; Equivalence Lab screen (UI-6 verify) from 3C; UI Tasks UI-7 (cost/gate pills), UI-8 (SSE), UI-9 (Agent Console), UI-10 (Evidence Drawer + approval overlay) can proceed in parallel across this wave.

### Wave 4 — Phase 5 (Design + Codegen Workbench) — after Phases 1, 3, 4
- `phase-5` Tasks 1–14. Writer-path slice (CBTRN02C). Needs Phase-4 seam evidence (writer/identity-drift/transition-pattern), Phase-3 Equivalence Lab verdict, and the cross-cutting Build Lab (`mvn verify`).
- **UI mapping:** Design Studio + Build Lab screens (UI-6 design/build) get real data here.

### Wave 5 — Phase 6 (Deployment + Canary) — last; after Phases 2, 3, 5
- `phase-6` Tasks 6.0–6.11. Containerize the Phase-5 `spring_boot_project` artifact, perf baseline vs Phase-3 lab, canary behind routing enabling-point, RollbackGuard, fitness functions, attributed deploy gate.
- **UI mapping:** verify-stage canary/rollback surfacing completes the cockpit.

### UI workstream (parallel band across all waves)
The cockpit is a thin layer and is NOT on the critical path. UI tasks gate on *data availability* per the table above, not on UI-internal ordering: UI-1/2/3/5 (shell/client/portfolio/rail) → Wave 1; UI-4 v1 graph → Wave 1, seam overlay → Wave 2; UI-6 screen stubs → Wave 1 with screens filling in as Waves 2–5 land; UI-7/8/9/10/11 (pills/SSE/console/drawer/approval/artifact viewer) → Wave 1+ against mocks, real data as control-plane endpoints ship; UI-12/13 (e2e + typecheck) → after the screens they exercise are real.

---

## 3. Consistency report (adversarial cross-check vs foundation contracts)

Findings from opening the files and comparing the load-bearing identifiers verbatim. Severity: **BLOCKER** (will break a build/import if unresolved), **RECONCILE** (shape/name drift to settle at synthesis), **OK-with-note** (intentional, documented).

1. **`seam_candidates` JSON shape diverges across Phase 1 / Phase 2 / Phase 4 — RECONCILE.** Foundation §5 specifies `[{program, fan_in, fan_out, reader_only, score}]`. Phase 1 Cypher returns `{program, fan_in, fan_out, write_count, side_effects, reader_only, score}`. Phase 2's `seam_candidates_sample.json` fixture expects `{program, fan_in, fan_out, reader_only, writes, reads, score}` (note `writes`/`reads` not `write_count`/`side_effects`). Phase 4 keeps the row keys but **replaces `score`** with the weighted formula `0.25b+0.20i+0.20t+0.20d−0.15r`. **Resolution:** the tool output is canonical at the **superset** Phase-1+Phase-2 shape — `{program, fan_in, fan_out, reader_only, reads, writes, write_count, side_effects, score, evidence_map}`; Phase 4 overwrites only `score` (and must keep Phase-1 row keys so Phase-2's `pick_slice` and the UI seam overlay keep working). Phase 1 must rename/alias `write_count`→also expose `writes`, and add a `reads` count, to satisfy Phase 2's fixture. Owner: Phase 1 emits the superset; Phase 4 overwrites `score`; Phase 2 fixture conforms.

2. **`journey_stage.stage_key` value set differs between Foundation and UI — RECONCILE (UI canonical for the 11 cockpit stages).** Foundation §3 gives the illustrative set `intake|graph|brd|seams|stories|design|build|equivalence|deploy`. The UI plan defines the canonical 11: `outcome, intake, parse, graph, explore, blueprint, seams, plan, design, build, verify`. These are not 1:1 (`brd`≠`blueprint`, `stories`≠`plan`, `equivalence`/`deploy` collapse into `verify`). **Resolution:** the UI plan explicitly flags the Foundation list as "illustrative" and the 11-stage list as canonical, with a stage→gate mapping (`blueprint→brd_groundedness`, `plan→stories_dag`, `design→design_data_ownership`, `build→code`, `verify→equivalence`+`deploy`). The `api.py` ADAPT (Phase 0) **must seed exactly these 11 `stage_key`s and this stage→gate map** — this is the single point that must not drift. Owner: `api.py` (Phase 0) seeds; `lib/stages.ts` (UI) mirrors.

3. **`agent_run.role` comment lists `equivalence` but the `resolve_model` role is `equivalence_triage` — RECONCILE (cosmetic but real).** Foundation §3 `agent_run.role` comment enumerates `...codegen|equivalence`; Foundation §4's `resolve_model` table has no `equivalence` role — the Haiku role is `equivalence_triage`. Phase 3 correctly uses `equivalence_triage` only for an optional narrative. **Resolution:** `agent_run.role` is a free TEXT column (not an enum), so this is non-breaking, but the comment should read `equivalence_triage`. Any code calling `resolve_model("equivalence")` would fall through to the Sonnet default — no phase does this. Owner: Foundation comment fix; no code impact.

4. **Alembic migration numbering collision — BLOCKER.** Phase 0 creates `0001_initial.py`. Phase 6 adds `0002_deploy.py`. Phase 3 adds `0003_defect_ticket.py`. But in delivery order Phase 3 (Wave 3) ships **before** Phase 6 (Wave 5), so Phase 3's `0003` would be authored before `0002` exists, and `down_revision` chains will be inconsistent (Phase 3 risk-note already flags "synthesis must confirm migration numbering doesn't collide"). **Resolution:** renumber by delivery order, not by phase number — Phase 3's defect_ticket migration becomes `0002_defect_ticket` (down_revision `0001_initial`) and Phase 6's deploy/canary/fitness migration becomes `0003_deploy` (down_revision `0002_defect_ticket`). Phase 2 adds NO migration (it reuses Phase 0's `workspace`/`gate`/`approval`). Owner: synthesis — fix the two migration filenames + `down_revision` pointers before either runs.

5. **`api.py` is ADAPT-shared by Phase 0, 2, 3, 5, 6 and the UI — RECONCILE (one merged route set).** Each phase adds routes to the same `src/cobol_modernizer/api.py` (Phase 2 slice/dark-launch, Phase 3 equivalence, Phase 5 design/codegen, Phase 6 canary, all over the Phase-0 stages/approvals/cost/SSE base). The UI plan pins the exact endpoint + SSE event shapes it consumes (`GET /api/workspaces`, `/{id}/stages`, `/{id}/gates`, `/{id}/artifacts`, `/{id}/runs`, `/{id}/budget`, `POST /api/workspaces`, `/{id}/runs`, `POST /api/gates/{gateId}/approval`, SSE `/api/workspaces/{id}/runs/{runId}/events` → `{type,run_id,seq,ts,summary,detail}`, plus `/api/graph`, `/api/entity`). **Resolution:** the Phase-0 `api.py` ADAPT is canonical for the base + SSE shape; downstream phases append routes without altering the base; the UI's pinned contract is the acceptance test for that base. Owner: Phase 0 `api.py` ADAPT; verified by UI MSW mocks + Playwright.

6. **`schemaVersion: 1` literals appear in plans — OK-with-note.** Grep finds `schemaVersion": 1` references; all are in **negative tests** (`test_version_mismatch_raises`, `test_mapping_rejects_v1`) asserting the loader raises on v1. This is correct, not a contradiction. The live extractor emits `schemaVersion=2` (Phase 1 Task 4 flips `ExtractorMain.SCHEMA_VERSION` to 2). Owner: none.

7. **`graph_ops.py` read-only WRITE-guard is touched by both Phase 0 and Phase 1 — RECONCILE.** Phase 0 ports `graph_ops.py` with read paths only (no WRITE guard); Phase 1 adds v2 ops AND the read-only guard. The two plans modify the same file. **Resolution:** Phase 0 ports read paths verbatim; Phase 1 is the sole owner of the WRITE-guard + v2 ops. The enricher's WRITE_BACK (Phase 0 Task 6) is the one sanctioned mutation and must be whitelisted by Phase 1's guard, not blocked. Owner: Phase 1 guard must allow-list enrichment WRITE_BACK.

8. **`agent/models.py` → `cost/tiering.py` rename ripple — RECONCILE.** Foundation REBUILDS `agent/models.py` as `cost/tiering.py`. Phase 0 Task 5 includes a grep-rewrite (`cobol_modernizer.agent.models import resolve_model` → `cobol_modernizer.cost.tiering import resolve_model`) across ported BRD modules. **Resolution:** the Phase-0 grep-rewrite is canonical; synthesis must confirm it covers every ported module (clustering, brd_orchestrator, pipeline) and no later phase re-introduces `agent.models`. Owner: Phase 0 Task 5 grep step (verify coverage).

9. **Java `FileResultJson` arity change ripples to v1 Java tests — RECONCILE.** Phase 1 Task 1 adds `dataItems` to `FileResultJson` (3-arg→adds a list), breaking every existing `new FileResultJson(...)` call site (CobolWalker ×3, ExternalResolver ×1) and the ported v1 tests (`CobolWalkerTest`/`SectionTest`/`CallCopyTest`/`JsonShapeTest`). **Resolution:** whoever ports the v1 walker + tests (Foundation/Phase 0) and Phase 1 must coordinate: Phase 1 Task 1 updates all call sites to pass `List.of()` for `dataItems` and Task 4 fills them. The v1 test ports must be authored against the **v2 arity** from the start. Owner: Phase 1 Task 1 + Task 4.

10. **DataItem qualified-name convention (`PROGRAM.FIELD`) is assumed by Phase 3/4/5 — OK-with-note, must hold.** Phase 3 `seam_link.resolve_source_seam`, Phase 4 signal Cypher, and Phase 5 mimic layout all assume `qualifiedName = PROG.ITEM-NAME` (e.g. `CBACT01C.ACCT-CURR-BAL`) emitted by Phase 1's `DataFlowWalker.dataItems` (verified: it emits `progId + "." + name`). **Resolution:** consistent across plans; lock it as a contract invariant. The known follow-up (CICS resource is often a variable `LIT-*` not the real dataset name) is correctly deferred to a constant-resolution enrichment step. Owner: Phase 1 (emit), consumers conform.

11. **Package/path naming — OK.** Every plan uses `cobol_modernizer` (Python) / `com.cobolmodernizer.cobol` (Java) under the greenfield root, with PORT steps rewriting `code_context_graph`/`com.codecontextgraph.cobol`. No path drift found. MCP server name `graph`, FQN `mcp__graph__<tool>` is used consistently.

---

## 4. Gaps (master-plan requirements not fully owned by a plan)

1. **5-mode HITL operating model — partially owned, needs an explicit contract.** The UI plan references "the 5-mode HITL operating model" and the RBAC approval overlay, but no doc enumerates the five modes (e.g. autopilot / co-pilot / approve-each-gate / observe / manual) as a binding control-plane contract. **Assign to:** the UI plan (`workstream-ui-cockpit`) to define the 5 modes + which gates each mode auto-vs-manually clears, AND Phase 0 `api.py` ADAPT to persist the active mode per workspace (no current column). This needs a `workspace`-level mode field or a `journey_stage` policy — currently unspecified.

2. **RBAC role authority matrix — gap.** `approval.approver_role` (`lead_engineer|architect|risk_officer`) exists, but no doc specifies *which role may clear which gate* (e.g. can a `lead_engineer` waive `equivalence` with risk, or only `risk_officer`?). **Assign to:** Phase 0 `api.py` ADAPT (the gate-approval endpoint must enforce a role→gate authorization matrix); the UI approval overlay surfaces it.

3. **`estimatedCostUsd` for the approval overlay — gap (UI risk-noted).** The UI approval overlay shows a budget-impact estimate, but Foundation/api.py specify no run-cost-estimate endpoint or `gate.result` field carrying it. **Assign to:** Phase 0 `api.py` ADAPT — add a run cost-estimate source (endpoint or `gate.result.estimated_cost_usd`).

4. **§4 token tactics beyond caching/tiering — partial.** Model tiering, prompt caching, 4-bucket tracking, cost caps + kill-switch, content-hash enrichment cache are covered (Foundation §4, Phase 0 Tasks 3/4/6/7/9). **Gap:** the master-plan §4 "compaction / context-window budget per agent run" and "advisor escalation budget exhaustion telemetry" are only partially present (`ADVISOR_MAX_USES` exists; per-run context-window budgeting and compaction policy are not specified). **Assign to:** Phase 0 (extend `CostPolicy`/harness) or a cross-cutting token-economy note; flag for synthesis.

5. **§5 verification gates — mostly covered, one gap.** Parse gate (Phase 0/1), graph gate, `brd_groundedness` (Phase 0/2), `stories_dag` (Phase 2/4), `design_data_ownership` (Phase 5), `code` (Phase 5), `equivalence` (Phase 3), `deploy` (Phase 6) are all owned. **Gap:** the `graph` gate (graph-completeness/quality threshold after ingest) is referenced in the UI stage→gate map but no phase defines its `threshold`/`result` schema or who evaluates it. **Assign to:** Phase 1 (it owns graph completeness) — define the `graph` gate threshold (e.g. min parse-success ratio, expected entity counts vs discovered) and emit its `gate.result`.

6. **§7 open question — CICS literal/variable resource resolution — deferred, owner unassigned.** Phase 1 correctly records the raw operand token (e.g. `LIT-ACCTFILENAME`) and notes a "constant-resolution enrichment step" as follow-up, but no plan owns it. Downstream phases (3/4/5) that need the real VSAM dataset name will see unresolved `LIT-*` resources. **Assign to:** a Phase-1 follow-up task (resolve `VALUE` clauses for `LIT-*` constants into the real dataset name) before Phase 4's data-ownership signal can be precise.

7. **Co-change churn ingestion — conditionally owned.** Phase 4's `risk` signal includes a churn term from `CO_CHANGED_WITH` edges via `git_analyzer.py` (PORT-AS-IS in Phase 0). **Gap:** no task actually *ingests* churn edges into the graph; Phase 4 notes the term degrades to 0 if absent. **Assign to:** Phase 1 ingestion (add a churn-ingest step) or accept the documented degradation; decide at synthesis.

8. **Graph-snapshot pinning lifecycle — partial.** `workspace.graph_snapshot` column exists and the UI pins sessions to a snapshot + artifact versions, but no plan defines how a Neo4j snapshot id is created/pinned/resolved. **Assign to:** Phase 0 `api.py` ADAPT + ingestion (stamp `graph_snapshot` on ingest completion).

---

## 5. Recommended FIRST task

**`00-foundation-and-architecture.md` → Task 1.1 — Bootstrap the Python project.**

- File path: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/docs/plans/00-foundation-and-architecture.md`
- Creates: `pyproject.toml`, `.python-version`, `src/cobol_modernizer/__init__.py`, `tests/unit/test_package_imports.py`.
- Rationale: the foundation is the barrier for all 8 plans, and within the foundation Task 1.1 is the prerequisite for Task 2.1 (contract loader), which Phase 0 and Phase 1 both import. Nothing else compiles until the `cobol_modernizer` package exists and is editable-installed under uv. It is a 5-minute red→green→commit step (`uv run pytest tests/unit/test_package_imports.py`).
