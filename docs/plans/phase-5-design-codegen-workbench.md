# Phase 5 — Design + Codegen Workbench (Writer-Path Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Migrate a **stateful / writer slice** of CardDemo — the posting / balance-update path (`CBTRN02C`: post daily transactions → `REWRITE` account balance in ACCTFILE, `REWRITE` category balance in TCATBAL, `WRITE` to TRANSACT) — into a Spring Boot module under **Extract Product Lines + Legacy Mimic write-back**, with full TDD codegen gated by ArchUnit/SpotBugs/Error Prone/Checkstyle, a repair loop that feeds compiler/test/architecture logs back to the agent, and a Legacy Mimic adapter that serializes the Java result back into the exact mainframe `ACCOUNT-RECORD` (RECLN 300) / `TRAN-RECORD` (RECLN 350) fixed-width format so the un-migrated COBOL estate keeps running. Exit when the writer slice passes compile + tests + architecture rules + equivalence (Phase 3 lab) with **no identity drift**, and the old COBOL path is retired or fronted by an anti-corruption layer (ACL).

**Architecture:** Deterministic Neo4j code-graph (source of truth; read via read-only Cypher MCP tools only) + Postgres run/audit/version/RBAC + MinIO object store (raw source, golden files, generated project). Two new bounded-context modules in a **modular monolith** (default; promote to microservices only on proven data-ownership + independent release). Codegen is a budgeted, tiered agent loop (`design`=Opus, `codegen`=Sonnet, `repair`=Opus) reading BRD + seam evidence + golden fixtures from the graph and object store, never raw dumps. Seam classification (writer, identity-drift) comes pre-computed from Phase 1/4 Cypher — the agent only writes rationale. Every artifact (ADR, design, generated project, equivalence report) carries an `evidence_map` and is judged by the groundedness gate. The Legacy Mimic adapter writes Java results back to mainframe fixed-width records so the strangler-fig keeps the legacy path alive until full extraction.

**Tech Stack (pinned — per foundation §Tech Stack):** Python 3.12 + uv; **Java 25 + Maven 3.9 + Spring Boot 3.3** for generated services; JUnit 5 + **ArchUnit 1.3 + SpotBugs 4.8 (FindSecBugs) + Error Prone 2.28 + Checkstyle 10**; Neo4j 5.24-enterprise + GDS 2.x (read-only); Postgres 16; MinIO; GnuCOBOL 3.2 (Phase 3 Equivalence Lab); `claude-agent-sdk==0.2.87` with `tools=[]`, `setting_sources=[]`, `output_format` json_schema.

**Depends on (must be complete first):**
- **Foundation (`docs/plans/00-foundation-and-architecture.md`)** — package `cobol_modernizer`, contract `schemaVersion=2`, Postgres tables (`workspace/journey_stage/agent_run/artifact/gate/approval/budget`), `cost/tiering.py:resolve_model`, `cost/policy.py:CostPolicy`, `agent/harness.py:SdkAgentRunner`, read-only MCP graph surface.
- **Phase 1** — v2 graph edges (`READS`/`WRITES` with mode, `EXECUTES_CICS`/`EXECUTES_SQL` intent, `MOVES_TO`, `GO_TO`), `DataItem` nodes, reader/writer Cypher.
- **Phase 4** — seam engine: `seam_candidates`, writer/identity-drift flag, transition-pattern recommendation, story DAG.
- **Build Lab** (cross-cutting) — Maven invocation harness that compiles a generated project and runs `mvn verify`, returning structured pass/fail + logs.
- **Phase 3** — Equivalence Lab (`equivalence/` runner) producing a golden-master diff with COMP-3 / numeric-scale tolerance rules and an identity-drift check.

This plan **does not** rebuild those; it imports their public surfaces. Where a dependency's exact symbol is needed, this plan declares the import and the test stubs it with a fake (TDD: the unit under test is the Phase 5 code).

---

## File Structure

Everything is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── src/cobol_modernizer/
│   ├── design/                                   # NEW — service-design + ADR agents (Phase 5)
│   │   ├── __init__.py
│   │   ├── schema.py                             # BoundedContext/ServiceDesign/ADR/DesignResult pydantic models + design EvidenceMap
│   │   ├── context_map.py                        # deterministic bounded-context assignment from seam + data-ownership Cypher (no LLM)
│   │   ├── designer.py                            # design agent: reads graph+seam evidence, emits ServiceDesign (role="design", Opus)
│   │   ├── adr.py                                 # ADR generator + renderer (Markdown ADRs from design decisions)
│   │   └── judge.py                               # design groundedness gate (data-ownership rule + evidence floor; reuses brd_judge weights)
│   ├── codegen/                                  # NEW — TDD codegen + repair loop (Phase 5)
│   │   ├── __init__.py
│   │   ├── schema.py                             # GeneratedFile/GeneratedProject/CodegenResult/RepairAttempt models
│   │   ├── scaffold.py                            # writes the Spring Boot 3.3 Maven module skeleton (pom, ArchUnit/SpotBugs/EP/Checkstyle config)
│   │   ├── generator.py                           # codegen agent: BRD+golden fixtures -> tests-first then code (role="codegen", Sonnet)
│   │   ├── repair_loop.py                         # feeds compile/test/ArchUnit/SpotBugs logs back; escalates hard failures (role="repair", Opus)
│   │   ├── quality_gate.py                        # parse mvn verify output -> structured QualityReport (compile/test/archunit/spotbugs/errorprone/checkstyle)
│   │   └── archrules.py                           # emits the ArchUnit test source enforcing bounded-context + data-ownership rules
│   ├── mimic/                                     # NEW — Legacy Mimic write-back adapter (Phase 5)
│   │   ├── __init__.py
│   │   ├── layout.py                             # copybook -> fixed-width field layout (offset/len/PIC/usage) from DataItem graph
│   │   ├── codec.py                              # encode/decode COMP-3 packed-decimal, zoned-decimal, S9(n)Vm scale; EBCDIC option
│   │   └── writeback.py                           # ResultDTO -> mainframe ACCOUNT-RECORD/TRAN-RECORD bytes; ACL boundary
│   └── orchestration/
│       └── phase5.py                              # end-to-end: seam->design->ADR->scaffold->codegen->repair->mimic->equivalence, gated + cost-capped
├── generated/
│   └── carddemo-posting/                          # the generated Spring Boot writer module (scaffolded by scaffold.py; not hand-written)
│       ├── pom.xml
│       └── src/{main,test}/java/com/cobolmodernizer/posting/...
├── tests/
│   ├── unit/
│   │   ├── test_design_context_map.py            # deterministic bounded-context assignment
│   │   ├── test_design_schema.py                 # design models + evidence_map shape
│   │   ├── test_design_judge.py                  # data-ownership gate + groundedness floor
│   │   ├── test_adr.py                           # ADR rendering + numbering
│   │   ├── test_codegen_scaffold.py              # Maven skeleton + plugin wiring present
│   │   ├── test_codegen_generator.py             # tests-first ordering + evidence_map
│   │   ├── test_quality_gate.py                  # mvn-output parsing -> QualityReport
│   │   ├── test_repair_loop.py                   # log feedback + repair escalation + bounded attempts
│   │   ├── test_archrules.py                     # generated ArchUnit source content
│   │   ├── test_mimic_layout.py                  # copybook -> offset/len layout (RECLN 300/350)
│   │   ├── test_mimic_codec.py                   # COMP-3 / S9V scale round-trip
│   │   ├── test_mimic_writeback.py               # DTO -> mainframe bytes, identity preserved
│   │   └── test_phase5_orchestration.py          # gated pipeline, cost cap, no-identity-drift exit
│   ├── integration/
│   │   └── test_phase5_writer_slice_e2e.py       # full slice on CardDemo CBTRN02C (graph fixture) -> mvn verify -> equivalence
│   └── fixtures/
│       ├── seam_writer_cbtrn02c.json             # Phase-4-shaped seam evidence for the posting writer slice
│       ├── brd_posting_slice.json                # focused BRD for the posting slice (required vs accidental behavior)
│       ├── golden_posting/                        # captured COBOL inputs/outputs for the posting slice (Phase 3 golden master)
│       │   ├── input_dalytran.fixed              # daily-transaction input records (fixed-width)
│       │   ├── before_acctfile.fixed             # ACCTFILE before posting
│       │   └── after_acctfile.golden.fixed       # ACCTFILE after COBOL posting (the oracle)
│       └── account_layout_cvact01y.json          # DataItem-shaped layout for ACCOUNT-RECORD copybook
└── docs/adr/                                      # rendered ADRs land here (created by adr.py)
    └── .gitkeep
```

**Single-responsibility map (new files):**
- `design/context_map.py` — pure-Cypher, zero-LLM assignment of each migrated program to one of the four bounded contexts (Account Mgmt / Card Mgmt / Transaction Processing / Bill Pay-Reporting) from seam writer-set + data ownership.
- `design/designer.py` — the only place the design agent runs; emits `ServiceDesign` with an `evidence_map`.
- `design/judge.py` — enforces "a service owns its data" + groundedness floor before design can pass its gate.
- `codegen/scaffold.py` — deterministic project skeleton (no LLM) so the agent only fills in business code/tests.
- `codegen/generator.py` — TDD: emits failing tests from BRD+golden first, then code.
- `codegen/quality_gate.py` — turns Build Lab's `mvn verify` output into a structured, judgeable `QualityReport`.
- `codegen/repair_loop.py` — the log-feedback loop; bounded attempts; escalates to Opus on hard failure.
- `mimic/codec.py` — the numeric-fidelity core (COMP-3, scale, sign) that prevents identity drift on write-back.
- `mimic/writeback.py` — the ACL: Java DTO → exact mainframe bytes.
- `orchestration/phase5.py` — wires it all behind gates + the cost policy.

---

## Task 1 — Design schema (BoundedContext / ServiceDesign / ADR) with evidence_map

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/design/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/design/schema.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_design_schema.py`

Steps:
- [ ] Write failing test `tests/unit/test_design_schema.py`:
  ```python
  from cobol_modernizer.design.schema import (
      BoundedContext, ServiceDesign, ADR, DesignResult,
  )

  def test_bounded_context_enum_has_four_carddemo_contexts():
      values = {c.value for c in BoundedContext}
      assert values == {
          "account_management", "card_management",
          "transaction_processing", "bill_pay_reporting",
      }

  def test_service_design_carries_evidence_map_and_data_ownership():
      d = ServiceDesign(
          slice_id="posting-cbtrn02c",
          deployment="modular_monolith",
          context=BoundedContext.transaction_processing,
          owned_resources=["TRANSACT", "ACCTDAT", "TCATBAL"],
          transition_pattern="extract_product_lines+legacy_mimic",
          components=["PostingService", "AccountBalanceRepository"],
          evidence_map={"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]},
      )
      assert d.context is BoundedContext.transaction_processing
      assert "ACCTDAT" in d.owned_resources
      assert d.evidence_map["DR-1"] == ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]

  def test_adr_is_numbered_and_has_decision_and_consequences():
      adr = ADR(number=1, title="Modular monolith for posting slice",
                status="accepted", context="Writer slice, identity-drift risk",
                decision="Extract Product Lines + Legacy Mimic write-back",
                consequences="COBOL estate keeps running via ACL",
                evidence_refs=["CBTRN02C"])
      assert adr.number == 1 and adr.status == "accepted"

  def test_design_result_aggregates_design_and_adrs():
      d = ServiceDesign(slice_id="s", deployment="modular_monolith",
                        context=BoundedContext.transaction_processing,
                        owned_resources=["ACCTDAT"],
                        transition_pattern="extract_product_lines+legacy_mimic",
                        components=["PostingService"], evidence_map={"DR-1": ["CBTRN02C"]})
      res = DesignResult(design=d, adrs=[], rating="high", weighted_score=4.4)
      assert res.rating == "high"
  ```
- [ ] Run `uv run pytest tests/unit/test_design_schema.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.design'`.
- [ ] Create `src/cobol_modernizer/design/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/design/schema.py`:
  ```python
  from __future__ import annotations

  from enum import Enum
  from typing import Literal

  from pydantic import BaseModel, Field

  # Reuse the foundation lineage contract: requirement_id -> [graph entity ids / source refs].
  DesignEvidenceMap = dict[str, list[str]]


  class BoundedContext(str, Enum):
      """The four CardDemo bounded contexts derived from seams + data ownership
      (master plan Phase 5). Assignment is deterministic (context_map.py), not LLM."""
      account_management = "account_management"
      card_management = "card_management"
      transaction_processing = "transaction_processing"
      bill_pay_reporting = "bill_pay_reporting"


  Deployment = Literal["modular_monolith", "microservice"]


  class ServiceDesign(BaseModel):
      slice_id: str
      deployment: Deployment = "modular_monolith"   # modular monolith is the default
      context: BoundedContext
      owned_resources: list[str]                     # VSAM/file/table this service OWNS (writes)
      transition_pattern: str                        # e.g. extract_product_lines+legacy_mimic
      components: list[str]                           # planned Java components
      evidence_map: DesignEvidenceMap = Field(default_factory=dict)


  class ADR(BaseModel):
      number: int
      title: str
      status: Literal["proposed", "accepted", "superseded"] = "accepted"
      context: str
      decision: str
      consequences: str
      evidence_refs: list[str] = Field(default_factory=list)


  class DesignResult(BaseModel):
      design: ServiceDesign
      adrs: list[ADR]
      rating: Literal["high", "medium", "low"]
      weighted_score: float
  ```
- [ ] Run `uv run pytest tests/unit/test_design_schema.py` — expected PASS (4 passed).
- [ ] Commit: `feat(design): ServiceDesign/BoundedContext/ADR models with evidence_map`

---

## Task 2 — Deterministic bounded-context assignment from seam + data-ownership (no LLM)

A service must **own its data**. Bounded-context assignment is computed from the writer-set Cypher (Phase 1/4), never guessed by the LLM. This is the determinism non-negotiable applied to design.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/design/context_map.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_design_context_map.py`

Steps:
- [ ] Write failing test `tests/unit/test_design_context_map.py`:
  ```python
  from cobol_modernizer.design.context_map import (
      assign_context, owned_resources, RESOURCE_CONTEXT,
  )

  class FakeDeps:
      """Stands in for GraphDeps; exposes only what context_map needs."""
      def __init__(self, writes):
          self._writes = writes  # program -> [resource,...] (WRITES/REWRITE intent)
      def writer_resources(self, program):
          return self._writes.get(program, [])

  def test_resource_context_table_maps_carddemo_files():
      assert RESOURCE_CONTEXT["ACCTDAT"] == "account_management"
      assert RESOURCE_CONTEXT["TRANSACT"] == "transaction_processing"
      assert RESOURCE_CONTEXT["CARDDAT"] == "card_management"

  def test_owned_resources_are_writer_resources_only():
      deps = FakeDeps({"CBTRN02C": ["TRANSACT", "ACCTDAT", "TCATBAL"]})
      assert owned_resources(deps, "CBTRN02C") == ["ACCTDAT", "TCATBAL", "TRANSACT"]

  def test_assign_context_by_dominant_owned_resource():
      # CBTRN02C writes TRANSACT(txn-proc), ACCTDAT(acct), TCATBAL(txn-proc):
      # transaction_processing dominates (2 vs 1).
      deps = FakeDeps({"CBTRN02C": ["TRANSACT", "ACCTDAT", "TCATBAL"]})
      assert assign_context(deps, "CBTRN02C") == "transaction_processing"

  def test_assign_context_no_writes_raises():
      import pytest
      deps = FakeDeps({})
      with pytest.raises(ValueError, match="no owned"):
          assign_context(deps, "COACTVWC")  # a reader-only program owns no data
  ```
- [ ] Run `uv run pytest tests/unit/test_design_context_map.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/design/context_map.py`:
  ```python
  """Deterministic bounded-context assignment from data ownership.

  A program belongs to the context that owns the data it WRITES. Writer-set
  comes from the v2 graph (READS/WRITES/EXECUTES_* with intent), computed in
  Cypher in Phase 1/4 — zero LLM in this path."""
  from __future__ import annotations

  from collections import Counter
  from typing import Protocol

  # CardDemo VSAM/file -> bounded context. Grounded in the four Phase-5 contexts.
  RESOURCE_CONTEXT: dict[str, str] = {
      "ACCTDAT": "account_management",
      "ACCTFILE": "account_management",
      "CUSTDAT": "account_management",
      "CARDDAT": "card_management",
      "CARDFILE": "card_management",
      "CXACAIX": "card_management",
      "TRANSACT": "transaction_processing",
      "TRANFILE": "transaction_processing",
      "TCATBAL": "transaction_processing",
      "TCATBALF": "transaction_processing",
      "DALYTRAN": "transaction_processing",
      "BILLPAY": "bill_pay_reporting",
      "RPTFILE": "bill_pay_reporting",
  }


  class _WriterDeps(Protocol):
      def writer_resources(self, program: str) -> list[str]: ...


  def owned_resources(deps: _WriterDeps, program: str) -> list[str]:
      """Resources the program WRITES (owns), sorted for determinism."""
      return sorted(set(deps.writer_resources(program)))


  def assign_context(deps: _WriterDeps, program: str) -> str:
      owned = owned_resources(deps, program)
      if not owned:
          raise ValueError(f"{program} has no owned (written) resources; "
                           f"reader-only programs are not assigned a context")
      tally: Counter[str] = Counter()
      for res in owned:
          ctx = RESOURCE_CONTEXT.get(res)
          if ctx:
              tally[ctx] += 1
      if not tally:
          raise ValueError(f"{program} owns resources {owned} with no known context")
      # dominant context wins; ties broken by name for determinism
      return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
  ```
- [ ] Run `uv run pytest tests/unit/test_design_context_map.py` — expected PASS (4 passed).
- [ ] Commit: `feat(design): deterministic bounded-context assignment from writer-set (no LLM)`

---

## Task 3 — Design groundedness gate (data-ownership rule + evidence floor)

The Design gate (master plan §5 "Design (service owns its data)") must fail any design whose `owned_resources` include a resource also written by another in-scope context (ownership leak), or whose evidence refs are not in the graph (groundedness). Reuses the `brd_judge` weighting/floor pattern verbatim.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/design/judge.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_design_judge.py`

Steps:
- [ ] Write failing test `tests/unit/test_design_judge.py`:
  ```python
  from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
  from cobol_modernizer.design.judge import judge_design

  def _design(owned, evidence):
      return ServiceDesign(
          slice_id="posting", deployment="modular_monolith",
          context=BoundedContext.transaction_processing,
          owned_resources=owned, transition_pattern="extract_product_lines+legacy_mimic",
          components=["PostingService"], evidence_map=evidence)

  KNOWN = {"CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC", "TRANSACT", "ACCTDAT"}

  def test_clean_design_passes_high():
      d = _design(["TRANSACT", "ACCTDAT"],
                  {"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]})
      rep = judge_design(d, known_refs=KNOWN, external_writers={})
      assert rep.data_ownership_ok is True
      assert rep.groundedness_failures == []
      assert rep.rating == "high"

  def test_ownership_leak_fails():
      # ACCTDAT is also written by another context's program -> shared-write leak
      d = _design(["TRANSACT", "ACCTDAT"], {"DR-1": ["CBTRN02C"]})
      rep = judge_design(d, known_refs=KNOWN,
                         external_writers={"ACCTDAT": ["COACTUPC"]})
      assert rep.data_ownership_ok is False
      assert rep.rating == "low"

  def test_hallucinated_evidence_floors_rating():
      d = _design(["TRANSACT"], {"DR-1": ["NOSUCHPGM"]})
      rep = judge_design(d, known_refs=KNOWN, external_writers={})
      assert "NOSUCHPGM" in rep.groundedness_failures
      assert rep.rating == "low"
  ```
- [ ] Run `uv run pytest tests/unit/test_design_judge.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/design/judge.py`:
  ```python
  """Design gate: a service must own its data, and every evidence ref must exist
  in the graph. Mirrors the BRD groundedness gate (brd_judge.py): hallucinated
  refs floor the rating to 'low'; an ownership leak floors it to 'low'."""
  from __future__ import annotations

  from pydantic import BaseModel

  from cobol_modernizer.design.schema import ServiceDesign


  class DesignJudgeReport(BaseModel):
      data_ownership_ok: bool
      groundedness_failures: list[str]
      rating: str            # high | medium | low
      weighted_score: float
      rationale: str


  def judge_design(design: ServiceDesign, *, known_refs: set[str],
                   external_writers: dict[str, list[str]]) -> DesignJudgeReport:
      # 1. Groundedness: every evidence ref must be a known graph entity.
      failures: list[str] = []
      for refs in design.evidence_map.values():
          for ref in refs:
              if ref not in known_refs:
                  failures.append(ref)

      # 2. Data-ownership: no owned resource may also be written by another context.
      leaks = [r for r in design.owned_resources if external_writers.get(r)]
      data_ownership_ok = not leaks

      if failures:
          return DesignJudgeReport(
              data_ownership_ok=data_ownership_ok, groundedness_failures=failures,
              rating="low", weighted_score=2.0,
              rationale=f"hallucinated evidence refs: {failures}")
      if not data_ownership_ok:
          return DesignJudgeReport(
              data_ownership_ok=False, groundedness_failures=[],
              rating="low", weighted_score=2.0,
              rationale=f"ownership leak; shared writers: "
                        f"{ {r: external_writers[r] for r in leaks} }")
      return DesignJudgeReport(
          data_ownership_ok=True, groundedness_failures=[],
          rating="high", weighted_score=4.4,
          rationale="service owns its data; all evidence grounded")
  ```
- [ ] Run `uv run pytest tests/unit/test_design_judge.py` — expected PASS (3 passed).
- [ ] Commit: `feat(design): design gate enforcing data-ownership + groundedness floor`

---

## Task 4 — ADR generation + Markdown rendering

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/design/adr.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_adr.py`

Steps:
- [ ] Write failing test `tests/unit/test_adr.py`:
  ```python
  from cobol_modernizer.design.schema import ADR
  from cobol_modernizer.design.adr import render_adr, default_adrs_for_writer_slice

  def test_render_adr_is_markdown_with_standard_sections():
      adr = ADR(number=3, title="Legacy Mimic write-back",
                status="accepted", context="Un-migrated COBOL still reads ACCTFILE",
                decision="Serialize Java result to ACCOUNT-RECORD fixed-width bytes",
                consequences="COBOL estate keeps running; ACL owns the format",
                evidence_refs=["CBTRN02C.2800-UPDATE-ACCOUNT-REC", "ACCTDAT"])
      md = render_adr(adr)
      assert md.startswith("# ADR-0003: Legacy Mimic write-back")
      assert "## Status\naccepted" in md
      assert "## Decision" in md and "## Consequences" in md
      assert "CBTRN02C.2800-UPDATE-ACCOUNT-REC" in md  # lineage embedded

  def test_default_adrs_for_writer_slice_cover_monolith_eps_and_mimic():
      adrs = default_adrs_for_writer_slice(
          slice_id="posting", owned_resources=["TRANSACT", "ACCTDAT"],
          evidence_refs=["CBTRN02C"])
      titles = [a.title.lower() for a in adrs]
      assert any("monolith" in t for t in titles)
      assert any("extract product lines" in t for t in titles)
      assert any("mimic" in t for t in titles)
      assert [a.number for a in adrs] == [1, 2, 3]
  ```
- [ ] Run `uv run pytest tests/unit/test_adr.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/design/adr.py`:
  ```python
  """Architecture Decision Records for a writer slice. Each ADR carries lineage
  (evidence_refs) so design decisions are auditable, not asserted."""
  from __future__ import annotations

  from cobol_modernizer.design.schema import ADR


  def render_adr(adr: ADR) -> str:
      refs = "\n".join(f"- `{r}`" for r in adr.evidence_refs) or "- (none)"
      return (
          f"# ADR-{adr.number:04d}: {adr.title}\n\n"
          f"## Status\n{adr.status}\n\n"
          f"## Context\n{adr.context}\n\n"
          f"## Decision\n{adr.decision}\n\n"
          f"## Consequences\n{adr.consequences}\n\n"
          f"## Evidence (lineage)\n{refs}\n"
      )


  def default_adrs_for_writer_slice(*, slice_id: str,
                                    owned_resources: list[str],
                                    evidence_refs: list[str]) -> list[ADR]:
      res = ", ".join(owned_resources)
      return [
          ADR(number=1, title="Modular monolith as default deployment",
              status="accepted",
              context=f"Writer slice {slice_id} owns {res}; no proven need for "
                      f"independent release or ops autonomy yet.",
              decision="Deploy as a bounded-context module in a modular monolith; "
                       "promote to microservice only when data-ownership + "
                       "independent release + ops autonomy are proven.",
              consequences="Lower operational cost; clear seam for later promotion.",
              evidence_refs=evidence_refs),
          ADR(number=2, title="Extract Product Lines for the writer path",
              status="accepted",
              context=f"{slice_id} mutates {res} (identity-drift hazard if dual-write).",
              decision="Use Extract Product Lines: the new service is the single "
                       "writer of its owned data; readers migrate later.",
              consequences="No dual-write; identity-drift writers stay single-system.",
              evidence_refs=evidence_refs),
          ADR(number=3, title="Legacy Mimic write-back via anti-corruption layer",
              status="accepted",
              context="Un-migrated COBOL programs still read the owned files.",
              decision="An ACL serializes the Java result back to the exact "
                       "mainframe fixed-width record (COMP-3 / scale / sign preserved).",
              consequences="COBOL estate keeps running unchanged during strangler-fig.",
              evidence_refs=evidence_refs),
      ]
  ```
- [ ] Run `uv run pytest tests/unit/test_adr.py` — expected PASS (2 passed).
- [ ] Commit: `feat(design): ADR generator + Markdown renderer with embedded lineage`

---

## Task 5 — Mimic field layout: copybook → fixed-width offsets (RECLN 300/350)

The Legacy Mimic adapter must reproduce the exact byte layout. The layout is read from `DataItem` graph nodes (Phase 1), never re-parsed. Grounded in `CVACT01Y` (`ACCOUNT-RECORD`, RECLN 300) and `CVTRA05Y` (`TRAN-RECORD`, RECLN 350).

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/mimic/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/mimic/layout.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/account_layout_cvact01y.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_mimic_layout.py`

Steps:
- [ ] Create fixture `tests/fixtures/account_layout_cvact01y.json` (DataItem-shaped, from CVACT01Y):
  ```json
  [
    {"simpleName":"ACCT-ID","picture":"9(11)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-ACTIVE-STATUS","picture":"X(01)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-CURR-BAL","picture":"S9(10)V99","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-CREDIT-LIMIT","picture":"S9(10)V99","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-CASH-CREDIT-LIMIT","picture":"S9(10)V99","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-OPEN-DATE","picture":"X(10)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-EXPIRAION-DATE","picture":"X(10)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-REISSUE-DATE","picture":"X(10)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-CURR-CYC-CREDIT","picture":"S9(10)V99","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-CURR-CYC-DEBIT","picture":"S9(10)V99","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-ADDR-ZIP","picture":"X(10)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"ACCT-GROUP-ID","picture":"X(10)","usage":"DISPLAY","occurs":0,"redefines":null},
    {"simpleName":"FILLER","picture":"X(178)","usage":"DISPLAY","occurs":0,"redefines":null}
  ]
  ```
- [ ] Write failing test `tests/unit/test_mimic_layout.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.mimic.layout import pic_width, build_layout, Field

  FIX = Path(__file__).parents[1] / "fixtures" / "account_layout_cvact01y.json"

  def test_pic_width_display_numeric_and_signed_scaled():
      assert pic_width("X(10)", "DISPLAY") == 10
      assert pic_width("9(11)", "DISPLAY") == 11
      # S9(10)V99 DISPLAY: 10 + 2 digit positions = 12 chars (sign overpunched, V implied)
      assert pic_width("S9(10)V99", "DISPLAY") == 12

  def test_pic_width_comp3_packed_decimal():
      # COMP-3 packs 2 digits/byte + sign nibble: ceil((digits+1)/2)
      assert pic_width("S9(10)V99", "COMP-3") == 7   # 12 digits -> ceil(13/2)=7
      assert pic_width("9(11)", "COMP-3") == 6        # 11 digits -> ceil(12/2)=6

  def test_build_layout_recln_300_account_record():
      items = json.loads(FIX.read_text())
      layout = build_layout(items)
      assert sum(f.length for f in layout) == 300        # RECLN 300 exactly
      acct_id = layout[0]
      assert acct_id == Field(name="ACCT-ID", offset=0, length=11,
                              picture="9(11)", usage="DISPLAY", scale=0, signed=False)
      curr_bal = next(f for f in layout if f.name == "ACCT-CURR-BAL")
      assert curr_bal.offset == 12 and curr_bal.length == 12
      assert curr_bal.scale == 2 and curr_bal.signed is True
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_layout.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/mimic/__init__.py` (empty), then `src/cobol_modernizer/mimic/layout.py`:
  ```python
  """Copybook DataItem -> fixed-width field layout. Drives the Legacy Mimic codec.
  Layout is computed from v2 DataItem graph nodes, not re-parsed from source."""
  from __future__ import annotations

  import re
  from dataclasses import dataclass

  _PIC_NUM = re.compile(r"9(?:\((\d+)\))?")
  _PIC_X = re.compile(r"X(?:\((\d+)\))?")


  @dataclass(frozen=True)
  class Field:
      name: str
      offset: int
      length: int
      picture: str
      usage: str
      scale: int        # digits after implied V
      signed: bool


  def _count(token_re: re.Pattern, pic: str) -> int:
      """Total digit/char count for repeated occurrences of a PIC token."""
      total = 0
      for m in token_re.finditer(pic):
          total += int(m.group(1)) if m.group(1) else 1
      return total


  def _digits_and_scale(pic: str) -> tuple[int, int]:
      """Total numeric digit positions and scale (digits right of V)."""
      whole, frac = (pic.split("V", 1) + [""])[:2] if "V" in pic else (pic, "")
      return _count(_PIC_NUM, whole) + _count(_PIC_NUM, frac), _count(_PIC_NUM, frac)


  def pic_width(picture: str, usage: str | None) -> int:
      pic = picture.upper()
      if pic.startswith("X") and "9" not in pic:
          return _count(_PIC_X, pic)
      digits, _ = _digits_and_scale(pic)
      if usage and usage.upper() in ("COMP-3", "PACKED-DECIMAL"):
          return (digits + 1 + 1) // 2          # ceil((digits+1)/2): 2 digits/byte + sign
      return digits                              # zoned/DISPLAY: 1 char per digit (V implied, sign overpunched)


  def build_layout(items: list[dict]) -> list[Field]:
      fields: list[Field] = []
      offset = 0
      for it in items:
          pic = (it.get("picture") or "").upper()
          usage = it.get("usage") or "DISPLAY"
          occurs = it.get("occurs") or 0
          width = pic_width(pic, usage)
          _, scale = _digits_and_scale(pic) if ("9" in pic) else (0, 0)
          length = width * (occurs or 1)
          fields.append(Field(name=it["simpleName"], offset=offset, length=length,
                              picture=pic, usage=usage, scale=scale,
                              signed=pic.startswith("S")))
          offset += length
      return fields
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_layout.py` — expected PASS (3 passed).
- [ ] Commit: `feat(mimic): copybook DataItem -> fixed-width layout (RECLN 300/350)`

---

## Task 6 — Mimic codec: COMP-3 / zoned-decimal / scale round-trip (no identity drift)

This is the numeric-fidelity core. The exit criterion "no identity drift" lives or dies here: `ACCT-CURR-BAL` is `S9(10)V99`, updated by `ADD DALYTRAN-AMT TO ACCT-CURR-BAL` then `REWRITE`. A scale/sign error silently corrupts balances.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/mimic/codec.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_mimic_codec.py`

Steps:
- [ ] Write failing test `tests/unit/test_mimic_codec.py`:
  ```python
  from decimal import Decimal
  from cobol_modernizer.mimic.codec import (
      encode_zoned, decode_zoned, encode_comp3, decode_comp3,
  )

  def test_zoned_unsigned_pads_left_with_zeros():
      assert encode_zoned(Decimal("123"), digits=11, scale=0, signed=False) == b"00000000123"

  def test_zoned_signed_scaled_roundtrip():
      # S9(10)V99, value 1234.56 -> 12 digit chars, last digit sign-overpunched.
      enc = encode_zoned(Decimal("1234.56"), digits=12, scale=2, signed=True)
      assert len(enc) == 12
      assert decode_zoned(enc, scale=2, signed=True) == Decimal("1234.56")

  def test_zoned_negative_overpunch_roundtrip():
      enc = encode_zoned(Decimal("-7.05"), digits=12, scale=2, signed=True)
      assert decode_zoned(enc, scale=2, signed=True) == Decimal("-7.05")

  def test_comp3_packed_roundtrip_signed_scaled():
      # S9(10)V99 COMP-3 -> 7 bytes; sign nibble C(+)/D(-).
      enc = encode_comp3(Decimal("1234.56"), digits=12, scale=2, signed=True)
      assert len(enc) == 7
      assert enc[-1] & 0x0F == 0x0C                      # positive sign nibble
      assert decode_comp3(enc, scale=2, signed=True) == Decimal("1234.56")
      neg = encode_comp3(Decimal("-1234.56"), digits=12, scale=2, signed=True)
      assert neg[-1] & 0x0F == 0x0D                      # negative sign nibble
      assert decode_comp3(neg, scale=2, signed=True) == Decimal("-1234.56")

  def test_comp3_balance_update_is_exact():
      # posting: 1000.00 + (-250.50) = 749.50, no float drift
      bal = decode_comp3(encode_comp3(Decimal("1000.00"), 12, 2, True), 2, True)
      amt = decode_comp3(encode_comp3(Decimal("-250.50"), 12, 2, True), 2, True)
      assert bal + amt == Decimal("749.50")
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_codec.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/mimic/codec.py`:
  ```python
  """Mainframe numeric codecs. Decimal-exact (never float) so balance updates
  reproduce COBOL packed/zoned arithmetic with no identity drift.

  Overpunch table (EBCDIC-agnostic ASCII convention used by GnuCOBOL DISPLAY):
  positive last digit 0-9 stays '0'-'9'; negative maps 0-9 -> '}JKLMNOPQR'.
  COMP-3: 2 digits per byte, trailing sign nibble C (+) / D (-)."""
  from __future__ import annotations

  from decimal import Decimal

  _NEG_OVERPUNCH = "}JKLMNOPQR"   # -0..-9
  _NEG_DECODE = {c: i for i, c in enumerate(_NEG_OVERPUNCH)}


  def _digit_string(value: Decimal, digits: int, scale: int) -> tuple[str, bool]:
      """Return (zero-padded unsigned digit string of length `digits`, is_negative)."""
      neg = value < 0
      scaled = (abs(value) * (10 ** scale)).to_integral_value()
      s = str(int(scaled)).rjust(digits, "0")
      if len(s) > digits:
          s = s[-digits:]            # COBOL truncates high-order on overflow
      return s, neg


  def encode_zoned(value: Decimal, *, digits: int, scale: int, signed: bool) -> bytes:
      s, neg = _digit_string(value, digits, scale)
      if signed and neg:
          s = s[:-1] + _NEG_OVERPUNCH[int(s[-1])]
      return s.encode("ascii")


  def decode_zoned(raw: bytes, *, scale: int, signed: bool) -> Decimal:
      s = raw.decode("ascii")
      neg = False
      if signed and s and s[-1] in _NEG_DECODE:
          s = s[:-1] + str(_NEG_DECODE[s[-1]])
          neg = True
      val = Decimal(s) / (10 ** scale)
      return -val if neg else val


  def encode_comp3(value: Decimal, *, digits: int, scale: int, signed: bool) -> bytes:
      s, neg = _digit_string(value, digits, scale)
      if len(s) % 2 == 0:           # COMP-3 stores an odd number of digit nibbles + sign
          s = "0" + s
      sign_nibble = 0x0D if (signed and neg) else 0x0C
      nibbles = [int(c) for c in s] + [sign_nibble]
      out = bytearray()
      for i in range(0, len(nibbles), 2):
          out.append((nibbles[i] << 4) | nibbles[i + 1])
      return bytes(out)


  def decode_comp3(raw: bytes, *, scale: int, signed: bool) -> Decimal:
      nibbles: list[int] = []
      for b in raw:
          nibbles.append(b >> 4)
          nibbles.append(b & 0x0F)
      sign = nibbles.pop()
      digits = "".join(str(n) for n in nibbles)
      val = Decimal(digits) / (10 ** scale)
      return -val if (signed and sign == 0x0D) else val
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_codec.py` — expected PASS (5 passed).
- [ ] Commit: `feat(mimic): Decimal-exact COMP-3/zoned codecs (no identity drift)`

---

## Task 7 — Mimic write-back: DTO → mainframe ACCOUNT-RECORD bytes (ACL)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/mimic/writeback.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_mimic_writeback.py`

Steps:
- [ ] Write failing test `tests/unit/test_mimic_writeback.py`:
  ```python
  import json
  from decimal import Decimal
  from pathlib import Path
  from cobol_modernizer.mimic.layout import build_layout
  from cobol_modernizer.mimic.writeback import LegacyMimicWriter

  FIX = Path(__file__).parents[1] / "fixtures" / "account_layout_cvact01y.json"

  def _writer():
      return LegacyMimicWriter(build_layout(json.loads(FIX.read_text())))

  def test_writeback_record_is_exactly_recln_300():
      w = _writer()
      rec = w.encode({
          "ACCT-ID": Decimal("12345678901"),
          "ACCT-ACTIVE-STATUS": "Y",
          "ACCT-CURR-BAL": Decimal("749.50"),
          "ACCT-CREDIT-LIMIT": Decimal("5000.00"),
          "ACCT-CASH-CREDIT-LIMIT": Decimal("1000.00"),
          "ACCT-OPEN-DATE": "2020-01-01",
          "ACCT-EXPIRAION-DATE": "2030-01-01",
          "ACCT-REISSUE-DATE": "2025-01-01",
          "ACCT-CURR-CYC-CREDIT": Decimal("0.00"),
          "ACCT-CURR-CYC-DEBIT": Decimal("250.50"),
          "ACCT-ADDR-ZIP": "12345",
          "ACCT-GROUP-ID": "GRP1",
      })
      assert len(rec) == 300

  def test_writeback_balance_field_round_trips_through_decode():
      w = _writer()
      rec = w.encode({"ACCT-ID": Decimal("1"), "ACCT-CURR-BAL": Decimal("-7.05")})
      decoded = w.decode(rec)
      assert decoded["ACCT-CURR-BAL"] == Decimal("-7.05")  # identity preserved

  def test_unknown_field_is_rejected_acl_boundary():
      import pytest
      w = _writer()
      with pytest.raises(KeyError, match="not in copybook layout"):
          w.encode({"BOGUS-FIELD": "x"})
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_writeback.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/mimic/writeback.py`:
  ```python
  """Legacy Mimic write-back ACL: encodes a Java-result DTO into the exact
  mainframe fixed-width record so un-migrated COBOL keeps reading it. The ACL
  rejects any field not in the copybook layout (corruption guard)."""
  from __future__ import annotations

  from decimal import Decimal

  from cobol_modernizer.mimic.codec import (
      decode_comp3, decode_zoned, encode_comp3, encode_zoned,
  )
  from cobol_modernizer.mimic.layout import Field


  class LegacyMimicWriter:
      def __init__(self, layout: list[Field]) -> None:
          self._layout = layout
          self._by_name = {f.name: f for f in layout}
          self._reclen = sum(f.length for f in layout)

      def encode(self, values: dict[str, object]) -> bytes:
          for name in values:
              if name not in self._by_name:
                  raise KeyError(f"{name!r} not in copybook layout")
          buf = bytearray(b" " * self._reclen)
          for f in self._layout:
              if f.name == "FILLER" or f.name not in values:
                  continue
              cell = self._encode_field(f, values[f.name])
              buf[f.offset:f.offset + f.length] = cell.ljust(f.length, b"\x00" if "9" in f.picture and f.usage.upper().startswith("COMP") else b" ")[:f.length]
          return bytes(buf)

      def decode(self, record: bytes) -> dict[str, object]:
          out: dict[str, object] = {}
          for f in self._layout:
              if f.name == "FILLER":
                  continue
              raw = record[f.offset:f.offset + f.length]
              out[f.name] = self._decode_field(f, raw)
          return out

      # --- per-field ---
      def _is_numeric(self, f: Field) -> bool:
          return "9" in f.picture

      def _digits(self, f: Field) -> int:
          # for zoned the byte length == digit count; for comp3 derive from picture
          if f.usage.upper().startswith("COMP") or f.usage.upper() == "PACKED-DECIMAL":
              return f.length * 2 - 1
          return f.length

      def _encode_field(self, f: Field, value: object) -> bytes:
          if not self._is_numeric(f):
              return str(value).encode("ascii")[:f.length].ljust(f.length, b" ")
          dec = value if isinstance(value, Decimal) else Decimal(str(value))
          if f.usage.upper().startswith("COMP") or f.usage.upper() == "PACKED-DECIMAL":
              return encode_comp3(dec, digits=self._digits(f), scale=f.scale, signed=f.signed)
          return encode_zoned(dec, digits=self._digits(f), scale=f.scale, signed=f.signed)

      def _decode_field(self, f: Field, raw: bytes) -> object:
          if not self._is_numeric(f):
              return raw.decode("ascii", "replace").rstrip()
          if f.usage.upper().startswith("COMP") or f.usage.upper() == "PACKED-DECIMAL":
              return decode_comp3(raw, scale=f.scale, signed=f.signed)
          return decode_zoned(raw, scale=f.scale, signed=f.signed)
  ```
- [ ] Run `uv run pytest tests/unit/test_mimic_writeback.py` — expected PASS (3 passed).
- [ ] Commit: `feat(mimic): write-back ACL DTO -> ACCOUNT-RECORD bytes with corruption guard`

---

## Task 8 — Spring Boot module scaffold (deterministic; quality plugins wired)

The agent must not invent build wiring. The scaffold writes a deterministic Maven module (Java 25, Spring Boot 3.3) with ArchUnit/SpotBugs/Error Prone/Checkstyle pre-configured so `mvn verify` enforces all four. The agent only fills in business code + tests.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/scaffold.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_codegen_scaffold.py`

Steps:
- [ ] Write failing test `tests/unit/test_codegen_scaffold.py`:
  ```python
  from pathlib import Path
  from cobol_modernizer.codegen.scaffold import scaffold_module

  def test_scaffold_writes_pom_with_all_four_quality_plugins(tmp_path):
      root = scaffold_module(tmp_path, module="carddemo-posting",
                             base_package="com.cobolmodernizer.posting")
      pom = (root / "pom.xml").read_text()
      assert "spring-boot-starter" in pom and "<java.version>25</java.version>" in pom
      assert "spotbugs-maven-plugin" in pom
      assert "error_prone_core" in pom
      assert "maven-checkstyle-plugin" in pom
      assert "archunit-junit5" in pom

  def test_scaffold_creates_main_and_test_source_roots(tmp_path):
      root = scaffold_module(tmp_path, module="carddemo-posting",
                             base_package="com.cobolmodernizer.posting")
      assert (root / "src/main/java/com/cobolmodernizer/posting").is_dir()
      assert (root / "src/test/java/com/cobolmodernizer/posting").is_dir()
      assert (root / "config/checkstyle.xml").exists()

  def test_scaffold_is_idempotent(tmp_path):
      r1 = scaffold_module(tmp_path, module="m", base_package="com.x")
      r2 = scaffold_module(tmp_path, module="m", base_package="com.x")
      assert r1 == r2 and (r2 / "pom.xml").exists()
  ```
- [ ] Run `uv run pytest tests/unit/test_codegen_scaffold.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/codegen/__init__.py` (empty), then `src/cobol_modernizer/codegen/scaffold.py`:
  ```python
  """Deterministic Spring Boot 3.3 / Java 25 Maven module scaffold with all four
  quality gates wired (ArchUnit, SpotBugs+FindSecBugs, Error Prone, Checkstyle).
  No LLM here — the agent only fills in src code/tests."""
  from __future__ import annotations

  from pathlib import Path

  _POM = """<?xml version="1.0" encoding="UTF-8"?>
  <project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <parent>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-parent</artifactId>
      <version>3.3.4</version>
    </parent>
    <groupId>com.cobolmodernizer</groupId>
    <artifactId>{module}</artifactId>
    <version>0.1.0</version>
    <properties>
      <java.version>25</java.version>
      <maven.compiler.release>25</maven.compiler.release>
    </properties>
    <dependencies>
      <dependency><groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter</artifactId></dependency>
      <dependency><groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
      <dependency><groupId>com.tngtech.archunit</groupId>
        <artifactId>archunit-junit5</artifactId><version>1.3.0</version><scope>test</scope></dependency>
    </dependencies>
    <build><plugins>
      <plugin><groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration><compilerArgs>
          <arg>-XDcompilePolicy=simple</arg>
          <arg>-Xplugin:ErrorProne</arg>
        </compilerArgs><annotationProcessorPaths>
          <path><groupId>com.google.errorprone</groupId>
            <artifactId>error_prone_core</artifactId><version>2.28.0</version></path>
        </annotationProcessorPaths></configuration></plugin>
      <plugin><groupId>com.github.spotbugs</groupId>
        <artifactId>spotbugs-maven-plugin</artifactId><version>4.8.6.2</version>
        <configuration><effort>Max</effort><threshold>Low</threshold>
          <plugins><plugin><groupId>com.h3xstream.findsecbugs</groupId>
            <artifactId>findsecbugs-plugin</artifactId><version>1.13.0</version></plugin></plugins>
        </configuration>
        <executions><execution><phase>verify</phase><goals><goal>check</goal></goals></execution></executions></plugin>
      <plugin><groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-checkstyle-plugin</artifactId><version>3.5.0</version>
        <configuration><configLocation>config/checkstyle.xml</configLocation>
          <failOnViolation>true</failOnViolation></configuration>
        <executions><execution><phase>verify</phase><goals><goal>check</goal></goals></execution></executions></plugin>
    </plugins></build>
  </project>
  """

  _CHECKSTYLE = """<?xml version="1.0"?>
  <!DOCTYPE module PUBLIC "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
   "https://checkstyle.org/dtds/configuration_1_3.dtd">
  <module name="Checker">
    <module name="TreeWalker">
      <module name="UnusedImports"/>
      <module name="MissingOverride"/>
      <module name="EmptyBlock"/>
    </module>
  </module>
  """


  def scaffold_module(parent: Path, *, module: str, base_package: str) -> Path:
      root = Path(parent) / module
      pkg = base_package.replace(".", "/")
      (root / f"src/main/java/{pkg}").mkdir(parents=True, exist_ok=True)
      (root / f"src/test/java/{pkg}").mkdir(parents=True, exist_ok=True)
      (root / "config").mkdir(parents=True, exist_ok=True)
      (root / "pom.xml").write_text(_POM.format(module=module), encoding="utf-8")
      (root / "config/checkstyle.xml").write_text(_CHECKSTYLE, encoding="utf-8")
      return root
  ```
- [ ] Run `uv run pytest tests/unit/test_codegen_scaffold.py` — expected PASS (3 passed).
- [ ] Commit: `feat(codegen): deterministic Spring Boot module scaffold with 4 quality gates`

---

## Task 9 — ArchUnit rule source generation (bounded-context + data-ownership)

ArchUnit enforces the architecture *as compiled code*. The generator emits a JUnit5 ArchUnit test asserting the bounded-context package owns its repository and no other context's package touches its owned resources.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/archrules.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_archrules.py`

Steps:
- [ ] Write failing test `tests/unit/test_archrules.py`:
  ```python
  from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
  from cobol_modernizer.codegen.archrules import render_archunit_test

  def _design():
      return ServiceDesign(slice_id="posting", deployment="modular_monolith",
          context=BoundedContext.transaction_processing,
          owned_resources=["TRANSACT", "ACCTDAT"],
          transition_pattern="extract_product_lines+legacy_mimic",
          components=["PostingService", "PostingRepository"],
          evidence_map={"DR-1": ["CBTRN02C"]})

  def test_archunit_source_pins_layered_architecture_and_package():
      src = render_archunit_test(_design(), base_package="com.cobolmodernizer.posting")
      assert "@AnalyzeClasses(packages = \"com.cobolmodernizer.posting\")" in src
      assert "layeredArchitecture()" in src
      assert "Repository" in src and "Service" in src
      assert "noClasses()" in src  # forbids cross-layer leak
      assert src.strip().endswith("}")

  def test_archunit_source_is_compilable_junit5_class():
      src = render_archunit_test(_design(), base_package="com.cobolmodernizer.posting")
      assert "import com.tngtech.archunit.junit.AnalyzeClasses;" in src
      assert "class ArchitectureTest" in src
  ```
- [ ] Run `uv run pytest tests/unit/test_archrules.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/codegen/archrules.py`:
  ```python
  """Emit the ArchUnit JUnit5 test that pins the bounded-context layering. The
  architecture rule becomes a compiled, runnable assertion in `mvn verify`."""
  from __future__ import annotations

  from cobol_modernizer.design.schema import ServiceDesign

  _TEMPLATE = '''package {pkg};

  import com.tngtech.archunit.junit.AnalyzeClasses;
  import com.tngtech.archunit.junit.ArchTest;
  import com.tngtech.archunit.lang.ArchRule;
  import static com.tngtech.archunit.library.Architectures.layeredArchitecture;
  import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

  @AnalyzeClasses(packages = "{pkg}")
  class ArchitectureTest {{

      @ArchTest
      static final ArchRule layering = layeredArchitecture().consideringAllDependencies()
          .layer("Controller").definedBy("{pkg}.api..")
          .layer("Service").definedBy("{pkg}.service..")
          .layer("Repository").definedBy("{pkg}.repository..")
          .whereLayer("Controller").mayNotBeAccessedByAnyLayer()
          .whereLayer("Service").mayOnlyBeAccessedByLayers("Controller")
          .whereLayer("Repository").mayOnlyBeAccessedByLayers("Service");

      @ArchTest
      static final ArchRule repository_only_from_service =
          noClasses().that().resideInAPackage("{pkg}.api..")
              .should().dependOnClassesThat().resideInAPackage("{pkg}.repository..");
  }}
  '''


  def render_archunit_test(design: ServiceDesign, *, base_package: str) -> str:
      return _TEMPLATE.format(pkg=base_package)
  ```
- [ ] Run `uv run pytest tests/unit/test_archrules.py` — expected PASS (2 passed).
- [ ] Commit: `feat(codegen): generate ArchUnit layered-architecture test source`

---

## Task 10 — Codegen result models + tests-first generator (TDD ordering enforced)

The generator must emit failing tests **before** code (TDD), with each generated artifact carrying an `evidence_map`. The agent uses the read-only graph MCP server + golden fixtures; it never sees raw dumps. The unit test uses a **fake `AgentRunner`** (per foundation conventions) so no live model is called.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/schema.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/generator.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_codegen_generator.py`

Steps:
- [ ] Write failing test `tests/unit/test_codegen_generator.py`:
  ```python
  import pytest
  from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
  from cobol_modernizer.codegen.generator import generate_slice, CODEGEN_SCHEMA

  class FakeRunner:
      """Foundation-style fake AgentRunner returning canned structured output."""
      def __init__(self, payload): self.payload = payload; self.calls = []
      async def run_structured(self, **kw):
          self.calls.append(kw); return self.payload

  PAYLOAD = {"files": [
      {"path": "src/test/java/com/cobolmodernizer/posting/PostingServiceTest.java",
       "kind": "test", "content": "class PostingServiceTest {}",
       "evidence": ["CBTRN02C.2000-POST-TRANSACTION"]},
      {"path": "src/main/java/com/cobolmodernizer/posting/service/PostingService.java",
       "kind": "main", "content": "class PostingService {}",
       "evidence": ["CBTRN02C.2800-UPDATE-ACCOUNT-REC"]},
  ]}

  async def test_generator_emits_tests_before_main_and_evidence_map():
      runner = FakeRunner(PAYLOAD)
      project = await generate_slice(
          runner=runner, server=None, model="claude-sonnet-4-6",
          brd_json='{"sections":[]}', golden_summary="after_acctfile diff",
          allowed_tools=["mcp__graph__get_source_slice"])
      assert isinstance(project, GeneratedProject)
      # TDD invariant: a test file precedes its production file
      kinds = [f.kind for f in project.files]
      assert kinds.index("test") < kinds.index("main")
      assert project.evidence_map["CBTRN02C.2800-UPDATE-ACCOUNT-REC"]

  async def test_generator_rejects_run_with_no_test_file():
      runner = FakeRunner({"files": [
          {"path": "X.java", "kind": "main", "content": "x", "evidence": ["CBTRN02C"]}]})
      with pytest.raises(ValueError, match="no failing test"):
          await generate_slice(runner=runner, server=None, model="m",
                               brd_json="{}", golden_summary="", allowed_tools=[])

  def test_codegen_schema_requires_files():
      assert "files" in CODEGEN_SCHEMA["required"]
  ```
- [ ] Run `uv run pytest tests/unit/test_codegen_generator.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/codegen/schema.py`:
  ```python
  from __future__ import annotations

  from typing import Literal

  from pydantic import BaseModel, Field


  class GeneratedFile(BaseModel):
      path: str
      kind: Literal["test", "main"]
      content: str
      evidence: list[str] = Field(default_factory=list)


  class GeneratedProject(BaseModel):
      slice_id: str = "posting"
      files: list[GeneratedFile]
      evidence_map: dict[str, list[str]] = Field(default_factory=dict)


  class RepairAttempt(BaseModel):
      attempt: int
      failing_gate: str          # compile|test|archunit|spotbugs|errorprone|checkstyle
      log_excerpt: str
      patched_files: list[str]


  class CodegenResult(BaseModel):
      project: GeneratedProject
      attempts: list[RepairAttempt] = Field(default_factory=list)
      passed: bool
  ```
- [ ] Create `src/cobol_modernizer/codegen/generator.py`:
  ```python
  """TDD codegen agent. Reads BRD + golden-fixture summary + read-only graph
  slices; emits failing tests THEN production code. Each file carries lineage.
  role='codegen' (Sonnet) via the foundation harness (tools=[], json_schema)."""
  from __future__ import annotations

  from typing import Any

  from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject

  CODEGEN_SCHEMA: dict[str, Any] = {
      "type": "object",
      "properties": {
          "files": {"type": "array", "items": {"type": "object", "properties": {
              "path": {"type": "string"},
              "kind": {"type": "string", "enum": ["test", "main"]},
              "content": {"type": "string"},
              "evidence": {"type": "array", "items": {"type": "string"}},
          }, "required": ["path", "kind", "content"]}},
      },
      "required": ["files"],
  }

  CODEGEN_SYSTEM = (
      "You migrate ONE COBOL writer slice to Spring Boot using strict TDD. "
      "FIRST emit JUnit5 tests that assert the BRD's required behavior against the "
      "golden fixtures (kind='test'); THEN emit the minimal production code "
      "(kind='main'). Use ONLY the read-only graph tools and the supplied evidence; "
      "every file MUST list the graph entity ids it is grounded in. Do NOT invent "
      "behavior absent from the BRD (accidental legacy behavior is excluded)."
  )


  async def generate_slice(*, runner, server, model: str, brd_json: str,
                           golden_summary: str, allowed_tools: list[str]) -> GeneratedProject:
      prompt = (
          f"## BRD\n```json\n{brd_json}\n```\n"
          f"## Golden-master summary (the oracle)\n{golden_summary}\n"
          "Emit tests first, then code."
      )
      raw = await runner.run_structured(
          system=CODEGEN_SYSTEM, prompt=prompt, server=server,
          allowed_tools=allowed_tools, model=model, max_turns=12, schema=CODEGEN_SCHEMA)
      files = [GeneratedFile(**f) for f in raw.get("files", [])]
      if not any(f.kind == "test" for f in files):
          raise ValueError("codegen produced no failing test (TDD violated)")
      evidence_map: dict[str, list[str]] = {}
      for f in files:
          for ref in f.evidence:
              evidence_map.setdefault(ref, []).append(f.path)
      return GeneratedProject(files=files, evidence_map=evidence_map)
  ```
- [ ] Run `uv run pytest tests/unit/test_codegen_generator.py` — expected PASS (3 passed).
- [ ] Commit: `feat(codegen): tests-first generator with evidence_map (TDD enforced)`

---

## Task 11 — Quality gate: parse `mvn verify` output → structured QualityReport

The Build Lab runs `mvn verify`; this turns its output into a judgeable report covering all six checks. "Compilable is never sufficient" — every check must pass.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/quality_gate.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_quality_gate.py`

Steps:
- [ ] Write failing test `tests/unit/test_quality_gate.py`:
  ```python
  from cobol_modernizer.codegen.quality_gate import parse_mvn_output, QualityReport

  PASS_LOG = """[INFO] BUILD SUCCESS
  [INFO] Tests run: 14, Failures: 0, Errors: 0, Skipped: 0
  [INFO] BUILD SUCCESS"""

  FAIL_LOG = """[ERROR] COMPILATION ERROR :
  [ERROR] PostingService.java:[42,8] cannot find symbol
  [INFO] Tests run: 14, Failures: 2, Errors: 0
  [ERROR] SpotBugs: 3 bug(s) found
  [ERROR] Checkstyle: 1 violation
  [ERROR] BUILD FAILURE"""

  def test_clean_build_passes_all_gates():
      rep = parse_mvn_output(PASS_LOG, exit_code=0)
      assert rep.passed is True
      assert rep.compile_ok and rep.tests_ok
      assert rep.failing_gate is None

  def test_failing_build_reports_first_failing_gate_compile_first():
      rep = parse_mvn_output(FAIL_LOG, exit_code=1)
      assert rep.passed is False
      assert rep.compile_ok is False
      assert rep.failing_gate == "compile"        # compile precedes test/spotbugs
      assert rep.test_failures == 2
      assert rep.spotbugs_bugs == 3
      assert "cannot find symbol" in rep.log_excerpt

  def test_test_failure_when_compile_ok():
      log = "[INFO] BUILD FAILURE\n[INFO] Tests run: 5, Failures: 1, Errors: 0"
      rep = parse_mvn_output(log, exit_code=1)
      assert rep.compile_ok is True and rep.failing_gate == "test"
  ```
- [ ] Run `uv run pytest tests/unit/test_quality_gate.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/codegen/quality_gate.py`:
  ```python
  """Parse `mvn verify` output into a structured QualityReport. Failure priority
  (matches build phase order): compile -> test -> errorprone -> spotbugs ->
  checkstyle -> archunit. 'Compilable' alone never passes the gate."""
  from __future__ import annotations

  import re

  from pydantic import BaseModel

  _TESTS = re.compile(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)")
  _SPOTBUGS = re.compile(r"SpotBugs:\s*(\d+)\s+bug", re.I)
  _CHECKSTYLE = re.compile(r"Checkstyle:\s*(\d+)\s+violation", re.I)


  class QualityReport(BaseModel):
      passed: bool
      compile_ok: bool
      tests_ok: bool
      test_failures: int
      spotbugs_bugs: int
      checkstyle_violations: int
      errorprone_ok: bool
      archunit_ok: bool
      failing_gate: str | None
      log_excerpt: str


  def parse_mvn_output(text: str, *, exit_code: int) -> QualityReport:
      compile_ok = "COMPILATION ERROR" not in text and "cannot find symbol" not in text
      m = _TESTS.search(text)
      failures = (int(m.group(2)) + int(m.group(3))) if m else 0
      tests_ok = failures == 0
      sb = int(_SPOTBUGS.search(text).group(1)) if _SPOTBUGS.search(text) else 0
      cs = int(_CHECKSTYLE.search(text).group(1)) if _CHECKSTYLE.search(text) else 0
      errorprone_ok = "[Error Prone]" not in text and "error-prone" not in text.lower() or compile_ok
      archunit_ok = "ArchRule" not in text or "Architecture Violation" not in text

      failing_gate: str | None = None
      if not compile_ok:
          failing_gate = "compile"
      elif not tests_ok:
          failing_gate = "test"
      elif sb > 0:
          failing_gate = "spotbugs"
      elif cs > 0:
          failing_gate = "checkstyle"
      elif "Architecture Violation" in text:
          failing_gate = "archunit"

      passed = (exit_code == 0 and compile_ok and tests_ok
                and sb == 0 and cs == 0 and failing_gate is None)

      excerpt = "\n".join(l for l in text.splitlines()
                          if "ERROR" in l or "Failures" in l)[:2000]
      return QualityReport(
          passed=passed, compile_ok=compile_ok, tests_ok=tests_ok,
          test_failures=failures, spotbugs_bugs=sb, checkstyle_violations=cs,
          errorprone_ok=errorprone_ok, archunit_ok=archunit_ok,
          failing_gate=failing_gate, log_excerpt=excerpt or text[:2000])
  ```
- [ ] Run `uv run pytest tests/unit/test_quality_gate.py` — expected PASS (3 passed).
- [ ] Commit: `feat(codegen): mvn verify output parser -> QualityReport (all 6 gates)`

---

## Task 12 — Repair loop: feed logs back, escalate hard failures, bounded attempts + cost cap

The repair loop is the heart of "repair loop feeding logs back". It feeds the failing `QualityReport.log_excerpt` to the agent (`role="repair"`, Opus), applies patched files, re-runs the Build Lab, and stops on pass / max attempts / budget kill. Build Lab and runner are injected (fakes in the unit test).

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/codegen/repair_loop.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_repair_loop.py`

Steps:
- [ ] Write failing test `tests/unit/test_repair_loop.py`:
  ```python
  import pytest
  from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
  from cobol_modernizer.codegen.quality_gate import QualityReport
  from cobol_modernizer.codegen.repair_loop import run_repair_loop, BudgetGuard

  def _report(passed, gate=None):
      return QualityReport(passed=passed, compile_ok=passed, tests_ok=passed,
          test_failures=0 if passed else 1, spotbugs_bugs=0, checkstyle_violations=0,
          errorprone_ok=passed, archunit_ok=passed,
          failing_gate=None if passed else gate, log_excerpt="boom" if not passed else "")

  class FakeBuildLab:
      """Returns FAIL then PASS — proves the loop converges."""
      def __init__(self, reports): self.reports = list(reports); self.runs = 0
      def verify(self, project): self.runs += 1; return self.reports.pop(0)

  class FakeRunner:
      def __init__(self): self.calls = 0
      async def run_structured(self, **kw):
          self.calls += 1
          return {"files": [{"path": "src/main/java/X.java", "kind": "main",
                             "content": "fixed", "evidence": ["CBTRN02C"]}]}

  class OkGuard:
      def check(self): pass            # never trips
  class KillGuard:
      def check(self): raise RuntimeError("budget killed")

  def _project():
      return GeneratedProject(files=[GeneratedFile(path="src/main/java/X.java",
          kind="main", content="broken", evidence=["CBTRN02C"])],
          evidence_map={"CBTRN02C": ["src/main/java/X.java"]})

  async def test_loop_converges_and_records_attempts():
      lab = FakeBuildLab([_report(False, "test"), _report(True)])
      runner = FakeRunner()
      result = await run_repair_loop(_project(), build_lab=lab, runner=runner,
          server=None, model="claude-opus-4-8", max_attempts=3, guard=OkGuard())
      assert result.passed is True
      assert len(result.attempts) == 1            # one repair before passing
      assert result.attempts[0].failing_gate == "test"

  async def test_loop_stops_at_max_attempts():
      lab = FakeBuildLab([_report(False, "test")] * 5)
      result = await run_repair_loop(_project(), build_lab=lab, runner=FakeRunner(),
          server=None, model="m", max_attempts=2, guard=OkGuard())
      assert result.passed is False and len(result.attempts) == 2

  async def test_loop_aborts_on_budget_kill():
      lab = FakeBuildLab([_report(False, "test")] * 5)
      with pytest.raises(RuntimeError, match="budget killed"):
          await run_repair_loop(_project(), build_lab=lab, runner=FakeRunner(),
              server=None, model="m", max_attempts=5, guard=KillGuard())
  ```
- [ ] Run `uv run pytest tests/unit/test_repair_loop.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/codegen/repair_loop.py`:
  ```python
  """Repair loop: build -> on fail, feed the log excerpt + failing gate back to a
  repair agent (role='repair', Opus) -> apply patches -> rebuild. Bounded by
  max_attempts and the cost-policy guard (kill-switch). The agent only ever sees
  structured logs + read-only graph, never raw dumps."""
  from __future__ import annotations

  from typing import Any, Protocol

  from cobol_modernizer.codegen.schema import (
      CodegenResult, GeneratedFile, GeneratedProject, RepairAttempt,
  )
  from cobol_modernizer.codegen.generator import CODEGEN_SCHEMA

  REPAIR_SYSTEM = (
      "A generated Spring Boot writer slice failed a quality gate. You are given "
      "the failing gate and the build log excerpt. Return ONLY the patched files "
      "(same JSON shape as codegen). Fix the root cause; do not weaken tests or "
      "suppress warnings. Preserve lineage (evidence)."
  )


  class BuildLab(Protocol):
      def verify(self, project: GeneratedProject) -> Any: ...   # -> QualityReport


  class BudgetGuard(Protocol):
      def check(self) -> None: ...   # raises if the cost kill-switch tripped


  def _apply_patches(project: GeneratedProject, patched: list[GeneratedFile]) -> GeneratedProject:
      by_path = {f.path: f for f in project.files}
      for p in patched:
          by_path[p.path] = p
      return GeneratedProject(slice_id=project.slice_id,
                              files=list(by_path.values()),
                              evidence_map=project.evidence_map)


  async def run_repair_loop(project: GeneratedProject, *, build_lab: BuildLab,
                            runner, server, model: str, max_attempts: int,
                            guard: BudgetGuard) -> CodegenResult:
      attempts: list[RepairAttempt] = []
      report = build_lab.verify(project)
      while not report.passed and len(attempts) < max_attempts:
          guard.check()                                   # may raise on kill-switch
          raw = await runner.run_structured(
              system=REPAIR_SYSTEM,
              prompt=(f"## Failing gate: {report.failing_gate}\n"
                      f"## Build log\n```\n{report.log_excerpt}\n```\n"
                      "Return patched files."),
              server=server, allowed_tools=["mcp__graph__get_source_slice",
                                             "mcp__graph__get_entity"],
              model=model, max_turns=8, schema=CODEGEN_SCHEMA)
          patched = [GeneratedFile(**f) for f in raw.get("files", [])]
          attempts.append(RepairAttempt(attempt=len(attempts) + 1,
              failing_gate=report.failing_gate or "unknown",
              log_excerpt=report.log_excerpt[:500],
              patched_files=[p.path for p in patched]))
          project = _apply_patches(project, patched)
          report = build_lab.verify(project)
      return CodegenResult(project=project, attempts=attempts, passed=report.passed)
  ```
- [ ] Run `uv run pytest tests/unit/test_repair_loop.py` — expected PASS (3 passed).
- [ ] Commit: `feat(codegen): repair loop feeding logs back, bounded + budget-guarded`

---

## Task 13 — Phase 5 orchestration: gated pipeline with cost cap + no-identity-drift exit

Wires the whole slice behind hard gates and the cost policy: seam (writer, identity-drift) → design + ADRs (design gate) → scaffold → codegen → repair (Build Lab) → mimic write-back → equivalence (Phase 3, no identity drift). Every stage records an `agent_run` / `gate` in Postgres and is cost-capped. Heavy dependencies (Build Lab, Equivalence Lab, GraphDeps) are injected so the unit test runs with fakes.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/orchestration/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/orchestration/phase5.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_phase5_orchestration.py`

Steps:
- [ ] Write failing test `tests/unit/test_phase5_orchestration.py`:
  ```python
  import pytest
  from cobol_modernizer.orchestration.phase5 import run_writer_slice, SliceOutcome

  class FakeEquiv:
      """Phase-3-shaped equivalence result."""
      def __init__(self, matched, drift): self.matched = matched; self.identity_drift = drift

  class FakeLab:
      def __init__(self, equiv): self.equiv = equiv
      def run_equivalence(self, project, golden): return self.equiv

  def _inputs(passed, matched=True, drift=False):
      # codegen_result, design_report, equiv lab
      from cobol_modernizer.codegen.schema import CodegenResult, GeneratedProject, GeneratedFile
      proj = GeneratedProject(files=[GeneratedFile(path="X.java", kind="main",
          content="c", evidence=["CBTRN02C"])], evidence_map={"CBTRN02C": ["X.java"]})
      return CodegenResult(project=proj, attempts=[], passed=passed), FakeLab(FakeEquiv(matched, drift))

  def test_slice_passes_when_code_and_equivalence_clean():
      codegen, lab = _inputs(passed=True, matched=True, drift=False)
      out = run_writer_slice(codegen_result=codegen, design_ok=True,
                             equivalence_lab=lab, golden="g")
      assert isinstance(out, SliceOutcome)
      assert out.passed is True and out.identity_drift is False
      assert out.cobol_path_retired is True   # clean equivalence -> COBOL can be fronted by ACL

  def test_identity_drift_blocks_slice():
      codegen, lab = _inputs(passed=True, matched=True, drift=True)
      out = run_writer_slice(codegen_result=codegen, design_ok=True,
                             equivalence_lab=lab, golden="g")
      assert out.passed is False and out.identity_drift is True
      assert out.cobol_path_retired is False

  def test_failing_quality_gate_blocks_before_equivalence():
      codegen, lab = _inputs(passed=False)
      out = run_writer_slice(codegen_result=codegen, design_ok=True,
                             equivalence_lab=lab, golden="g")
      assert out.passed is False and out.blocked_at == "code"

  def test_failing_design_gate_blocks_first():
      codegen, lab = _inputs(passed=True)
      out = run_writer_slice(codegen_result=codegen, design_ok=False,
                             equivalence_lab=lab, golden="g")
      assert out.passed is False and out.blocked_at == "design"
  ```
- [ ] Run `uv run pytest tests/unit/test_phase5_orchestration.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/orchestration/__init__.py` (empty), then `src/cobol_modernizer/orchestration/phase5.py`:
  ```python
  """Phase 5 writer-slice orchestration. Enforces the gate order from master plan §5:
  Design (owns its data) -> Code (compile+tests+ArchUnit+SpotBugs/EP/Checkstyle) ->
  Equivalence (golden-master within tolerance, NO identity drift). Only on a clean
  pass is the COBOL path eligible to be retired / fronted by the Legacy Mimic ACL."""
  from __future__ import annotations

  from typing import Any, Protocol

  from pydantic import BaseModel

  from cobol_modernizer.codegen.schema import CodegenResult


  class EquivalenceLab(Protocol):
      def run_equivalence(self, project: Any, golden: Any) -> Any: ...


  class SliceOutcome(BaseModel):
      passed: bool
      blocked_at: str | None          # design|code|equivalence|None
      identity_drift: bool
      cobol_path_retired: bool        # true only on clean equivalence (fronted by ACL)


  def run_writer_slice(*, codegen_result: CodegenResult, design_ok: bool,
                       equivalence_lab: EquivalenceLab, golden: Any) -> SliceOutcome:
      # Gate 1: Design (service owns its data).
      if not design_ok:
          return SliceOutcome(passed=False, blocked_at="design",
                              identity_drift=False, cobol_path_retired=False)
      # Gate 2: Code (all six quality gates via the repair loop's final report).
      if not codegen_result.passed:
          return SliceOutcome(passed=False, blocked_at="code",
                              identity_drift=False, cobol_path_retired=False)
      # Gate 3: Equivalence (golden-master, no identity drift).
      equiv = equivalence_lab.run_equivalence(codegen_result.project, golden)
      if getattr(equiv, "identity_drift", False):
          return SliceOutcome(passed=False, blocked_at="equivalence",
                              identity_drift=True, cobol_path_retired=False)
      if not getattr(equiv, "matched", False):
          return SliceOutcome(passed=False, blocked_at="equivalence",
                              identity_drift=False, cobol_path_retired=False)
      # Clean pass: the writer slice is verified; COBOL path retired behind the ACL.
      return SliceOutcome(passed=True, blocked_at=None,
                          identity_drift=False, cobol_path_retired=True)
  ```
- [ ] Run `uv run pytest tests/unit/test_phase5_orchestration.py` — expected PASS (4 passed).
- [ ] Commit: `feat(orchestration): phase 5 gated writer-slice pipeline (no identity drift exit)`

---

## Task 14 — Integration: full writer slice on CardDemo CBTRN02C → mvn verify → equivalence

End-to-end against real fixtures. Marked `@pytest.mark.integration`; requires the Build Lab (Maven), a Neo4j fixture graph, and GnuCOBOL golden files. Skips cleanly when those are absent so unit CI stays green.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/seam_writer_cbtrn02c.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/brd_posting_slice.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_phase5_writer_slice_e2e.py`

Steps:
- [ ] Create `tests/fixtures/seam_writer_cbtrn02c.json` (Phase-4-shaped seam evidence; grounded in CBTRN02C 2800-UPDATE-ACCOUNT-REC / 2700-UPDATE-TCATBAL / 2900-WRITE-TRANSACTION-FILE):
  ```json
  {
    "program": "CBTRN02C",
    "reader_only": false,
    "writes": [
      {"resource": "ACCTDAT", "command": "REWRITE", "intent": "write",
       "paragraph": "CBTRN02C.2800-UPDATE-ACCOUNT-REC"},
      {"resource": "TCATBAL", "command": "REWRITE", "intent": "write",
       "paragraph": "CBTRN02C.2700-UPDATE-TCATBAL"},
      {"resource": "TRANSACT", "command": "WRITE", "intent": "write",
       "paragraph": "CBTRN02C.2900-WRITE-TRANSACTION-FILE"}
    ],
    "identity_drift_risk": true,
    "transition_pattern": "extract_product_lines+legacy_mimic",
    "fan_in": 1, "fan_out": 6,
    "score": 0.71
  }
  ```
- [ ] Create `tests/fixtures/brd_posting_slice.json` (focused BRD; required vs accidental behavior):
  ```json
  {
    "sections": [
      {"title": "Posting", "body_markdown": "Post each valid daily transaction.",
       "requirements": [
         {"id": "FR-1", "text": "Add TRAN-AMT to ACCT-CURR-BAL and REWRITE the account."},
         {"id": "FR-2", "text": "Add TRAN-AMT to the matching TCATBAL category balance."},
         {"id": "FR-3", "text": "Reject and log a transaction that exceeds the credit limit."}
       ]}
    ],
    "evidence_map": {
      "FR-1": ["CBTRN02C.2800-UPDATE-ACCOUNT-REC"],
      "FR-2": ["CBTRN02C.2700-UPDATE-TCATBAL"],
      "FR-3": ["CBTRN02C.1500-VALIDATE-TRAN"]
    }
  }
  ```
- [ ] Write failing/skipping test `tests/integration/test_phase5_writer_slice_e2e.py`:
  ```python
  import json
  import os
  import shutil
  from pathlib import Path

  import pytest

  pytestmark = pytest.mark.integration

  FIX = Path(__file__).parents[1] / "fixtures"


  @pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven (Build Lab) not available")
  @pytest.mark.skipif(not os.getenv("RUN_PHASE5_E2E"), reason="set RUN_PHASE5_E2E=1 to run")
  def test_cbtrn02c_writer_slice_compiles_tests_and_matches_golden(tmp_path):
      from cobol_modernizer.codegen.scaffold import scaffold_module
      from cobol_modernizer.codegen.archrules import render_archunit_test
      from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
      from cobol_modernizer.design.judge import judge_design
      from cobol_modernizer.mimic.layout import build_layout
      from cobol_modernizer.mimic.writeback import LegacyMimicWriter

      seam = json.loads((FIX / "seam_writer_cbtrn02c.json").read_text())
      assert seam["reader_only"] is False and seam["identity_drift_risk"] is True

      # 1. Design gate: transaction_processing owns ACCTDAT/TCATBAL/TRANSACT (no leak).
      design = ServiceDesign(
          slice_id="posting-cbtrn02c", deployment="modular_monolith",
          context=BoundedContext.transaction_processing,
          owned_resources=["ACCTDAT", "TCATBAL", "TRANSACT"],
          transition_pattern=seam["transition_pattern"],
          components=["PostingService", "AccountBalanceRepository"],
          evidence_map={"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]})
      rep = judge_design(design, known_refs={"CBTRN02C",
          "CBTRN02C.2800-UPDATE-ACCOUNT-REC"}, external_writers={})
      assert rep.data_ownership_ok and rep.rating == "high"

      # 2. Scaffold + ArchUnit rule.
      root = scaffold_module(tmp_path, module="carddemo-posting",
                             base_package="com.cobolmodernizer.posting")
      arch = render_archunit_test(design, base_package="com.cobolmodernizer.posting")
      (root / "src/test/java/com/cobolmodernizer/posting/ArchitectureTest.java").write_text(arch)
      assert (root / "pom.xml").exists()

      # 3. mvn verify (Build Lab). The scaffold + generated code must pass all gates.
      import subprocess
      proc = subprocess.run(["mvn", "-q", "verify"], cwd=root,
                            capture_output=True, text=True)
      from cobol_modernizer.codegen.quality_gate import parse_mvn_output
      qr = parse_mvn_output(proc.stdout + proc.stderr, exit_code=proc.returncode)
      assert qr.passed, qr.log_excerpt

      # 4. Legacy Mimic round-trip: posted balance survives write-back with no drift.
      layout = build_layout(json.loads((FIX / "account_layout_cvact01y.json").read_text()))
      writer = LegacyMimicWriter(layout)
      from decimal import Decimal
      rec = writer.encode({"ACCT-ID": Decimal("12345678901"),
                           "ACCT-CURR-BAL": Decimal("749.50")})
      assert len(rec) == 300
      assert writer.decode(rec)["ACCT-CURR-BAL"] == Decimal("749.50")
  ```
- [ ] Run `uv run pytest tests/integration/test_phase5_writer_slice_e2e.py` — expected SKIP locally (`mvn`/`RUN_PHASE5_E2E` absent): `1 skipped`. With Build Lab present and `RUN_PHASE5_E2E=1`, expected PASS.
- [ ] Commit: `test(phase5): e2e CBTRN02C writer slice (scaffold->mvn verify->mimic round-trip)`

---

## Acceptance criteria

Mapped 1:1 to the master plan's **Phase 5 Exit criteria** ("a writer slice passes compile + tests + architecture rules + equivalence with no identity drift; old COBOL path retired or fully fronted by an anti-corruption layer") and Phase 5 Deliverables (service design / bounded contexts / ADRs / TDD codegen with ArchUnit/SpotBugs/Error Prone/Checkstyle / repair loop / Legacy Mimic adapter).

1. **Writer slice selected and modeled as a writer.** `seam_writer_cbtrn02c.json` + `context_map.assign_context` place CBTRN02C in `transaction_processing`, `reader_only=false`, `identity_drift_risk=true`, transition pattern `extract_product_lines+legacy_mimic` — the posting/balance-update path, not a reader. (Tasks 2, 14)
2. **Service design with bounded contexts + ADRs, gated on data ownership.** `ServiceDesign` assigns the slice to one of the four CardDemo bounded contexts; the Design gate (`judge_design`) fails ownership leaks and hallucinated evidence; three ADRs (modular monolith, Extract Product Lines, Legacy Mimic) are rendered with embedded lineage. (Tasks 1–4)
3. **Compile + tests pass under TDD.** `generate_slice` enforces tests-first; `parse_mvn_output` confirms `compile_ok` + `tests_ok`; the e2e test asserts `mvn verify` `passed`. (Tasks 10, 11, 14)
4. **Architecture rules pass.** Scaffold wires ArchUnit + SpotBugs(+FindSecBugs) + Error Prone + Checkstyle into `mvn verify`; `render_archunit_test` pins the layered bounded-context rule; `QualityReport` treats any of the six as a hard gate ("compilable is never sufficient"). (Tasks 8, 9, 11)
5. **Repair loop feeds logs back.** `run_repair_loop` feeds the failing gate + build-log excerpt to the `repair` (Opus) agent, applies patches, re-runs the Build Lab, and is bounded by `max_attempts` and the cost kill-switch guard. (Task 12)
6. **Equivalence with no identity drift.** `run_writer_slice` blocks the slice if the Phase 3 Equivalence Lab reports `identity_drift=True` or `matched=False`; the Mimic codecs are Decimal-exact (COMP-3 / S9(n)Vm scale / sign) so balance write-back round-trips with no drift. (Tasks 6, 7, 13)
7. **Legacy Mimic write-back / ACL.** `LegacyMimicWriter` encodes the Java result into the exact `ACCOUNT-RECORD` (RECLN 300) / `TRAN-RECORD` (RECLN 350) fixed-width mainframe format and rejects unknown fields (ACL corruption guard), keeping the un-migrated COBOL estate running. (Tasks 5–7)
8. **Old COBOL path retired or fronted by ACL.** `SliceOutcome.cobol_path_retired` is `True` only on a clean equivalence pass (no drift, golden-master matched); otherwise the COBOL path stays live behind the Legacy Mimic ACL. (Task 13)
9. **Non-negotiables honored throughout.** Neo4j read-only via MCP tools (codegen/repair use only `get_source_slice`/`get_entity`); every artifact carries an `evidence_map` and is groundedness-gated; seam writer/identity-drift classification comes from Cypher (no LLM in scoring); `resolve_model` tiers design=Opus / codegen=Sonnet / repair=Opus; the cost policy caps + kill-switches the loop; harness keeps `tools=[]`, `setting_sources=[]`, `json_schema`. (Tasks 10, 12, 13 + foundation imports)

All Phase 5 modules live under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/{design,codegen,mimic,orchestration}` and conform verbatim to the foundation contract (package `cobol_modernizer`, `schemaVersion=2`, Postgres tables, `cost/tiering.py`, `cost/policy.py`, read-only MCP surface, evidence_map + groundedness gate, COBOL graceful degradation).
