# Phase 2 — Thin Vertical Slice (CardDemo Account-View) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Prove the *entire* modernization pipeline on ONE low-fan-in, read-only CardDemo program — `COACTVWC` (Account View) — all the way to a **dark-launched Spring Boot read-path service** whose output **diff-matches the COBOL** within tolerance. This is the v1 product acceptance test: seam-ranking surfaces account-view as the safe first slice → a focused (slice-scoped) BRD → a story cluster → a generated Spring Boot service (read path via an **anti-corruption adapter** over the Phase 0 captured VSAM data, with a CDC/replica seam left as the production path) → CI/observability → **dark launch with output diffing**, with a **human approval at every gate** and **cost under cap**.

**Architecture:** Reuses, end-to-end, the deterministic core already locked by Phases 0/1: Neo4j v2 code graph (source of truth) + Postgres run/audit/RBAC + MinIO object store + bounded agents reading only via read-only Cypher MCP tools + the `schemaVersion:2` JSON contract. Phase 2 adds NOTHING to the scoring path (seam ranking is the Phase-1 Cypher `seam_candidates` query; the LLM only writes *rationale* and the slice BRD/story over precomputed evidence). The generated artifact is a Spring Boot 3.3 / Java 25 service that reads account-view data through an **anti-corruption layer (ACL)** translating COBOL record layouts (`ACCOUNT-RECORD` RECLN 300, `CARD-XREF-RECORD` RECLN 50, `CUSTOMER-RECORD` RECLN 500) into a clean `AccountView` DTO. A **dark-launch harness** replays Phase-0-captured COACTVWC inputs (account ids) against both the COBOL golden outputs and the Spring Boot service, and a **diff engine with explicit COMP-3 / numeric-scale / date / EBCDIC tolerance rules** asserts outcome parity. Every artifact (slice BRD, story DAG, design, generated project, dark-launch report) is versioned in Postgres `artifact` with an `evidence_map`, gated by attributed RBAC approvals in `approval`, and budgeted by `CostPolicy`.

**Tech Stack (pinned, per foundation doc):** Python 3.12 + uv; Java 25 + Maven 3.9 + Spring Boot 3.3; Neo4j 5.24-enterprise + GDS 2.x; Postgres 16; MinIO; `claude-agent-sdk==0.2.87`; pytest + pytest-asyncio (`asyncio_mode=auto`); JUnit 5; conventional commits.

**Slice target (binding):** program `COACTVWC` (`app/cbl/COACTVWC.cbl`, 941 lines). It is **read-only** — three CICS `READ` operations and zero writes:
1. `EXEC CICS READ DATASET(CXACAIX/CardXref-Acct-Path) RIDFLD(acct-id) INTO(CARD-XREF-RECORD)` → `XREF-CARD-NUM`, `XREF-CUST-ID`, `XREF-ACCT-ID`.
2. `EXEC CICS READ DATASET(ACCTDAT) RIDFLD(acct-id) INTO(ACCOUNT-RECORD)` → balance, credit limit, status, dates.
3. `EXEC CICS READ DATASET(CUSTDAT) RIDFLD(cust-id) INTO(CUSTOMER-RECORD)` → name, address, FICO.
In the Phase-1 v2 graph these surface as three `EXECUTES_CICS` edges with `intent:"read"` and zero `intent:"write"` edges — i.e. `seam_candidates` ranks COACTVWC as `reader_only:true`, the safest possible first slice.

---

## File Structure

Everything below is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── src/cobol_modernizer/
│   ├── slice/                                   # NEW — Phase 2 thin-slice orchestration (Python)
│   │   ├── __init__.py
│   │   ├── selection.py                         # pick_slice(): rank via Phase-1 seam_candidates, choose reader_only top
│   │   ├── slice_brd.py                         # focused, slice-scoped BRD agent (reuses brd harness + groundedness gate)
│   │   ├── stories.py                           # story-cluster agent (INVEST) over the slice BRD; acyclic DAG check
│   │   ├── design.py                            # service design doc (ACL/CDC decision) over Cypher evidence
│   │   └── gates.py                             # Postgres gate+approval helpers for the slice journey
│   ├── darklaunch/                              # NEW — dual-run + diff engine (Python)
│   │   ├── __init__.py
│   │   ├── fixtures.py                          # load Phase-0 captured COACTVWC inputs/golden outputs from MinIO
│   │   ├── tolerance.py                         # ToleranceRule: COMP-3, scale, date, EBCDIC, trailing-space rules
│   │   ├── diff.py                              # diff_outputs(): field-level compare with tolerance → DiffReport
│   │   └── runner.py                            # replay inputs to Spring Boot HTTP + compare to golden → report artifact
│   └── api.py                                   # MODIFY — add /slice + /darklaunch SSE/REST endpoints
├── generated/account-view-service/              # NEW — generated Spring Boot read-path service (Java 25)
│   ├── pom.xml                                  # Spring Boot 3.3, Java 25, JUnit 5
│   └── src/
│       ├── main/java/com/cobolmodernizer/accountview/
│       │   ├── AccountViewApplication.java      # Spring Boot entry
│       │   ├── api/AccountViewController.java    # GET /api/accounts/{acctId}/view
│       │   ├── api/AccountView.java              # clean DTO (the bounded-context model)
│       │   ├── acl/CobolRecordCodec.java         # ANTI-CORRUPTION LAYER: fixed-width COBOL record -> domain
│       │   ├── acl/PackedDecimal.java            # COMP-3 packed-decimal decode (S9(10)V99 etc.)
│       │   ├── domain/AccountViewService.java    # read path: xref -> acct -> cust assembly
│       │   └── repo/CapturedVsamRepository.java  # reads Phase-0 captured VSAM slices (ACL data source)
│       └── test/java/com/cobolmodernizer/accountview/
│           ├── acl/PackedDecimalTest.java
│           ├── acl/CobolRecordCodecTest.java
│           └── api/AccountViewControllerTest.java
├── .github/workflows/account-view-ci.yml        # NEW — CI: maven build+test+jacoco for the generated service
└── tests/
    ├── unit/
    │   ├── test_slice_selection.py              # reader_only top-ranked seam chosen
    │   ├── test_slice_brd_scope.py              # slice BRD prompt is scoped to one program's evidence
    │   ├── test_slice_stories_dag.py            # story DAG acyclic gate
    │   ├── test_tolerance_rules.py              # COMP-3/scale/date/EBCDIC tolerance
    │   ├── test_darklaunch_diff.py              # diff engine match + mismatch
    │   └── test_slice_gates.py                  # gate+approval round-trip with RBAC identity + cost cap
    ├── integration/
    │   └── test_darklaunch_runner.py            # end-to-end dual-run against a fake Spring Boot endpoint
    └── fixtures/
        ├── seam_candidates_sample.json          # Phase-1 seam query output (COACTVWC reader_only top)
        ├── coactvwc_inputs.json                 # captured account-ids (dark-launch inputs)
        ├── coactvwc_golden.json                 # captured COBOL golden outputs (AccountView shape)
        └── account_record_fixed.bin.hex         # raw fixed-width ACCOUNT-RECORD bytes (COMP-3 fields) hex
```

**Single responsibilities:**
- `slice/selection.py` — turn the deterministic Phase-1 `seam_candidates` Cypher result into the chosen slice; **no LLM, no scoring re-implementation**.
- `slice/slice_brd.py`, `stories.py`, `design.py` — reuse the working BRD harness/judge/groundedness gate, but **scope evidence to the one program's subgraph** so the BRD is "focused" (slice BRD), not estate-wide.
- `darklaunch/tolerance.py` + `diff.py` — the explicit tolerance rules + field-level diff that make *outcome parity* (not feature parity) checkable; the linchpin of the exit criteria.
- `generated/account-view-service/**` — the dark-launched Spring Boot read service with an ACL over captured VSAM; **reader path only**, no write-back (writers are Phase 5).
- `slice/gates.py` — persists each gate's pass/fail + the attributed RBAC approval and checks `CostPolicy` before advancing.

---

## Preconditions (assert before starting)

- [ ] Phase 0 complete: Postgres `workspace/journey_stage/agent_run/artifact/gate/approval/budget` tables exist; `CostPolicy` + `resolve_model` exist; CardDemo ingested; **Phase-0 capture harness has stored COACTVWC golden inputs/outputs in MinIO** (this plan loads them; if absent, Task 2.6 documents the minimal capture stub).
- [ ] Phase 1 complete: v2 graph carries `EXECUTES_CICS` edges with `intent`; the read-only MCP tools `data_accesses`, `reader_writer_classification`, `seam_candidates` exist and run in Cypher with **zero LLM in the scoring path**.
- [ ] Branch first if on the default branch: `git checkout -b phase-2-thin-slice`.

---

## Task 2.1 — Deterministic slice selection from Phase-1 seam ranking

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/selection.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/seam_candidates_sample.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_selection.py`

Steps:
- [ ] Create fixture `tests/fixtures/seam_candidates_sample.json` (the shape Phase-1 `seam_candidates` Cypher returns — COACTVWC is `reader_only:true`, lowest fan-out):
  ```json
  [
    {"program": "COACTVWC", "fan_in": 1, "fan_out": 0, "reader_only": true,  "writes": 0, "reads": 3, "score": 0.91},
    {"program": "COCRDSLC", "fan_in": 2, "fan_out": 1, "reader_only": true,  "writes": 0, "reads": 2, "score": 0.78},
    {"program": "COACTUPC", "fan_in": 3, "fan_out": 2, "reader_only": false, "writes": 2, "reads": 4, "score": 0.31}
  ]
  ```
- [ ] Write failing test `tests/unit/test_slice_selection.py`:
  ```python
  import json
  from pathlib import Path

  from cobol_modernizer.slice.selection import pick_slice, SliceChoice

  FIX = Path(__file__).parents[1] / "fixtures" / "seam_candidates_sample.json"

  def test_picks_reader_only_top_ranked():
      candidates = json.loads(FIX.read_text())
      choice = pick_slice(candidates)
      assert isinstance(choice, SliceChoice)
      assert choice.program == "COACTVWC"
      assert choice.reader_only is True
      assert choice.score == 0.91
      # evidence carries the deterministic signals — NO LLM re-scoring
      assert choice.evidence["writes"] == 0
      assert choice.evidence["reads"] == 3

  def test_rejects_when_no_reader_only_candidate():
      writers_only = [{"program": "X", "fan_in": 1, "fan_out": 1,
                       "reader_only": False, "writes": 1, "reads": 0, "score": 0.5}]
      import pytest
      with pytest.raises(ValueError, match="no reader-only seam"):
          pick_slice(writers_only)

  def test_ties_break_by_lower_fan_out_then_name():
      cands = [
          {"program": "BBB", "fan_in": 1, "fan_out": 2, "reader_only": True,
           "writes": 0, "reads": 1, "score": 0.5},
          {"program": "AAA", "fan_in": 1, "fan_out": 1, "reader_only": True,
           "writes": 0, "reads": 1, "score": 0.5},
      ]
      assert pick_slice(cands).program == "AAA"  # lower fan_out wins the tie
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_selection.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.slice'`.
- [ ] Create `src/cobol_modernizer/slice/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/slice/selection.py`:
  ```python
  """Pick the thin-slice program from the Phase-1 seam ranking.

  CRITICAL (master plan §1.4, §4.2): seam scoring is computed in Cypher/GDS
  (Phase 1 `seam_candidates`). This module does NOT re-score and does NOT call an
  LLM — it only applies the deterministic strangler-fig policy 'macro before micro,
  one verified seam before broadening': choose the safest reader-only seam first.
  """
  from __future__ import annotations

  from dataclasses import dataclass


  @dataclass(frozen=True)
  class SliceChoice:
      program: str
      reader_only: bool
      score: float
      evidence: dict  # the deterministic Cypher signals (fan_in/fan_out/reads/writes)


  def pick_slice(candidates: list[dict]) -> SliceChoice:
      """Choose the first verified seam: the highest-scoring reader-only program.

      Tie-break: higher score, then lower fan_out (less blast radius), then name.
      Raises ValueError if no reader-only candidate exists (a writer-first slice
      violates the Phase-2 'low-fan-in read-only' precondition; writers are Phase 5).
      """
      readers = [c for c in candidates if c.get("reader_only") is True]
      if not readers:
          raise ValueError("no reader-only seam in candidates; cannot start a "
                           "read-only thin slice (writer slices are Phase 5)")
      readers.sort(key=lambda c: (-float(c["score"]), int(c["fan_out"]), c["program"]))
      top = readers[0]
      return SliceChoice(
          program=top["program"],
          reader_only=True,
          score=float(top["score"]),
          evidence={"fan_in": int(top["fan_in"]), "fan_out": int(top["fan_out"]),
                    "reads": int(top["reads"]), "writes": int(top["writes"])},
      )
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_selection.py` — expected PASS (3 passed).
- [ ] Commit: `feat(slice): deterministic reader-only seam selection from Phase-1 ranking`

---

## Task 2.2 — Slice-scoped (focused) BRD over the single-program subgraph

The Phase-0 BRD is estate-wide. The Phase-2 deliverable is a *focused* BRD for the one slice. Reuse the working BRD harness, judge, and groundedness gate verbatim; the only change is **scoping the evidence to the chosen program's subgraph** (its `EXECUTES_CICS`/`READS` edges + imported copybooks) so the agent reads only the slice via the read-only MCP tools.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/slice_brd.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_brd_scope.py`

Steps:
- [ ] Write failing test `tests/unit/test_slice_brd_scope.py` (uses a fake runner — no network, no LLM; asserts the prompt is scoped and the groundedness gate is wired):
  ```python
  import asyncio

  from cobol_modernizer.slice.slice_brd import build_slice_brd_prompt, SliceBrdInput

  def test_prompt_is_scoped_to_one_program_and_its_io():
      inp = SliceBrdInput(
          program="COACTVWC",
          read_resources=[
              {"resource": "CXACAIX", "command": "READ", "intent": "read"},
              {"resource": "ACCTDAT", "command": "READ", "intent": "read"},
              {"resource": "CUSTDAT", "command": "READ", "intent": "read"},
          ],
          copybooks=["CVACT01Y", "CVACT03Y", "CVCUS01Y"],
      )
      prompt = build_slice_brd_prompt(inp)
      # scoped to ONE program
      assert "COACTVWC" in prompt
      assert "single program" in prompt.lower()
      # the slice's read resources are named so the agent reads only their slices
      assert "ACCTDAT" in prompt and "CXACAIX" in prompt and "CUSTDAT" in prompt
      # explicit instruction to use read-only graph tools, not whole files
      assert "get_source_slice" in prompt
      # required-vs-accidental behavior separation (outcome parity, not feature parity)
      assert "required" in prompt.lower() and "accidental" in prompt.lower()

  def test_uses_brd_role_model(monkeypatch):
      monkeypatch.delenv("BRD_AGENT_MODEL", raising=False)
      from cobol_modernizer.slice.slice_brd import slice_brd_model
      assert slice_brd_model() == "claude-sonnet-4-6"  # 'brd' role tier
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_brd_scope.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/slice/slice_brd.py`:
  ```python
  """Focused, slice-scoped BRD: reuse the working BRD harness + judge + groundedness
  gate, but scope the agent's evidence to ONE program's subgraph so the BRD is about
  the thin slice, not the whole estate. Seam math is NOT here (it is Phase-1 Cypher);
  this only reverse-engineers required behavior for the chosen reader-only program.
  """
  from __future__ import annotations

  from dataclasses import dataclass, field

  from cobol_modernizer.cost.tiering import resolve_model


  @dataclass
  class SliceBrdInput:
      program: str
      read_resources: list[dict]            # [{resource, command, intent}]  (intent=='read')
      copybooks: list[str] = field(default_factory=list)


  def slice_brd_model() -> str:
      """The slice BRD is synthesis work -> 'brd' role -> Sonnet tier."""
      return resolve_model("brd")


  def build_slice_brd_prompt(inp: SliceBrdInput) -> str:
      resources = ", ".join(r["resource"] for r in inp.read_resources)
      copybooks = ", ".join(inp.copybooks) or "(none)"
      return (
          f"Produce a FOCUSED Business Requirements Document for the single program "
          f"{inp.program}. This is one thin vertical slice of a COBOL modernization; "
          f"scope strictly to this program.\n\n"
          f"This program is READ-ONLY. Its data accesses (all intent=read) are: "
          f"{resources}. Its record layouts come from copybooks: {copybooks}.\n\n"
          f"Use ONLY the read-only graph tools to gather evidence: call get_entity on "
          f"{inp.program}, data_accesses to enumerate its reads, neighbors with "
          f"edge=IMPORTS for copybooks, and get_source_slice to read code lines — never "
          f"request whole files.\n\n"
          f"Separate REQUIRED behavior (the account-view query the business depends on) "
          f"from ACCIDENTAL legacy behavior (screen/BMS formatting, CICS plumbing, "
          f"error-message construction). The migration target reproduces required "
          f"behavior only; we verify OUTCOME parity, not feature parity.\n\n"
          f"Every requirement MUST carry an evidence_map entry referencing the graph "
          f"entity ids / source refs it is grounded in."
      )


  async def agenerate_slice_brd(deps, *, runner, model: str, inp: SliceBrdInput,
                                max_retries: int = 1, max_turns: int = 15,
                                advisor=None, advisor_max_uses: int = 3):
      """Run the slice BRD through the SAME groundedness-gated loop as the estate BRD,
      but with a single-program prompt. Returns the GraphBRDResult (brd, report,
      rating, weighted_score). Imported lazily so unit tests need no SDK."""
      from cobol_modernizer.agent.brd_judge import ajudge
      from cobol_modernizer.agent.brd_orchestrator import agenerate_brd_draft
      from cobol_modernizer.brd.pipeline import GraphBRDResult, _draft_to_brd
      from cobol_modernizer.brd.schema import AttemptRecord, JudgeReport, Rating, Strategy

      attempts: list[AttemptRecord] = []
      best: tuple = None
      prompt = build_slice_brd_prompt(inp)
      for attempt_no in range(1, max_retries + 2):
          draft, strategy = await agenerate_brd_draft(
              deps, runner=runner, model=model, max_turns=max_turns,
              max_subsystems=1, advisor=advisor, advisor_max_uses=advisor_max_uses,
              prompt_override=prompt)
          brd = _draft_to_brd(draft, deps.repo_id, model, strategy)
          report = await ajudge(brd, deps, runner=runner, model=model)
          attempts.append(AttemptRecord(attempt=attempt_no, rating=report.rating,
                                        weighted_score=report.weighted_score,
                                        feedback=report.feedback))
          if best is None or report.weighted_score > best[1].weighted_score:
              best = (brd, report)
          if report.rating == Rating.high:
              break
      final_brd, final_report = best
      return GraphBRDResult(brd=final_brd, report=final_report,
                            rating=final_report.rating,
                            weighted_score=final_report.weighted_score,
                            attempts=len(attempts), attempt_history=attempts,
                            strategy=final_brd.strategy)
  ```
  > NOTE for the implementer: `agenerate_brd_draft` is ported in the Phase-0/agent plan; add a `prompt_override` kwarg there during this task (default `None` → existing estate prompt). That keeps the working core intact while letting the slice supply a focused prompt.
- [ ] Run `uv run pytest tests/unit/test_slice_brd_scope.py` — expected PASS (2 passed).
- [ ] Commit: `feat(slice): focused single-program BRD prompt reusing groundedness-gated harness`

---

## Task 2.3 — Story cluster (INVEST) with acyclic-DAG gate

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/stories.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_stories_dag.py`

Steps:
- [ ] Write failing test `tests/unit/test_slice_stories_dag.py`:
  ```python
  import pytest

  from cobol_modernizer.slice.stories import (
      Story, StoryCluster, assert_acyclic, story_model,
  )

  def _cluster(deps):
      return StoryCluster(
          program="COACTVWC",
          stories=[
              Story(id="S1", title="Decode COBOL account/customer/xref records (ACL)",
                    depends_on=[], evidence_map={"S1": ["CVACT01Y", "CVACT03Y"]}),
              Story(id="S2", title="Assemble AccountView from xref->acct->cust reads",
                    depends_on=["S1"], evidence_map={"S2": ["COACTVWC.9000-READ-ACCT"]}),
              Story(id="S3", title="Expose GET /api/accounts/{id}/view",
                    depends_on=["S2"], evidence_map={"S3": ["COACTVWC"]}),
          ],
      )

  def test_story_cluster_is_acyclic():
      c = _cluster(None)
      assert_acyclic(c)  # no raise
      order = c.topological_order()
      assert order.index("S1") < order.index("S2") < order.index("S3")

  def test_cycle_is_rejected():
      c = StoryCluster(program="X", stories=[
          Story(id="A", title="a", depends_on=["B"], evidence_map={}),
          Story(id="B", title="b", depends_on=["A"], evidence_map={}),
      ])
      with pytest.raises(ValueError, match="cycle"):
          assert_acyclic(c)

  def test_every_story_carries_evidence():
      c = StoryCluster(program="X", stories=[
          Story(id="A", title="a", depends_on=[], evidence_map={}),
      ])
      with pytest.raises(ValueError, match="evidence"):
          assert_acyclic(c)

  def test_story_role_model():
      assert story_model() == "claude-sonnet-4-6"  # 'story' role tier
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_stories_dag.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/slice/stories.py`:
  ```python
  """Story cluster for the thin slice: INVEST-style stories with an explicit
  acyclic dependency DAG and per-story evidence_map (lineage non-negotiable).
  The DAG gate is deterministic (Kahn's algorithm); the LLM only proposes stories.
  """
  from __future__ import annotations

  from dataclasses import dataclass, field

  from cobol_modernizer.cost.tiering import resolve_model


  @dataclass
  class Story:
      id: str
      title: str
      depends_on: list[str] = field(default_factory=list)
      evidence_map: dict[str, list[str]] = field(default_factory=dict)


  @dataclass
  class StoryCluster:
      program: str
      stories: list[Story]

      def topological_order(self) -> list[str]:
          indeg = {s.id: 0 for s in self.stories}
          adj: dict[str, list[str]] = {s.id: [] for s in self.stories}
          for s in self.stories:
              for dep in s.depends_on:
                  adj[dep].append(s.id)
                  indeg[s.id] += 1
          queue = sorted([sid for sid, d in indeg.items() if d == 0])
          order: list[str] = []
          while queue:
              n = queue.pop(0)
              order.append(n)
              for m in adj[n]:
                  indeg[m] -= 1
                  if indeg[m] == 0:
                      queue.append(m)
              queue.sort()
          if len(order) != len(self.stories):
              raise ValueError("story dependency graph has a cycle")
          return order


  def story_model() -> str:
      return resolve_model("story")


  def assert_acyclic(cluster: StoryCluster) -> None:
      """Hard gate: the story DAG must be acyclic AND every story must carry evidence
      (lineage). Raises ValueError on a cycle or a story with an empty evidence_map."""
      for s in cluster.stories:
          if not s.evidence_map:
              raise ValueError(f"story {s.id} has no evidence (lineage required)")
      cluster.topological_order()  # raises on cycle
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_stories_dag.py` — expected PASS (4 passed).
- [ ] Commit: `feat(slice): INVEST story cluster with acyclic-DAG + evidence gate`

---

## Task 2.4 — COMP-3 packed-decimal decoder (ACL foundation, Java)

The generated service's anti-corruption layer must read the COBOL fixed-width records byte-for-byte. The hard part is COMP-3 (packed decimal): `ACCT-CURR-BAL PIC S9(10)V99` is 12 digits → 6 bytes, last nibble is the sign. Build this first, TDD, in the generated Java project.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/src/main/java/com/cobolmodernizer/accountview/acl/PackedDecimal.java`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/src/test/java/com/cobolmodernizer/accountview/acl/PackedDecimalTest.java`

Steps:
- [ ] Create `pom.xml`:
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <project xmlns="http://maven.apache.org/POM/4.0.0"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-parent</artifactId>
      <version>3.3.4</version>
      <relativePath/>
    </parent>
    <groupId>com.cobolmodernizer</groupId>
    <artifactId>account-view-service</artifactId>
    <version>0.1.0</version>
    <properties>
      <java.version>25</java.version>
      <maven.compiler.release>25</maven.compiler.release>
    </properties>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
      </dependency>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId>
        <scope>test</scope>
      </dependency>
    </dependencies>
    <build>
      <plugins>
        <plugin>
          <groupId>org.springframework.boot</groupId>
          <artifactId>spring-boot-maven-plugin</artifactId>
        </plugin>
        <plugin>
          <groupId>org.jacoco</groupId>
          <artifactId>jacoco-maven-plugin</artifactId>
          <version>0.8.12</version>
          <executions>
            <execution><goals><goal>prepare-agent</goal></goals></execution>
            <execution><id>report</id><phase>test</phase><goals><goal>report</goal></goals></execution>
          </executions>
        </plugin>
      </plugins>
    </build>
  </project>
  ```
- [ ] Write failing test `src/test/java/com/cobolmodernizer/accountview/acl/PackedDecimalTest.java`:
  ```java
  package com.cobolmodernizer.accountview.acl;

  import static org.junit.jupiter.api.Assertions.assertEquals;

  import java.math.BigDecimal;
  import org.junit.jupiter.api.Test;

  class PackedDecimalTest {

      // PIC S9(10)V99 COMP-3 -> 12 digits -> 6 bytes; value 1234.56, positive.
      // Digits: 0 0 0 0 0 0 1 2 3 4 5 6, sign nibble 0x0C (positive).
      @Test
      void decodesPositivePackedDecimalWithTwoImpliedDecimals() {
          byte[] packed = {0x00, 0x00, 0x00, 0x01, 0x23, 0x4C};
          // 8 digits packed here (0000 0001 234 + C). scale=2.
          BigDecimal v = PackedDecimal.decode(packed, 2);
          assertEquals(new BigDecimal("123.4").movePointLeft(0), v.setScale(1));
      }

      @Test
      void decodesNegativeSignNibbleD() {
          // value -7.65 : digits 7 6 5, sign 0xD (negative). packed: 0x07,0x65,0xD? -> {0x07,0x65} + sign
          byte[] packed = {0x07, 0x6D}; // digits 0,7,6 sign D -> 076 negative, scale 2 -> -0.76
          BigDecimal v = PackedDecimal.decode(packed, 2);
          assertEquals(new BigDecimal("-0.76"), v);
      }

      @Test
      void positiveSignNibbleFIsAlsoPositive() {
          byte[] packed = {0x12, 0x3F}; // 0x0F unsigned-positive -> 123, scale 0 -> 123
          assertEquals(new BigDecimal("123"), PackedDecimal.decode(packed, 0));
      }
  }
  ```
- [ ] Run from the project dir: `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=PackedDecimalTest test` — expected FAIL: compilation error (no `PackedDecimal` class).
- [ ] Create `src/main/java/com/cobolmodernizer/accountview/acl/PackedDecimal.java`:
  ```java
  package com.cobolmodernizer.accountview.acl;

  import java.math.BigDecimal;
  import java.math.BigInteger;

  /**
   * Anti-corruption layer primitive: decode IBM COBOL COMP-3 (packed decimal).
   * Each byte holds two 4-bit digits; the final low nibble is the sign
   * (0xC/0xF/0xA/0xE = positive, 0xD/0xB = negative). The COBOL V (implied
   * decimal point) is supplied as {@code scale}. No EBCDIC involved — COMP-3 is
   * numeric nibbles, not characters.
   */
  public final class PackedDecimal {
      private PackedDecimal() {}

      public static BigDecimal decode(byte[] bytes, int scale) {
          StringBuilder digits = new StringBuilder();
          int signNibble = bytes[bytes.length - 1] & 0x0F;
          for (int i = 0; i < bytes.length; i++) {
              int b = bytes[i] & 0xFF;
              int hi = (b >> 4) & 0x0F;
              digits.append(hi);
              if (i < bytes.length - 1) {
                  int lo = b & 0x0F;
                  digits.append(lo);
              }
          }
          BigInteger unscaled = new BigInteger(digits.toString());
          if (signNibble == 0x0D || signNibble == 0x0B) {
              unscaled = unscaled.negate();
          }
          return new BigDecimal(unscaled, scale);
      }
  }
  ```
- [ ] Run `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=PackedDecimalTest test` — expected PASS (Tests run: 3, Failures: 0).
- [ ] Commit: `feat(account-view): COMP-3 packed-decimal decoder (ACL primitive)`

---

## Task 2.5 — ACL record codec + AccountView assembly (Java)

Translate the three fixed-width COBOL records into a clean `AccountView` DTO. This is the anti-corruption layer that decouples the new service from the COBOL layout (Fowler: copybook → canonical DTO + ACL).

**Files:**
- Create: `.../accountview/api/AccountView.java`
- Create: `.../accountview/acl/CobolRecordCodec.java`
- Test: `.../accountview/acl/CobolRecordCodecTest.java`

(all under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/src/...`)

Steps:
- [ ] Write failing test `src/test/java/com/cobolmodernizer/accountview/acl/CobolRecordCodecTest.java`:
  ```java
  package com.cobolmodernizer.accountview.acl;

  import static org.junit.jupiter.api.Assertions.assertEquals;

  import com.cobolmodernizer.accountview.api.AccountView;
  import java.nio.charset.StandardCharsets;
  import org.junit.jupiter.api.Test;

  class CobolRecordCodecTest {

      // ACCOUNT-RECORD CVACT01Y: ACCT-ID 9(11), ACCT-ACTIVE-STATUS X(1),
      // ACCT-CURR-BAL S9(10)V99 (DISPLAY here for test simplicity).
      // We test the DISPLAY (zoned) numeric + text decode path used for ids/status.
      @Test
      void decodesAccountIdAndStatusFromDisplayFields() {
          // 11-digit acct id "00000000123", status "Y"
          byte[] rec = ("00000000123" + "Y").getBytes(StandardCharsets.US_ASCII);
          String acctId = CobolRecordCodec.text(rec, 0, 11).strip();
          String status = CobolRecordCodec.text(rec, 11, 1);
          assertEquals("00000000123", acctId);
          assertEquals("Y", status);
      }

      @Test
      void assemblesAccountViewFromThreeRecords() {
          AccountView v = CobolRecordCodec.assemble(
              /*acctId*/ "00000000123",
              /*status*/ "Y",
              /*balance*/ new java.math.BigDecimal("1234.56"),
              /*creditLimit*/ new java.math.BigDecimal("5000.00"),
              /*custId*/ "000000042",
              /*firstName*/ "JANE ",
              /*lastName*/ "DOE  ",
              /*fico*/ 720);
          assertEquals("00000000123", v.accountId());
          assertEquals("Y", v.activeStatus());
          assertEquals(new java.math.BigDecimal("1234.56"), v.currentBalance());
          assertEquals("JANE", v.customerFirstName());   // trailing COBOL spaces trimmed
          assertEquals("DOE", v.customerLastName());
          assertEquals(720, v.ficoScore());
      }
  }
  ```
- [ ] Run `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=CobolRecordCodecTest test` — expected FAIL: compilation error.
- [ ] Create `src/main/java/com/cobolmodernizer/accountview/api/AccountView.java`:
  ```java
  package com.cobolmodernizer.accountview.api;

  import java.math.BigDecimal;

  /** Clean bounded-context DTO — the modernized account-view model, decoupled
   *  from any COBOL copybook layout by the anti-corruption layer. */
  public record AccountView(
      String accountId,
      String activeStatus,
      BigDecimal currentBalance,
      BigDecimal creditLimit,
      String customerId,
      String customerFirstName,
      String customerLastName,
      int ficoScore) {}
  ```
- [ ] Create `src/main/java/com/cobolmodernizer/accountview/acl/CobolRecordCodec.java`:
  ```java
  package com.cobolmodernizer.accountview.acl;

  import com.cobolmodernizer.accountview.api.AccountView;
  import java.math.BigDecimal;
  import java.nio.charset.StandardCharsets;

  /** Anti-corruption layer: decode fixed-width COBOL records (CVACT01Y account,
   *  CVACT03Y card-xref, CVCUS01Y customer) into the clean AccountView DTO.
   *  COBOL fixed-width text fields are space-padded; numeric COMP-3 fields go
   *  through {@link PackedDecimal}. */
  public final class CobolRecordCodec {
      private CobolRecordCodec() {}

      public static String text(byte[] rec, int offset, int len) {
          return new String(rec, offset, len, StandardCharsets.US_ASCII);
      }

      public static AccountView assemble(
              String acctId, String status, BigDecimal balance, BigDecimal creditLimit,
              String custId, String firstName, String lastName, int fico) {
          return new AccountView(
              acctId.strip(), status,
              balance, creditLimit,
              custId.strip(),
              firstName.strip(), lastName.strip(),
              fico);
      }
  }
  ```
- [ ] Run `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=CobolRecordCodecTest test` — expected PASS (Tests run: 2, Failures: 0).
- [ ] Commit: `feat(account-view): ACL record codec + AccountView DTO`

---

## Task 2.6 — Read-path service + REST controller (Java)

The read path: given an account id, read xref → account → customer (mirroring COACTVWC's `9000-READ-ACCT`) and return `AccountView`. The data source is the **Phase-0 captured VSAM slices** (an ACL repository), so the dark-launch reads exactly what COBOL read. Production swaps this repo for a CDC/replica without touching the domain.

**Files:**
- Create: `.../accountview/repo/CapturedVsamRepository.java`
- Create: `.../accountview/domain/AccountViewService.java`
- Create: `.../accountview/api/AccountViewController.java`
- Create: `.../accountview/AccountViewApplication.java`
- Test: `.../accountview/api/AccountViewControllerTest.java`

Steps:
- [ ] Write failing test `src/test/java/com/cobolmodernizer/accountview/api/AccountViewControllerTest.java`:
  ```java
  package com.cobolmodernizer.accountview.api;

  import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
  import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
  import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

  import com.cobolmodernizer.accountview.domain.AccountViewService;
  import java.math.BigDecimal;
  import org.junit.jupiter.api.Test;
  import org.springframework.beans.factory.annotation.Autowired;
  import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
  import org.springframework.boot.test.mock.mockito.MockBean;
  import org.springframework.test.web.servlet.MockMvc;

  @WebMvcTest(AccountViewController.class)
  class AccountViewControllerTest {

      @Autowired MockMvc mvc;
      @MockBean AccountViewService service;

      @Test
      void returnsAccountViewJson() throws Exception {
          org.mockito.Mockito.when(service.view("00000000123")).thenReturn(
              new AccountView("00000000123", "Y", new BigDecimal("1234.56"),
                  new BigDecimal("5000.00"), "000000042", "JANE", "DOE", 720));
          mvc.perform(get("/api/accounts/00000000123/view"))
             .andExpect(status().isOk())
             .andExpect(jsonPath("$.accountId").value("00000000123"))
             .andExpect(jsonPath("$.currentBalance").value(1234.56))
             .andExpect(jsonPath("$.customerLastName").value("DOE"));
      }

      @Test
      void returns404WhenNotFound() throws Exception {
          org.mockito.Mockito.when(service.view("99999999999")).thenReturn(null);
          mvc.perform(get("/api/accounts/99999999999/view"))
             .andExpect(status().isNotFound());
      }
  }
  ```
- [ ] Run `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=AccountViewControllerTest test` — expected FAIL: compilation error.
- [ ] Create `AccountViewApplication.java`:
  ```java
  package com.cobolmodernizer.accountview;

  import org.springframework.boot.SpringApplication;
  import org.springframework.boot.autoconfigure.SpringBootApplication;

  @SpringBootApplication
  public class AccountViewApplication {
      public static void main(String[] args) {
          SpringApplication.run(AccountViewApplication.class, args);
      }
  }
  ```
- [ ] Create `repo/CapturedVsamRepository.java`:
  ```java
  package com.cobolmodernizer.accountview.repo;

  import java.util.Optional;
  import org.springframework.stereotype.Repository;

  /** ACL data source. In dark-launch it reads the Phase-0 captured VSAM slices
   *  (ACCTDAT/CXACAIX/CUSTDAT) so the new service sees exactly the bytes COBOL saw.
   *  Production replaces this with a CDC/replica reader — domain code is unchanged. */
  @Repository
  public class CapturedVsamRepository {
      public Optional<byte[]> readXref(String acctId)    { return Optional.empty(); }
      public Optional<byte[]> readAccount(String acctId) { return Optional.empty(); }
      public Optional<byte[]> readCustomer(String custId){ return Optional.empty(); }
  }
  ```
- [ ] Create `domain/AccountViewService.java`:
  ```java
  package com.cobolmodernizer.accountview.domain;

  import com.cobolmodernizer.accountview.acl.CobolRecordCodec;
  import com.cobolmodernizer.accountview.acl.PackedDecimal;
  import com.cobolmodernizer.accountview.api.AccountView;
  import com.cobolmodernizer.accountview.repo.CapturedVsamRepository;
  import java.math.BigDecimal;
  import java.util.Optional;
  import org.springframework.stereotype.Service;

  /** Read path mirroring COACTVWC 9000-READ-ACCT: xref -> account -> customer.
   *  Required behavior only; no BMS/screen plumbing (accidental legacy behavior). */
  @Service
  public class AccountViewService {
      private final CapturedVsamRepository repo;

      public AccountViewService(CapturedVsamRepository repo) { this.repo = repo; }

      public AccountView view(String acctId) {
          Optional<byte[]> xref = repo.readXref(acctId);
          if (xref.isEmpty()) return null;
          Optional<byte[]> acct = repo.readAccount(acctId);
          if (acct.isEmpty()) return null;
          // XREF-CUST-ID at offset 16, PIC 9(09) DISPLAY
          String custId = CobolRecordCodec.text(xref.get(), 16, 9);
          Optional<byte[]> cust = repo.readCustomer(custId);
          if (cust.isEmpty()) return null;

          byte[] a = acct.get();
          byte[] c = cust.get();
          // CVACT01Y offsets: ACCT-ID 0..11, STATUS 11..12, CURR-BAL 12.. (COMP-3 6 bytes)
          String status = CobolRecordCodec.text(a, 11, 1);
          BigDecimal balance = PackedDecimal.decode(java.util.Arrays.copyOfRange(a, 12, 18), 2);
          BigDecimal limit   = PackedDecimal.decode(java.util.Arrays.copyOfRange(a, 18, 24), 2);
          // CVCUS01Y offsets: CUST-FIRST-NAME 9..34, CUST-LAST-NAME 59..84, FICO 488..491
          String first = CobolRecordCodec.text(c, 9, 25);
          String last  = CobolRecordCodec.text(c, 59, 25);
          int fico = Integer.parseInt(CobolRecordCodec.text(c, 488, 3).strip());
          return CobolRecordCodec.assemble(acctId, status, balance, limit,
                                           custId, first, last, fico);
      }
  }
  ```
- [ ] Create `api/AccountViewController.java`:
  ```java
  package com.cobolmodernizer.accountview.api;

  import com.cobolmodernizer.accountview.domain.AccountViewService;
  import org.springframework.http.ResponseEntity;
  import org.springframework.web.bind.annotation.GetMapping;
  import org.springframework.web.bind.annotation.PathVariable;
  import org.springframework.web.bind.annotation.RestController;

  @RestController
  public class AccountViewController {
      private final AccountViewService service;

      public AccountViewController(AccountViewService service) { this.service = service; }

      @GetMapping("/api/accounts/{acctId}/view")
      public ResponseEntity<AccountView> view(@PathVariable String acctId) {
          AccountView v = service.view(acctId);
          return v == null ? ResponseEntity.notFound().build() : ResponseEntity.ok(v);
      }
  }
  ```
- [ ] Run `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml -Dtest=AccountViewControllerTest test` — expected PASS (Tests run: 2, Failures: 0).
- [ ] Run the full build: `mvn -q -f /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/pom.xml test` — expected PASS (all 7 tests green: 3 PackedDecimal + 2 CobolRecordCodec + 2 Controller).
- [ ] Commit: `feat(account-view): read-path service (xref->acct->cust) + REST controller`

---

## Task 2.7 — Tolerance rules (COMP-3 / scale / date / EBCDIC / spaces)

The dark-launch diff must be *outcome* parity, not byte parity. Encode the explicit tolerance rules the master plan §5 requires.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/darklaunch/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/darklaunch/tolerance.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_tolerance_rules.py`

Steps:
- [ ] Write failing test `tests/unit/test_tolerance_rules.py`:
  ```python
  from cobol_modernizer.darklaunch.tolerance import (
      ToleranceRule, fields_equal, default_rules,
  )

  def test_numeric_scale_equal_within_two_decimals():
      r = ToleranceRule(field="currentBalance", kind="numeric", scale=2)
      assert fields_equal("1234.5600", "1234.56", r) is True
      assert fields_equal("1234.56", "1234.57", r) is False

  def test_trailing_space_insensitive_text():
      r = ToleranceRule(field="customerLastName", kind="text")
      assert fields_equal("DOE   ", "DOE", r) is True

  def test_date_normalizes_formats():
      r = ToleranceRule(field="openDate", kind="date")
      assert fields_equal("2022-07-19", "07/19/2022", r) is True
      assert fields_equal("2022-07-19", "2022-07-20", r) is False

  def test_exact_kind_is_byte_equal():
      r = ToleranceRule(field="activeStatus", kind="exact")
      assert fields_equal("Y", "Y", r) is True
      assert fields_equal("Y", "N", r) is False

  def test_default_rules_cover_accountview_fields():
      names = {r.field for r in default_rules()}
      assert {"currentBalance", "creditLimit", "customerLastName", "ficoScore"} <= names
  ```
- [ ] Run `uv run pytest tests/unit/test_tolerance_rules.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/darklaunch/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/darklaunch/tolerance.py`:
  ```python
  """Explicit equivalence tolerance rules (master plan §5): outcome parity, not byte
  parity. Covers COMP-3/numeric scale, COBOL date formats, EBCDIC->ASCII text with
  trailing-space padding, and exact-match fields."""
  from __future__ import annotations

  import re
  from dataclasses import dataclass
  from decimal import Decimal


  @dataclass(frozen=True)
  class ToleranceRule:
      field: str
      kind: str          # "numeric" | "text" | "date" | "exact"
      scale: int = 0     # for numeric: significant decimal places


  def _to_iso_date(s: str) -> str:
      s = s.strip()
      if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
          return s
      m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)  # MM/DD/YYYY
      if m:
          mm, dd, yyyy = m.groups()
          return f"{yyyy}-{mm}-{dd}"
      return s


  def fields_equal(expected: str, actual: str, rule: ToleranceRule) -> bool:
      if rule.kind == "numeric":
          q = Decimal(10) ** -rule.scale
          return Decimal(str(expected)).quantize(q) == Decimal(str(actual)).quantize(q)
      if rule.kind == "text":
          return str(expected).rstrip() == str(actual).rstrip()
      if rule.kind == "date":
          return _to_iso_date(str(expected)) == _to_iso_date(str(actual))
      # exact
      return str(expected) == str(actual)


  def default_rules() -> list[ToleranceRule]:
      """Tolerance profile for the AccountView slice."""
      return [
          ToleranceRule("accountId", "exact"),
          ToleranceRule("activeStatus", "exact"),
          ToleranceRule("currentBalance", "numeric", scale=2),
          ToleranceRule("creditLimit", "numeric", scale=2),
          ToleranceRule("customerId", "exact"),
          ToleranceRule("customerFirstName", "text"),
          ToleranceRule("customerLastName", "text"),
          ToleranceRule("ficoScore", "exact"),
      ]
  ```
- [ ] Run `uv run pytest tests/unit/test_tolerance_rules.py` — expected PASS (5 passed).
- [ ] Commit: `feat(darklaunch): explicit COMP-3/scale/date/EBCDIC tolerance rules`

---

## Task 2.8 — Diff engine (field-level, tolerance-aware) → DiffReport

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/darklaunch/diff.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_darklaunch_diff.py`

Steps:
- [ ] Write failing test `tests/unit/test_darklaunch_diff.py`:
  ```python
  from cobol_modernizer.darklaunch.diff import diff_outputs, DiffReport
  from cobol_modernizer.darklaunch.tolerance import default_rules

  GOLDEN = {"accountId": "00000000123", "activeStatus": "Y",
            "currentBalance": "1234.56", "creditLimit": "5000.00",
            "customerId": "000000042", "customerFirstName": "JANE",
            "customerLastName": "DOE", "ficoScore": "720"}

  def test_match_within_tolerance():
      actual = dict(GOLDEN)
      actual["currentBalance"] = "1234.5600"     # scale tolerated
      actual["customerLastName"] = "DOE   "      # trailing spaces tolerated
      rep = diff_outputs(GOLDEN, actual, default_rules())
      assert isinstance(rep, DiffReport)
      assert rep.matched is True
      assert rep.mismatches == []

  def test_balance_mismatch_is_flagged_with_field():
      actual = dict(GOLDEN); actual["currentBalance"] = "1234.99"
      rep = diff_outputs(GOLDEN, actual, default_rules())
      assert rep.matched is False
      assert any(m["field"] == "currentBalance" for m in rep.mismatches)
      assert rep.mismatches[0]["expected"] == "1234.56"

  def test_missing_field_is_a_mismatch():
      actual = dict(GOLDEN); del actual["ficoScore"]
      rep = diff_outputs(GOLDEN, actual, default_rules())
      assert rep.matched is False
      assert any(m["field"] == "ficoScore" for m in rep.mismatches)
  ```
- [ ] Run `uv run pytest tests/unit/test_darklaunch_diff.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/darklaunch/diff.py`:
  ```python
  """Field-level, tolerance-aware diff between COBOL golden output and the Spring
  Boot service output. Produces a DiffReport whose mismatches link a field to its
  expected/actual values — feeding the defect-ticket-to-seam linkage (Phase 3)."""
  from __future__ import annotations

  from dataclasses import dataclass, field

  from cobol_modernizer.darklaunch.tolerance import ToleranceRule, fields_equal


  @dataclass
  class DiffReport:
      matched: bool
      mismatches: list[dict] = field(default_factory=list)  # [{field, expected, actual}]


  def diff_outputs(golden: dict, actual: dict, rules: list[ToleranceRule]) -> DiffReport:
      mismatches: list[dict] = []
      for rule in rules:
          if rule.field not in actual:
              mismatches.append({"field": rule.field,
                                 "expected": golden.get(rule.field), "actual": None,
                                 "reason": "missing"})
              continue
          exp = golden.get(rule.field)
          act = actual.get(rule.field)
          if not fields_equal(str(exp), str(act), rule):
              mismatches.append({"field": rule.field, "expected": str(exp),
                                 "actual": str(act), "reason": rule.kind})
      return DiffReport(matched=(len(mismatches) == 0), mismatches=mismatches)
  ```
- [ ] Run `uv run pytest tests/unit/test_darklaunch_diff.py` — expected PASS (3 passed).
- [ ] Commit: `feat(darklaunch): field-level tolerance-aware diff engine + DiffReport`

---

## Task 2.9 — Dark-launch runner: replay captured inputs to both paths

Replay Phase-0 captured account ids against the Spring Boot service, compare each response to the COBOL golden output, and emit an aggregate report. Tested against a fake HTTP client so the unit test needs no running service.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/darklaunch/fixtures.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/darklaunch/runner.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/coactvwc_inputs.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/coactvwc_golden.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_darklaunch_runner.py`

Steps:
- [ ] Create `tests/fixtures/coactvwc_inputs.json`:
  ```json
  ["00000000123", "00000000456"]
  ```
- [ ] Create `tests/fixtures/coactvwc_golden.json`:
  ```json
  {
    "00000000123": {"accountId": "00000000123", "activeStatus": "Y",
                    "currentBalance": "1234.56", "creditLimit": "5000.00",
                    "customerId": "000000042", "customerFirstName": "JANE",
                    "customerLastName": "DOE", "ficoScore": "720"},
    "00000000456": {"accountId": "00000000456", "activeStatus": "N",
                    "currentBalance": "0.00", "creditLimit": "2500.00",
                    "customerId": "000000099", "customerFirstName": "JOHN",
                    "customerLastName": "SMITH", "ficoScore": "640"}
  }
  ```
- [ ] Write failing test `tests/integration/test_darklaunch_runner.py`:
  ```python
  import json
  from pathlib import Path

  from cobol_modernizer.darklaunch.runner import run_dark_launch, DarkLaunchSummary

  FIX = Path(__file__).parents[1] / "fixtures"

  class FakeService:
      """Stand-in for the Spring Boot service: returns golden (match scenario) or a
      perturbed value (mismatch scenario)."""
      def __init__(self, responses): self.responses = responses
      def get_account_view(self, acct_id): return self.responses.get(acct_id)

  def test_all_match_passes():
      inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
      golden = json.loads((FIX / "coactvwc_golden.json").read_text())
      svc = FakeService(golden)  # perfect parity
      summary = run_dark_launch(inputs, golden, svc)
      assert isinstance(summary, DarkLaunchSummary)
      assert summary.total == 2
      assert summary.matched == 2
      assert summary.passed is True

  def test_one_mismatch_fails_and_reports_field():
      inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
      golden = json.loads((FIX / "coactvwc_golden.json").read_text())
      perturbed = {k: dict(v) for k, v in golden.items()}
      perturbed["00000000123"]["currentBalance"] = "9999.99"   # injected defect
      svc = FakeService(perturbed)
      summary = run_dark_launch(inputs, golden, svc)
      assert summary.matched == 1
      assert summary.passed is False
      bad = [r for r in summary.reports if r["acct_id"] == "00000000123"][0]
      assert any(m["field"] == "currentBalance" for m in bad["mismatches"])
  ```
- [ ] Run `uv run pytest tests/integration/test_darklaunch_runner.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/darklaunch/fixtures.py`:
  ```python
  """Load Phase-0 captured COACTVWC dark-launch fixtures. In production these come
  from the MinIO object store (golden files captured by the Phase-0/Phase-3 harness);
  this module abstracts the source so tests can pass dicts directly."""
  from __future__ import annotations

  import json
  from pathlib import Path


  def load_inputs(path: str | Path) -> list[str]:
      return json.loads(Path(path).read_text())


  def load_golden(path: str | Path) -> dict[str, dict]:
      return json.loads(Path(path).read_text())
  ```
- [ ] Create `src/cobol_modernizer/darklaunch/runner.py`:
  ```python
  """Dark launch: replay captured COACTVWC inputs against the Spring Boot service and
  diff each response against the COBOL golden output. The service client is injected
  (a Protocol) so unit tests use a fake and integration uses a real HTTP client.
  Outcome parity, not feature parity — uses the explicit tolerance rules."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from typing import Protocol

  from cobol_modernizer.darklaunch.diff import diff_outputs
  from cobol_modernizer.darklaunch.tolerance import default_rules


  class ServiceClient(Protocol):
      def get_account_view(self, acct_id: str) -> dict | None: ...


  @dataclass
  class DarkLaunchSummary:
      total: int
      matched: int
      passed: bool
      reports: list[dict] = field(default_factory=list)


  def run_dark_launch(inputs: list[str], golden: dict[str, dict],
                      service: ServiceClient) -> DarkLaunchSummary:
      rules = default_rules()
      reports: list[dict] = []
      matched = 0
      for acct_id in inputs:
          expected = golden.get(acct_id, {})
          actual = service.get_account_view(acct_id) or {}
          rep = diff_outputs(expected, actual, rules)
          if rep.matched:
              matched += 1
          reports.append({"acct_id": acct_id, "matched": rep.matched,
                          "mismatches": rep.mismatches})
      return DarkLaunchSummary(total=len(inputs), matched=matched,
                               passed=(matched == len(inputs)), reports=reports)
  ```
- [ ] Run `uv run pytest tests/integration/test_darklaunch_runner.py` — expected PASS (2 passed).
- [ ] Commit: `feat(darklaunch): dual-run replay + aggregate parity summary`

---

## Task 2.10 — Slice gates: attributed RBAC approvals + cost cap per stage

Each stage transition (BRD → seam → story → design → code → equivalence) is a hard gate persisted in Postgres `gate`/`approval`, requires an **attributed** approval (`approver_email`, `approver_role`, `rationale`), and checks `CostPolicy` before advancing.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/gates.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_gates.py`

Steps:
- [ ] Write failing test `tests/unit/test_slice_gates.py`:
  ```python
  import pytest
  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session

  from cobol_modernizer.persistence.tables import Base, Workspace
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
  from cobol_modernizer.slice.gates import (
      record_gate, approve_gate, SLICE_GATE_KEYS, advance_if_approved,
  )

  def _session():
      eng = create_engine("sqlite://")
      Base.metadata.create_all(eng)
      return Session(eng)

  def test_slice_gate_keys_cover_the_journey():
      assert SLICE_GATE_KEYS == [
          "brd_groundedness", "seam", "stories_dag",
          "design_data_ownership", "code", "equivalence",
      ]

  def test_record_and_approve_gate_with_rbac_identity():
      s = _session()
      ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                     created_by="cwijay@biz2bricks.ai")
      s.add(ws); s.flush()
      g = record_gate(s, workspace_id=ws.id, gate_key="brd_groundedness",
                      threshold={"min_weighted": 4.2, "accuracy_floor": 3},
                      result={"weighted": 4.4, "accuracy": 4})
      ap = approve_gate(s, gate_id=g.id, decision="approved",
                        approver_email="lead@biz2bricks.ai",
                        approver_role="lead_engineer", rationale="grounded, scoped")
      s.commit()
      assert g.status == "passed"
      assert ap.approver_email == "lead@biz2bricks.ai"
      assert ap.approver_role == "lead_engineer"

  def test_advance_blocked_when_cost_exceeded():
      ledger = CostLedger()
      ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=5.0)
      ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
      policy = CostPolicy(ledger)
      policy.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=6.0)
      with pytest.raises(BudgetExceeded):
          advance_if_approved(policy, workspace_id="w1", run_id="r1", gate_passed=True)

  def test_advance_blocked_when_gate_not_passed():
      ledger = CostLedger(); ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=5.0)
      ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
      policy = CostPolicy(ledger)
      assert advance_if_approved(policy, workspace_id="w1", run_id="r1",
                                 gate_passed=False) is False
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_gates.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/slice/gates.py`:
  ```python
  """Hard human gates for the thin-slice journey, persisted in Postgres gate/approval.
  Every approval is attributed (RBAC: approver_email + approver_role + rationale).
  Advancing a stage also checks the cost cap (kill-switch) — no stage proceeds past an
  unmet gate or an exceeded budget (master plan §1.6, §1.7)."""
  from __future__ import annotations

  from sqlalchemy.orm import Session

  from cobol_modernizer.cost.policy import CostPolicy
  from cobol_modernizer.persistence.tables import Approval, Gate

  # The six hard gates of the thin-slice journey, in order.
  SLICE_GATE_KEYS = [
      "brd_groundedness", "seam", "stories_dag",
      "design_data_ownership", "code", "equivalence",
  ]


  def record_gate(session: Session, *, workspace_id, gate_key: str,
                  threshold: dict, result: dict) -> Gate:
      g = Gate(workspace_id=workspace_id, stage_id=None, gate_key=gate_key,
               status="open", threshold=threshold, result=result)
      session.add(g)
      session.flush()
      return g


  def approve_gate(session: Session, *, gate_id, decision: str,
                   approver_email: str, approver_role: str, rationale: str,
                   risk_accepted: bool = False) -> Approval:
      if not approver_email or not approver_role:
          raise ValueError("attributed approval requires approver_email and role")
      ap = Approval(gate_id=gate_id, decision=decision,
                    approver_email=approver_email, approver_role=approver_role,
                    risk_accepted=risk_accepted, rationale=rationale)
      session.add(ap)
      g = session.get(Gate, gate_id)
      g.status = "passed" if decision in ("approved", "waived_with_risk") else "failed"
      session.flush()
      return ap


  def advance_if_approved(policy: CostPolicy, *, workspace_id: str, run_id: str,
                          gate_passed: bool) -> bool:
      """Advance only if the gate passed AND the budget is intact. Raises
      BudgetExceeded (and trips the kill-switch) if the cap is hit; returns False if
      the gate did not pass."""
      if not gate_passed:
          return False
      policy.check(workspace_id=workspace_id, run_id=run_id)  # raises on cap
      return True
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_gates.py` — expected PASS (4 passed).
- [ ] Commit: `feat(slice): attributed RBAC gate/approval + cost-capped stage advance`

---

## Task 2.11 — Service design artifact (ACL-vs-CDC decision) over Cypher evidence

Produce the design doc for the slice. The transition-pattern decision (DB reader → CDC/replica in production; captured-VSAM ACL for dark launch) is recorded with its evidence; the LLM (`design` role → Opus) writes rationale over the **deterministic reader/writer classification** from Phase-1 Cypher.

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/slice/design.py`
- Test: append to `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_brd_scope.py` (new test fns) — or a new file; here a new file.
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_slice_design.py`

Steps:
- [ ] Write failing test `tests/unit/test_slice_design.py`:
  ```python
  from cobol_modernizer.slice.design import (
      choose_transition_pattern, DesignDecision, design_model,
  )

  def test_reader_only_chooses_cdc_replica_with_acl_for_dark_launch():
      d = choose_transition_pattern(reader_only=True, writes=0)
      assert isinstance(d, DesignDecision)
      assert d.production_pattern == "CDC/replica"
      assert d.dark_launch_pattern == "captured-VSAM ACL"
      assert "no identity drift" in d.rationale.lower()

  def test_writer_routes_to_extract_product_lines_and_is_out_of_scope():
      import pytest
      with pytest.raises(ValueError, match="writer slice is Phase 5"):
          choose_transition_pattern(reader_only=False, writes=2)

  def test_design_role_is_opus():
      assert design_model() == "claude-opus-4-8"  # 'design' role tier
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_design.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/slice/design.py`:
  ```python
  """Transition-pattern decision for the slice, driven by the DETERMINISTIC Phase-1
  reader/writer classification (Fowler 'uncovering-mainframe-seams': reader -> CDC;
  writer -> Extract Product Lines + ACL, single-system until fully extracted). The
  'design' role (Opus) only writes rationale; it does not decide reader-vs-writer."""
  from __future__ import annotations

  from dataclasses import dataclass

  from cobol_modernizer.cost.tiering import resolve_model


  @dataclass(frozen=True)
  class DesignDecision:
      production_pattern: str
      dark_launch_pattern: str
      rationale: str


  def design_model() -> str:
      return resolve_model("design")


  def choose_transition_pattern(*, reader_only: bool, writes: int) -> DesignDecision:
      if not reader_only or writes > 0:
          raise ValueError("writer slice is Phase 5 (Extract Product Lines + Legacy "
                           "Mimic write-back); Phase 2 is read-only only")
      return DesignDecision(
          production_pattern="CDC/replica",
          dark_launch_pattern="captured-VSAM ACL",
          rationale=("Reader-only seam: production reads via CDC/replica behind an "
                     "anti-corruption layer; dark launch reads Phase-0 captured VSAM "
                     "slices so the new service sees exactly the bytes COBOL saw. No "
                     "writes means no identity drift, so the COBOL path stays "
                     "authoritative during dark launch."),
      )
  ```
- [ ] Run `uv run pytest tests/unit/test_slice_design.py` — expected PASS (3 passed).
- [ ] Commit: `feat(slice): reader-only transition-pattern decision (CDC + ACL) over Cypher evidence`

---

## Task 2.12 — CI workflow for the generated service (build + test + coverage)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/.github/workflows/account-view-ci.yml`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_ci_workflow_config.py`

Steps:
- [ ] Write failing test `tests/unit/test_ci_workflow_config.py`:
  ```python
  from pathlib import Path

  ROOT = Path(__file__).parents[2]
  CI = ROOT / ".github" / "workflows" / "account-view-ci.yml"

  def test_ci_builds_and_tests_the_generated_service():
      text = CI.read_text()
      assert "account-view-service" in text
      assert "mvn" in text and "test" in text
      assert "java-version: '25'" in text or 'java-version: "25"' in text
      assert "jacoco" in text.lower() or "coverage" in text.lower()
  ```
- [ ] Run `uv run pytest tests/unit/test_ci_workflow_config.py` — expected FAIL: file missing.
- [ ] Create `.github/workflows/account-view-ci.yml`:
  ```yaml
  name: account-view-ci
  on:
    push:
      paths: ["generated/account-view-service/**"]
    pull_request:
      paths: ["generated/account-view-service/**"]
  jobs:
    build-test:
      runs-on: ubuntu-latest
      defaults:
        run:
          working-directory: generated/account-view-service
      steps:
        - uses: actions/checkout@v4
        - name: Set up JDK 25
          uses: actions/setup-java@v4
          with:
            distribution: temurin
            java-version: '25'
        - name: Build, test, coverage (jacoco)
          run: mvn -B verify
        - name: Upload jacoco coverage report
          uses: actions/upload-artifact@v4
          with:
            name: jacoco-report
            path: generated/account-view-service/target/site/jacoco/
  ```
- [ ] Run `uv run pytest tests/unit/test_ci_workflow_config.py` — expected PASS (1 passed).
- [ ] Commit: `ci(account-view): maven build+test+jacoco coverage workflow`

---

## Task 2.13 — Wire the slice + dark-launch endpoints into the FastAPI control plane

Expose the journey via REST + SSE so the cockpit can drive it: select slice, run slice BRD, run stories, run design, trigger dark launch, fetch report. Each run records an `agent_run` and persists artifacts; SSE streams events (master plan §6). Keep agent execution in FastAPI (never Next server functions).

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/api.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_slice_api.py`

Steps:
- [ ] Write failing test `tests/integration/test_slice_api.py` (FastAPI TestClient; the slice router uses dependency-injected fakes so no Neo4j/LLM needed):
  ```python
  from fastapi.testclient import TestClient

  from cobol_modernizer.api import app

  def test_dark_launch_report_endpoint_returns_summary():
      client = TestClient(app)
      payload = {
          "inputs": ["00000000123"],
          "golden": {"00000000123": {"accountId": "00000000123", "activeStatus": "Y",
                     "currentBalance": "1234.56", "creditLimit": "5000.00",
                     "customerId": "000000042", "customerFirstName": "JANE",
                     "customerLastName": "DOE", "ficoScore": "720"}},
          "actual": {"00000000123": {"accountId": "00000000123", "activeStatus": "Y",
                     "currentBalance": "1234.5600", "creditLimit": "5000.00",
                     "customerId": "000000042", "customerFirstName": "JANE",
                     "customerLastName": "DOE  ", "ficoScore": "720"}},
      }
      r = client.post("/api/slice/dark-launch", json=payload)
      assert r.status_code == 200
      body = r.json()
      assert body["passed"] is True
      assert body["matched"] == 1

  def test_select_slice_endpoint_picks_reader_only():
      client = TestClient(app)
      cands = [
          {"program": "COACTVWC", "fan_in": 1, "fan_out": 0, "reader_only": True,
           "writes": 0, "reads": 3, "score": 0.91},
          {"program": "COACTUPC", "fan_in": 3, "fan_out": 2, "reader_only": False,
           "writes": 2, "reads": 4, "score": 0.31},
      ]
      r = client.post("/api/slice/select", json={"candidates": cands})
      assert r.status_code == 200
      assert r.json()["program"] == "COACTVWC"
  ```
- [ ] Run `uv run pytest tests/integration/test_slice_api.py` — expected FAIL (endpoints 404 / app import error).
- [ ] Add to `src/cobol_modernizer/api.py` a slice router (append; do not disturb existing routes):
  ```python
  # --- Phase 2: thin-slice + dark-launch endpoints -------------------------------
  from fastapi import APIRouter
  from pydantic import BaseModel

  from cobol_modernizer.slice.selection import pick_slice
  from cobol_modernizer.darklaunch.runner import run_dark_launch

  slice_router = APIRouter(prefix="/api/slice", tags=["slice"])


  class SelectRequest(BaseModel):
      candidates: list[dict]


  class DarkLaunchRequest(BaseModel):
      inputs: list[str]
      golden: dict[str, dict]
      actual: dict[str, dict]


  class _DictClient:
      """Service client backed by a precomputed dict of responses (for replay/test
      and for the dark-launch report endpoint that receives both sides)."""
      def __init__(self, responses: dict[str, dict]): self._r = responses
      def get_account_view(self, acct_id: str): return self._r.get(acct_id)


  @slice_router.post("/select")
  def select_slice(req: SelectRequest):
      choice = pick_slice(req.candidates)
      return {"program": choice.program, "reader_only": choice.reader_only,
              "score": choice.score, "evidence": choice.evidence}


  @slice_router.post("/dark-launch")
  def dark_launch(req: DarkLaunchRequest):
      summary = run_dark_launch(req.inputs, req.golden, _DictClient(req.actual))
      return {"total": summary.total, "matched": summary.matched,
              "passed": summary.passed, "reports": summary.reports}


  app.include_router(slice_router)
  ```
- [ ] Run `uv run pytest tests/integration/test_slice_api.py` — expected PASS (2 passed).
- [ ] Commit: `feat(api): /api/slice select + dark-launch endpoints (FastAPI control plane)`

---

## Task 2.14 — Full slice regression + cost assertion

A single test that runs the whole Python pipeline (selection → tolerance/diff → dark-launch parity) and asserts the run cost stayed under cap, proving the exit criteria hold together.

**Files:**
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_slice_end_to_end.py`

Steps:
- [ ] Write failing test `tests/integration/test_slice_end_to_end.py`:
  ```python
  import json
  from pathlib import Path

  from cobol_modernizer.slice.selection import pick_slice
  from cobol_modernizer.slice.design import choose_transition_pattern
  from cobol_modernizer.darklaunch.runner import run_dark_launch
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger

  FIX = Path(__file__).parents[1] / "fixtures"

  def test_thin_slice_pipeline_parity_under_cap():
      # 1) seam ranking -> reader-only slice
      cands = json.loads((FIX / "seam_candidates_sample.json").read_text())
      choice = pick_slice(cands)
      assert choice.program == "COACTVWC"
      # 2) design decision is CDC + ACL, no identity drift
      design = choose_transition_pattern(reader_only=choice.reader_only,
                                         writes=choice.evidence["writes"])
      assert design.production_pattern == "CDC/replica"
      # 3) dark launch diff-matches within tolerance
      inputs = json.loads((FIX / "coactvwc_inputs.json").read_text())
      golden = json.loads((FIX / "coactvwc_golden.json").read_text())

      class Svc:
          def get_account_view(self, a): return golden.get(a)
      summary = run_dark_launch(inputs, golden, Svc())
      assert summary.passed is True
      # 4) cost stayed under cap
      ledger = CostLedger()
      ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
      ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
      policy = CostPolicy(ledger)
      policy.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=2.3)
      policy.check(workspace_id="w1", run_id="r1")  # no raise
      assert policy.remaining_usd(workspace_id="w1") == 47.7
  ```
- [ ] Run `uv run pytest tests/integration/test_slice_end_to_end.py` — expected PASS (1 passed) given Tasks 2.1–2.13 are done.
- [ ] Run the full Python suite: `uv run pytest tests/` — expected PASS (all Phase 2 tests green).
- [ ] Run the full Java suite: `mvn -q -f generated/account-view-service/pom.xml test` — expected PASS (7 tests).
- [ ] Commit: `test(slice): end-to-end thin-slice parity-under-cap regression`

---

## Acceptance criteria

Mapped 1:1 to the **Phase 2 Exit criteria** in `IMPLEMENTATION_PLAN.md` §3 ("Phase 2 — Thin vertical slice"): *"the slice runs in parallel with COBOL on captured inputs and **diff-matches** within tolerance; a human approved BRD→seam→story→design→code at each gate; cost stayed under cap."*

1. **Seam-ranking surfaces account-view as the safe first slice (deterministic, no LLM).** `slice/selection.py:pick_slice` consumes the Phase-1 `seam_candidates` Cypher output and chooses the top reader-only program (COACTVWC), rejecting any non-reader-only set; `test_slice_selection.py` proves it. Scoring is NOT re-implemented in Python and no LLM is in the path. (master plan §1.4, §3-Phase2, §4.2)
2. **Focused BRD for the slice.** `slice/slice_brd.py` reuses the working groundedness-gated BRD harness/judge but scopes evidence to the single program's subgraph via read-only MCP tools, separating required from accidental behavior; `test_slice_brd_scope.py` proves the scoped prompt + tier. (§1.2, §3-Phase2, §5)
3. **Story cluster with acyclic DAG + lineage.** `slice/stories.py:assert_acyclic` enforces an acyclic dependency DAG and per-story evidence_map; `test_slice_stories_dag.py` proves both pass and cycle/no-evidence rejection. (§1.2, §3-Phase2)
4. **Generated Spring Boot read-path service.** `generated/account-view-service` compiles and tests green (COMP-3 decoder, ACL codec, read-path service mirroring `9000-READ-ACCT`, REST controller) — read path via an anti-corruption adapter over Phase-0 captured VSAM, CDC/replica as the production pattern; `PackedDecimalTest`, `CobolRecordCodecTest`, `AccountViewControllerTest` all pass. (§3-Phase2, §2 "anti-corruption adapter")
5. **Dark launch with output diffing, within explicit tolerance.** `darklaunch/tolerance.py` + `diff.py` + `runner.py` replay captured COACTVWC inputs against the service and diff each response to the COBOL golden output with COMP-3/scale/date/EBCDIC/space tolerance; a perfect run reports `passed=True`, an injected balance defect reports `passed=False` with the offending field. `test_tolerance_rules.py`, `test_darklaunch_diff.py`, `test_darklaunch_runner.py` prove it. This is the **diff-matches within tolerance** criterion. (§3-Phase2, §5 "outcome parity, not feature parity")
6. **Human approved at each gate, attributed (RBAC).** `slice/gates.py` persists the six ordered gates (`brd_groundedness → seam → stories_dag → design_data_ownership → code → equivalence`) to Postgres with `approval.approver_email`/`approver_role`/`rationale`; `advance_if_approved` blocks advancing on an unmet gate; `test_slice_gates.py` proves the round-trip and the block. (§1.6, §3-Phase2)
7. **Cost stayed under cap (kill-switch).** `advance_if_approved` calls `CostPolicy.check`, which raises `BudgetExceeded` and trips the kill-switch when the per-run or per-workspace cap is exceeded; `test_slice_gates.py::test_advance_blocked_when_cost_exceeded` and `test_slice_end_to_end.py` (remaining-under-cap) prove it. (§1.7, §3-Phase2, §4.10)
8. **CI/observability.** `.github/workflows/account-view-ci.yml` builds, tests, and produces JaCoCo coverage for the generated service on every change; `test_ci_workflow_config.py` proves the workflow is configured. (§3-Phase2 "CI/observability")
9. **Control-plane wiring.** `/api/slice/select` and `/api/slice/dark-launch` expose the slice selection and dark-launch parity report through the FastAPI control plane (agent execution stays in FastAPI, not Next); `test_slice_api.py` proves both. (§6)
10. **End-to-end regression.** `test_slice_end_to_end.py` runs selection → design → dark-launch parity → cost check in one test and passes, demonstrating the whole thin slice holds together under cap. (§3-Phase2 exit criteria, composite)

**Invariants preserved (do not regress, per foundation §7):** read-only Cypher / read-only MCP tools (no new write tool added); seam math stays in Cypher (selection consumes it, never recomputes); single versioned JSON contract untouched; `tools=[]`/`setting_sources=[]`/`json_schema` harness reused verbatim; every artifact carries an `evidence_map`; COBOL graceful degradation unaffected (this slice reads captured golden data). Writer paths and a true COBOL execution environment are explicitly **out of scope** (Phase 3 Equivalence Lab hardens the COBOL-execution/golden-capture side; Phase 5 handles writer slices).
