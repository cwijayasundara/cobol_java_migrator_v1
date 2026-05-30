# Phase 4 — Seam Engine & Increment Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Generalize from the single Phase-2 slice to a **ranked, scored seam backlog** with explainable evidence, a **transition-pattern recommendation** per seam type, an **INVEST-judged acyclic story DAG**, and a **dead-code / duplicate-capability lens** that *enforces* the required-vs-accidental behavior distinction rather than asserting it. Every numeric score is computed in **Cypher / Neo4j-GDS over the v2 graph (READS/WRITES/EXECUTES_CICS/EXECUTES_SQL/MOVES_TO/GO_TO edges)** — the LLM only writes **rationale** over precomputed evidence. Zero LLM in the scoring path.

**Architecture:** Deterministic seam math lives in `src/cobol_modernizer/seam/scoring.py` as parametrized read-only Cypher (extends `queries.py` / `graph_ops.py`). The score formula is `0.25·business + 0.20·isolation + 0.20·testability + 0.20·data_ownership − 0.15·risk` over normalized [0,1] signals. A `seam_candidates` / `reader_writer_classification` / `data_accesses` v2 MCP tool surface (read-only, `readOnlyHint=True`) exposes the precomputed evidence to bounded agents. The seam-rationale agent and story-planner agent reuse the existing `SdkAgentRunner` (`tools=[]`, `setting_sources=[]`, `json_schema`) and the groundedness-gate pattern from `brd_judge.py` (any evidence ref not in `graph_ops.known_refs` floors the score). The story DAG is validated **deterministically acyclic** in Python (Kahn topological sort) — never trusted from the LLM. Dead-paragraph and duplicate-capability detection run as Cypher over `GO_TO`/`CALLS(perform)` reachability and a capability fingerprint over data-access signatures. Artifacts (`seam_set`, `story_dag`) persist to Postgres `artifact` + MinIO; gates persist to Postgres `gate`/`approval`.

**Tech Stack:** Python 3.12 + uv; pydantic 2.9; Neo4j 5.24-enterprise + GDS 2.x (read-only Cypher); pytest + pytest-asyncio (`asyncio_mode=auto`); `claude-agent-sdk==0.2.87`. Depends on Phase 0 (persistence + cost) and **is blocked until Phase 1 exits** (the v2 IO/data-flow edges this phase scores over must already be in the graph).

**Depends on (binding):**
- **Phase 1** — v2 graph enrichment. Phase 4 reads `READS`/`WRITES` (with `metadata.mode`/`resourceType`), `EXECUTES_CICS`/`EXECUTES_SQL` (with `metadata.intent`), `MOVES_TO`, `GO_TO` edges and `DataItem` nodes. **Phases 4+ are *blocked*, not deferred, until Phase 1 exits** (master plan §7 risk 2). If these edges are absent, seam scoring would silently fall back to LLM guessing — forbidden.
- **Phase 0** — Postgres `artifact`/`gate`/`approval`/`agent_run`/`budget` tables; `CostPolicy`; `resolve_model`.
- **Foundation (00)** — schemaVersion=2 contract, MCP graph tool surface (`seam_candidates`/`reader_writer_classification`/`data_accesses` reserved), `evidence_map` + groundedness-gate contract, read-only Cypher invariant.

**Ground truth (CardDemo, verified in source):**
- `COACTVWC.cbl` — CICS online **reader-only** (account view): `EXEC CICS READ DATASET(ACCTFILENAME/CUSTFILENAME/CARDXREF...)`, no WRITE/REWRITE → low-risk seam, CDC/replica candidate.
- `CBTRN02C.cbl` — batch **writer** (transaction poster): `OPEN I-O ACCOUNT-FILE`, `REWRITE FD-ACCTFILE-REC`, `REWRITE FD-TRAN-CAT-BAL-RECORD`, `WRITE FD-TRANFILE-REC` → **identity-drift writer**, must stay single-system (Extract Product Lines + ACL).
- `CBACT01C.cbl` — batch reader of `ACCTFILE` (INDEXED, SEQUENTIAL) writing sequential output files → Batch IO seam (Spring Batch adapter).
- Duplicate capability: date-validation logic appears in `CSUTLDTC.cbl` (the canonical date util) and is duplicated/inlined in `COACTUPC.cbl`, `CORPT00C.cbl`, `COTRN02C.cbl` → capability-level dedup target.

---

## File Structure

All paths under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
src/cobol_modernizer/seam/                          # NEW — Phase 4 seam engine (deterministic, Cypher-backed)
├── __init__.py
├── schema.py             # SeamCandidate/SeamSignals/SeamScore/TransitionPattern/SeamSet pydantic models + evidence_map
├── signals.py            # read-only Cypher: business/isolation/testability/data_ownership/risk raw signals per program
├── scoring.py            # pure-Python normalization + weighted formula 0.25b+0.20i+0.20t+0.20d-0.15r; orchestrates signals.py
├── reader_writer.py      # Cypher reader-vs-writer classification + identity-drift-writer (single-system) flagging
├── transition.py         # deterministic seam-type -> transition-pattern mapping (Batch IO/CICS/DB reader/DB writer/copybook)
├── deadcode.py           # Cypher dead-paragraph (unreachable via CALLS(perform)/GO_TO from program entry) detection
├── dedup.py              # capability fingerprint (data-access signature) -> duplicate-capability clusters
├── rationale.py          # seam-rationale agent (Sonnet) over precomputed evidence; groundedness-gated
└── service.py            # SeamEngine facade: build_seam_set() -> persists artifact(kind='seam_set') + gate

src/cobol_modernizer/planner/                       # NEW — Phase 4 increment / story planner
├── __init__.py
├── schema.py             # Story/StoryDAG/InvestScore models + evidence_map
├── dag.py                # deterministic Kahn topological sort + cycle detection (acyclic gate)
├── dependency.py         # Cypher: derive story dependency edges from shared-data-ownership / CALLS between seams
├── invest.py             # INVEST judge (Sonnet) + deterministic acyclic enforcement; reuses groundedness floor
└── service.py            # StoryPlanner facade: build_story_dag() -> persists artifact(kind='story_dag') + stories_dag gate

src/cobol_modernizer/agent/graph_ops.py             # MODIFY — add v2 read-only ops: data_accesses, reader_writer_classification, seam_candidates
src/cobol_modernizer/agent/graph_tools.py           # MODIFY — register v2 MCP tools (readOnlyHint=True), extend GRAPH_TOOL_NAMES + neighbors edge enum
src/cobol_modernizer/queries.py                     # MODIFY — add seam/reader-writer/dead-paragraph parametrized Cypher

tests/unit/
├── test_seam_scoring.py          # weighted formula + normalization + monotonicity
├── test_reader_writer.py         # reader/writer split + identity-drift single-system flag (CBTRN02C)
├── test_transition_pattern.py    # seam-type -> pattern mapping (all 5 types)
├── test_deadcode.py              # unreachable-paragraph detection
├── test_dedup.py                 # capability fingerprint clustering (CSUTLDTC date-validation dup)
├── test_story_dag.py             # Kahn topo-sort acyclic gate; cycle rejected
├── test_invest_judge.py          # INVEST scoring + groundedness floor (fake runner)
└── test_seam_rationale.py        # rationale agent groundedness floor (hallucinated ref -> evidence dropped)

tests/integration/
├── test_seam_signals_cypher.py   # signals.py Cypher against testcontainers Neo4j seeded with v2 CardDemo subgraph
├── test_seam_candidates_tool.py  # mcp__graph__seam_candidates returns ranked, read-only; write Cypher rejected
└── test_seam_engine_e2e.py       # SeamEngine.build_seam_set on seeded graph -> ranked backlog + identity-drift flag + dup

tests/fixtures/
├── carddemo_v2_subgraph.cypher   # seed: COACTVWC(reader), CBTRN02C(writer), CBACT01C(batch), CSUTLDTC+dupes, GO_TO/READS/WRITES
└── seam_evidence_sample.json     # canonical SeamSignals payload for scoring unit tests
```

---

## Background contracts this plan honors (verbatim from Foundation 00)

- **schemaVersion=2 edges** (the only signals seam math may use):
  - `READS`/`WRITES`: `metadata = {"resource","resourceType":"VSAM"|"FILE"|"DATAITEM","mode":"sequential"|"random"|"dynamic"}`. The `kind` itself (READS vs WRITES) carries the reader/writer distinction.
  - `EXECUTES_CICS`: `metadata = {"resource","command","intent":"read"|"write"}`.
  - `EXECUTES_SQL`: `metadata = {"resource","operation","intent":"read"|"write"}`.
  - `MOVES_TO`: DataItem→DataItem `{"line"}` (data-flow). `GO_TO`: paragraph→paragraph `{}` (control-flow; dead-paragraph).
  - `CALLS`: `metadata.type` is `"perform"` (paragraph→paragraph) or `"call"` (program→program).
- **Node label/props:** `CodeEntity {repo, qualified_name, simple_name, kind, file_path, start_line, end_line, is_external}`; v2 adds `DataItem`-kind entities with `level/picture/usage/redefines/occurs/parent_qname`. Every CardDemo program is a `CodeEntity {kind:"Program"}`.
- **`neo4j_client.run(query, **params) -> list[dict]`** (read-only assumed; the read-only guard rejects write clauses).
- **Groundedness gate (from `brd_judge.py`):** any evidence ref not in `graph_ops.known_refs(deps)` is a `groundedness_failure`; the dimension/score is floored. Weighted score, `Rating.high/medium/low` thresholds reused.
- **MCP invariants:** `tools=[]`, `setting_sources=[]`, `output_format=json_schema`; all new tools `ToolAnnotations(readOnlyHint=True)`; FQN `mcp__graph__<tool>`; extend `GRAPH_TOOL_NAMES` allow-list.
- **Model tiering:** `resolve_model("seam")` and `resolve_model("story")` → `claude-sonnet-4-6`; rationale/INVEST only write text over precomputed evidence. No model in the scoring path.
- **Persistence:** seam set → `artifact(kind='seam_set', evidence_map=...)`; story DAG → `artifact(kind='story_dag')`; gates → `gate(gate_key='stories_dag', threshold={"acyclic":true})` etc.; cost recorded via `CostPolicy.record_usage` + `check` around every agent run.

---

## Task 1 — Seam domain models (`seam/schema.py`)

**Files:**
- Create: `src/cobol_modernizer/seam/__init__.py`
- Create: `src/cobol_modernizer/seam/schema.py`
- Test: `tests/unit/test_seam_scoring.py` (model-shape portion; scoring added in Task 3)

Steps:
- [ ] Write failing test `tests/unit/test_seam_scoring.py`:
  ```python
  from cobol_modernizer.seam.schema import (
      SeamSignals, SeamScore, SeamType, TransitionPattern, SeamCandidate, SeamSet,
  )

  def test_seam_signals_clamped_to_unit_interval():
      s = SeamSignals(business=1.4, isolation=-0.2, testability=0.5,
                      data_ownership=0.8, risk=0.3)
      # raw values are stored as-given; scoring clamps. Model only validates shape.
      assert s.business == 1.4 and s.risk == 0.3

  def test_seam_candidate_carries_evidence_map():
      c = SeamCandidate(
          program="COACTVWC", seam_type=SeamType.cics_api,
          signals=SeamSignals(business=0.7, isolation=0.9, testability=0.8,
                              data_ownership=0.6, risk=0.1),
          score=SeamScore(weighted=0.0, normalized={}),
          transition=TransitionPattern(name="facade_routed_by_txn_id", summary=""),
          evidence_map={"isolation": ["COACTVWC"], "risk": ["COACTVWC"]},
          identity_drift_writer=False,
      )
      assert c.evidence_map["isolation"] == ["COACTVWC"]
      assert c.seam_type is SeamType.cics_api
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.seam'`.
- [ ] Create `src/cobol_modernizer/seam/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/seam/schema.py`:
  ```python
  from __future__ import annotations

  from enum import Enum
  from pydantic import BaseModel, Field

  EvidenceMap = dict[str, list[str]]
  """signal_name -> [graph entity ids / source refs] backing that signal."""


  class SeamType(str, Enum):
      batch_io = "batch_io"          # sequential file IO batch program -> Spring Batch adapter
      cics_api = "cics_api"          # CICS/online txn -> facade routed by transaction id
      db_reader = "db_reader"        # read-only data access -> CDC / read replica
      db_writer = "db_writer"        # write/REWRITE data access -> Extract Product Lines + ACL
      copybook = "copybook"          # shared copybook -> canonical DTO + anti-corruption layer


  class SeamSignals(BaseModel):
      """Raw, Cypher-computed signals (un-normalized). Scoring normalizes + weights."""
      business: float        # business-criticality proxy (fan-in + entry-point reach)
      isolation: float       # 1 - shared-state coupling (fewer shared resources = higher)
      testability: float     # reader-only + low control-flow complexity proxy
      data_ownership: float  # fraction of touched resources this program exclusively owns
      risk: float            # writer + side-effect (billing/audit) + churn proxy


  class SeamScore(BaseModel):
      weighted: float
      normalized: dict[str, float] = Field(default_factory=dict)  # signal -> [0,1]


  class TransitionPattern(BaseModel):
      name: str
      summary: str


  class SeamCandidate(BaseModel):
      program: str
      seam_type: SeamType
      signals: SeamSignals
      score: SeamScore
      transition: TransitionPattern
      evidence_map: EvidenceMap = Field(default_factory=dict)
      identity_drift_writer: bool = False  # writer that must stay single-system
      rationale: str = ""                  # LLM-written, groundedness-gated (Task 8)


  class SeamSet(BaseModel):
      repo_id: str
      candidates: list[SeamCandidate]      # ranked desc by score.weighted
      duplicate_capabilities: list[list[str]] = Field(default_factory=list)
      dead_paragraphs: list[str] = Field(default_factory=list)
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): seam domain models (SeamCandidate/SeamSignals/SeamSet) with evidence_map`

---

## Task 2 — Reader-vs-writer classification + identity-drift flagging (`seam/reader_writer.py`)

The pivotal Fowler distinction. Computed in Cypher over `READS`/`WRITES`/`EXECUTES_CICS`/`EXECUTES_SQL` edges. A program that issues any WRITE/REWRITE/`intent:"write"` against a VSAM/DB resource that is also read by ≥1 other program is an **identity-drift writer** → must stay single-system.

**Files:**
- Create: `src/cobol_modernizer/seam/reader_writer.py`
- Test: `tests/unit/test_reader_writer.py`

Steps:
- [ ] Write failing test `tests/unit/test_reader_writer.py` (fake graph client; no Neo4j):
  ```python
  from cobol_modernizer.seam.reader_writer import (
      classify_program, classify_resource, is_identity_drift_writer,
  )

  class FakeClient:
      """Returns canned rows keyed by a substring of the query."""
      def __init__(self, rows_by_key): self.rows_by_key = rows_by_key
      def run(self, query, **params):
          for key, rows in self.rows_by_key.items():
              if key in query:
                  return [r for r in rows if all(r.get(k) == v for k, v in params.items()
                                                 if k in r)]
          return []

  def test_coactvwc_is_reader_only():
      client = FakeClient({"accesses_for_program": [
          {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
          {"program": "COACTVWC", "resource": "CUSTFILE", "intent": "read"},
      ]})
      result = classify_program(client, repo="cardemo", program="COACTVWC")
      assert result["writes"] == []
      assert set(result["reads"]) == {"ACCTFILE", "CUSTFILE"}
      assert result["reader_only"] is True

  def test_cbtrn02c_is_identity_drift_writer():
      # CBTRN02C REWRITEs ACCTFILE; COACTVWC also reads ACCTFILE -> shared writer.
      client = FakeClient({
          "accesses_for_program": [
              {"program": "CBTRN02C", "resource": "ACCTFILE", "intent": "write"},
              {"program": "CBTRN02C", "resource": "TRANSACT", "intent": "write"},
          ],
          "readers_of_resource": [
              {"resource": "ACCTFILE", "reader": "COACTVWC"},
              {"resource": "ACCTFILE", "reader": "CBACT01C"},
          ],
      })
      assert is_identity_drift_writer(client, repo="cardemo", program="CBTRN02C") is True

  def test_pure_reader_is_not_identity_drift_writer():
      client = FakeClient({"accesses_for_program": [
          {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
      ]})
      assert is_identity_drift_writer(client, repo="cardemo", program="COACTVWC") is False
  ```
- [ ] Run `uv run pytest tests/unit/test_reader_writer.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/reader_writer.py`:
  ```python
  from __future__ import annotations

  from typing import Any, Protocol


  class GraphClient(Protocol):
      def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


  # Read-only. Normalizes READS/WRITES + CICS/SQL intent into (program, resource, intent).
  _ACCESSES_FOR_PROGRAM = """
  // accesses_for_program
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
  WHERE p.qualified_name = $program OR p.simple_name = $program
  WITH res.simple_name AS resource,
       CASE type(r)
            WHEN 'READS'  THEN 'read'
            WHEN 'WRITES' THEN 'write'
            ELSE coalesce(r.intent, 'read')
       END AS intent
  RETURN DISTINCT $program AS program, resource, intent
  """

  _READERS_OF_RESOURCE = """
  // readers_of_resource
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|EXECUTES_CICS|EXECUTES_SQL]->(res)
  WHERE res.simple_name = $resource
    AND (type(r) = 'READS' OR coalesce(r.intent,'read') = 'read')
  RETURN DISTINCT $resource AS resource, p.simple_name AS reader
  """


  def classify_program(client: GraphClient, *, repo: str, program: str) -> dict[str, Any]:
      rows = client.run(_ACCESSES_FOR_PROGRAM, repo=repo, program=program)
      reads = sorted({r["resource"] for r in rows if r["intent"] == "read"})
      writes = sorted({r["resource"] for r in rows if r["intent"] == "write"})
      return {"program": program, "reads": reads, "writes": writes,
              "reader_only": len(writes) == 0 and len(reads) > 0}


  def classify_resource(client: GraphClient, *, repo: str, resource: str) -> dict[str, Any]:
      readers = sorted({r["reader"] for r in
                        client.run(_READERS_OF_RESOURCE, repo=repo, resource=resource)})
      return {"resource": resource, "readers": readers}


  def is_identity_drift_writer(client: GraphClient, *, repo: str, program: str) -> bool:
      """A writer is identity-drift-prone (must stay single-system) when it writes a
      resource that other programs also read: splitting it risks two systems disagreeing
      about the canonical value. Fowler: identity-drift writers stay single-system."""
      cls = classify_program(client, repo=repo, program=program)
      for resource in cls["writes"]:
          other_readers = [rd for rd in classify_resource(client, repo=repo,
                                                           resource=resource)["readers"]
                           if rd != program]
          if other_readers:
              return True
      return False
  ```
- [ ] Run `uv run pytest tests/unit/test_reader_writer.py` — expected PASS (3 passed).
- [ ] Commit: `feat(seam): reader/writer classification + identity-drift writer (single-system) flag`

---

## Task 3 — Seam scoring formula + signal normalization (`seam/scoring.py`)

The exact master-plan formula `0.25·business + 0.20·isolation + 0.20·testability + 0.20·data_ownership − 0.15·risk` over signals normalized to [0,1]. Pure Python; deterministic; no LLM, no Neo4j (signals are injected). This is the contract the Cypher signal queries (Task 4) feed.

**Files:**
- Create: `src/cobol_modernizer/seam/scoring.py`
- Test: append to `tests/unit/test_seam_scoring.py`

Steps:
- [ ] Append failing tests to `tests/unit/test_seam_scoring.py`:
  ```python
  from cobol_modernizer.seam.scoring import WEIGHTS, clamp01, score_signals
  from cobol_modernizer.seam.schema import SeamSignals

  def test_weights_match_master_plan():
      assert WEIGHTS == {"business": 0.25, "isolation": 0.20, "testability": 0.20,
                         "data_ownership": 0.20, "risk": -0.15}

  def test_clamp01():
      assert clamp01(1.4) == 1.0 and clamp01(-0.2) == 0.0 and clamp01(0.5) == 0.5

  def test_reader_only_outranks_writer():
      reader = SeamSignals(business=0.7, isolation=0.9, testability=0.9,
                           data_ownership=0.8, risk=0.1)
      writer = SeamSignals(business=0.7, isolation=0.3, testability=0.3,
                           data_ownership=0.4, risk=0.9)
      assert score_signals(reader).weighted > score_signals(writer).weighted

  def test_known_value():
      s = SeamSignals(business=0.8, isolation=1.0, testability=1.0,
                      data_ownership=1.0, risk=0.0)
      # 0.25*0.8 + 0.20 + 0.20 + 0.20 - 0 = 0.80
      assert abs(score_signals(s).weighted - 0.80) < 1e-9
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring.py` — expected FAIL: `ImportError: cannot import name 'WEIGHTS'`.
- [ ] Create `src/cobol_modernizer/seam/scoring.py`:
  ```python
  from __future__ import annotations

  from cobol_modernizer.seam.schema import SeamScore, SeamSignals

  # Master plan §3 Phase 4 formula. risk subtracts.
  WEIGHTS: dict[str, float] = {
      "business": 0.25, "isolation": 0.20, "testability": 0.20,
      "data_ownership": 0.20, "risk": -0.15,
  }


  def clamp01(x: float) -> float:
      return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


  def score_signals(s: SeamSignals) -> SeamScore:
      normalized = {
          "business": clamp01(s.business), "isolation": clamp01(s.isolation),
          "testability": clamp01(s.testability),
          "data_ownership": clamp01(s.data_ownership), "risk": clamp01(s.risk),
      }
      weighted = sum(WEIGHTS[k] * v for k, v in normalized.items())
      return SeamScore(weighted=round(weighted, 6), normalized=normalized)
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring.py` — expected PASS (6 passed).
- [ ] Commit: `feat(seam): weighted seam score 0.25b+0.20i+0.20t+0.20d-0.15r over normalized signals`

---

## Task 4 — Cypher signal queries (`seam/signals.py`)

Translate each signal into **read-only Cypher aggregations over the v2 graph**. These are the queries that, on the real CardDemo graph, produce the raw `SeamSignals` for every Program. No LLM, no prompts — pure graph math (master plan §4.2). Unit-tested with a `FakeClient`; integration-tested against testcontainers Neo4j in Task 11.

**Files:**
- Create: `src/cobol_modernizer/seam/signals.py`
- Test: `tests/unit/test_seam_signals.py`

Signal definitions (each in [0,1] after normalization in `scoring.py`):
- **business** = normalized fan-in over CALLS(call) + 1 if reachable from an entry point (max-normalized across repo).
- **isolation** = `1 - sharedResources/touchedResources` where sharedResources = resources also touched by another program.
- **testability** = `reader_only ? 1.0 : 0.4` minus a control-flow-complexity penalty (`GO_TO` count, capped).
- **data_ownership** = `exclusivelyOwnedResources / touchedResources` (resource touched by no other program).
- **risk** = `(isWriter?0.5:0) + (touchesBillingOrAudit?0.3:0) + churnNorm*0.2`.

Steps:
- [ ] Write failing test `tests/unit/test_seam_signals.py`:
  ```python
  from cobol_modernizer.seam.signals import raw_signals_for_program

  class FakeClient:
      def __init__(self, mapping): self.mapping = mapping
      def run(self, query, **params):
          for key, rows in self.mapping.items():
              if key in query:
                  return rows
          return []

  def test_reader_only_program_signals():
      client = FakeClient({
          "// fan_in":            [{"fan_in": 2, "is_entry": True}],
          "// max_fan_in":        [{"max_fan_in": 4}],
          "// touched_resources": [{"resource": "ACCTFILE", "intent": "read", "shared": True, "exclusive": False},
                                   {"resource": "CUSTFILE", "intent": "read", "shared": False, "exclusive": True}],
          "// goto_count":        [{"goto_count": 0}],
          "// billing_audit":     [{"hits": 0}],
          "// churn":             [{"churn": 0, "max_churn": 10}],
      })
      sig = raw_signals_for_program(client, repo="cardemo", program="COACTVWC")
      assert sig.risk == 0.0                 # reader, no billing, no churn
      assert sig.testability == 1.0          # reader_only, goto=0
      assert 0.0 < sig.isolation < 1.0       # 1 shared of 2 touched -> 0.5
      assert sig.data_ownership == 0.5       # 1 exclusive of 2
      assert sig.business == 0.75            # (fan_in 2 / max 4)=0.5 + entry 0.25 cap -> 0.75

  def test_writer_program_has_risk():
      client = FakeClient({
          "// fan_in":            [{"fan_in": 0, "is_entry": False}],
          "// max_fan_in":        [{"max_fan_in": 4}],
          "// touched_resources": [{"resource": "ACCTFILE", "intent": "write", "shared": True, "exclusive": False}],
          "// goto_count":        [{"goto_count": 6}],
          "// billing_audit":     [{"hits": 1}],
          "// churn":             [{"churn": 10, "max_churn": 10}],
      })
      sig = raw_signals_for_program(client, repo="cardemo", program="CBTRN02C")
      assert sig.risk == 1.0                 # writer .5 + billing .3 + churn .2
      assert sig.testability < 0.4           # writer + goto penalty
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_signals.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/signals.py`:
  ```python
  from __future__ import annotations

  from typing import Any, Protocol

  from cobol_modernizer.seam.schema import SeamSignals


  class GraphClient(Protocol):
      def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


  _FAN_IN = """
  // fan_in
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
  WHERE p.qualified_name = $program OR p.simple_name = $program
  OPTIONAL MATCH (caller:CodeEntity {repo: $repo})-[c:CALLS]->(p)
  WHERE coalesce(c.type, 'call') = 'call'
  OPTIONAL MATCH (p)<-[:CALLS]-(:CodeEntity)<-[:CALLS*0..]-(ep:CodeEntity {repo: $repo})
  WITH p, count(DISTINCT caller) AS fan_in,
       exists((p)<-[:CALLS*0..]-(:CodeEntity {repo: $repo, is_external: true})) AS is_entry
  RETURN fan_in, is_entry
  """

  _MAX_FAN_IN = """
  // max_fan_in
  MATCH (:CodeEntity {repo: $repo})-[c:CALLS]->(p:CodeEntity {repo: $repo, kind: 'Program'})
  WHERE coalesce(c.type,'call') = 'call'
  WITH p, count(*) AS fi RETURN coalesce(max(fi), 1) AS max_fan_in
  """

  _TOUCHED_RESOURCES = """
  // touched_resources
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
  WHERE p.qualified_name = $program OR p.simple_name = $program
  WITH res, collect(DISTINCT CASE type(r) WHEN 'WRITES' THEN 'write'
                    WHEN 'READS' THEN 'read' ELSE coalesce(r.intent,'read') END) AS intents
  OPTIONAL MATCH (other:CodeEntity {repo: $repo, kind: 'Program'})-[:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
  WHERE NOT (other.qualified_name = $program OR other.simple_name = $program)
  WITH res, intents, count(DISTINCT other) AS others
  RETURN res.simple_name AS resource,
         CASE WHEN 'write' IN intents THEN 'write' ELSE 'read' END AS intent,
         others > 0 AS shared, others = 0 AS exclusive
  """

  _GOTO_COUNT = """
  // goto_count
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[:CONTAINS*1..2]->(para:CodeEntity)
  WHERE p.qualified_name = $program OR p.simple_name = $program
  OPTIONAL MATCH (para)-[g:GO_TO]->(:CodeEntity)
  RETURN count(g) AS goto_count
  """

  _BILLING_AUDIT = """
  // billing_audit
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
  WHERE (p.qualified_name = $program OR p.simple_name = $program)
    AND any(m IN ['BILL','AUDIT','TRAN','LEDGER','BAL','POST'] WHERE toUpper(res.simple_name) CONTAINS m)
  RETURN count(res) AS hits
  """

  _CHURN = """
  // churn
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
  WHERE p.qualified_name = $program OR p.simple_name = $program
  OPTIONAL MATCH (p)-[cc:CO_CHANGED_WITH]-(:CodeEntity)
  WITH coalesce(sum(cc.times), 0) AS churn
  MATCH (q:CodeEntity {repo: $repo, kind: 'Program'})
  OPTIONAL MATCH (q)-[cc2:CO_CHANGED_WITH]-(:CodeEntity)
  WITH churn, q, coalesce(sum(cc2.times),0) AS c2
  RETURN churn, coalesce(max(c2), 1) AS max_churn
  """


  def _one(rows: list[dict], key: str, default: Any = 0) -> Any:
      return rows[0].get(key, default) if rows else default


  def raw_signals_for_program(client: GraphClient, *, repo: str, program: str) -> SeamSignals:
      fi_rows = client.run(_FAN_IN, repo=repo, program=program)
      fan_in = float(_one(fi_rows, "fan_in", 0))
      is_entry = bool(_one(fi_rows, "is_entry", False))
      max_fan_in = float(_one(client.run(_MAX_FAN_IN, repo=repo), "max_fan_in", 1)) or 1.0

      touched = client.run(_TOUCHED_RESOURCES, repo=repo, program=program)
      n_touched = len(touched) or 1
      n_shared = sum(1 for t in touched if t.get("shared"))
      n_exclusive = sum(1 for t in touched if t.get("exclusive"))
      is_writer = any(t.get("intent") == "write" for t in touched)
      reader_only = (not is_writer) and len(touched) > 0

      goto = float(_one(client.run(_GOTO_COUNT, repo=repo, program=program), "goto_count", 0))
      billing = float(_one(client.run(_BILLING_AUDIT, repo=repo, program=program), "hits", 0))
      churn_rows = client.run(_CHURN, repo=repo, program=program)
      churn = float(_one(churn_rows, "churn", 0))
      max_churn = float(_one(churn_rows, "max_churn", 1)) or 1.0

      business = min(fan_in / max_fan_in, 1.0) * 0.75 + (0.25 if is_entry else 0.0)
      isolation = 1.0 - (n_shared / n_touched) if touched else 1.0
      testability = (1.0 if reader_only else 0.4) - min(goto / 10.0, 0.4)
      data_ownership = n_exclusive / n_touched if touched else 0.0
      risk = (0.5 if is_writer else 0.0) + (0.3 if billing > 0 else 0.0) \
             + 0.2 * min(churn / max_churn, 1.0)

      return SeamSignals(business=round(business, 6), isolation=round(isolation, 6),
                         testability=round(testability, 6),
                         data_ownership=round(data_ownership, 6), risk=round(risk, 6))
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_signals.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): read-only Cypher signal queries (business/isolation/testability/ownership/risk)`

---

## Task 5 — Seam-type classification + transition-pattern mapping (`seam/transition.py`)

Deterministic mapping from a program's access profile to its `SeamType`, then to the master-plan transition pattern:
- **Batch IO → Spring Batch adapter** (`batch_io`): sequential file IO, not CICS, batch program.
- **API/CICS → facade routed by transaction id** (`cics_api`): has `EXECUTES_CICS` edges.
- **DB reader → CDC** (`db_reader`): reader-only data access (no CICS).
- **DB writer → Extract Product Lines + ACL** (`db_writer`): writer data access.
- **Copybook → canonical DTO + anti-corruption layer** (`copybook`): the entity is a Copybook node imported by ≥2 programs.

**Files:**
- Create: `src/cobol_modernizer/seam/transition.py`
- Test: `tests/unit/test_transition_pattern.py`

Steps:
- [ ] Write failing test `tests/unit/test_transition_pattern.py`:
  ```python
  from cobol_modernizer.seam.transition import classify_seam_type, transition_for
  from cobol_modernizer.seam.schema import SeamType

  def test_cics_program_is_cics_api():
      profile = {"has_cics": True, "is_writer": False, "is_copybook": False,
                 "is_batch_io": False, "reader_only": True}
      assert classify_seam_type(profile) is SeamType.cics_api
      assert transition_for(SeamType.cics_api).name == "facade_routed_by_txn_id"

  def test_writer_is_db_writer_with_acl():
      profile = {"has_cics": False, "is_writer": True, "is_copybook": False,
                 "is_batch_io": False, "reader_only": False}
      assert classify_seam_type(profile) is SeamType.db_writer
      assert "anti-corruption" in transition_for(SeamType.db_writer).summary.lower()

  def test_reader_is_db_reader_cdc():
      profile = {"has_cics": False, "is_writer": False, "is_copybook": False,
                 "is_batch_io": False, "reader_only": True}
      assert classify_seam_type(profile) is SeamType.db_reader
      assert transition_for(SeamType.db_reader).name == "cdc_or_read_replica"

  def test_batch_io_is_spring_batch():
      profile = {"has_cics": False, "is_writer": False, "is_copybook": False,
                 "is_batch_io": True, "reader_only": True}
      assert classify_seam_type(profile) is SeamType.batch_io
      assert transition_for(SeamType.batch_io).name == "spring_batch_adapter"

  def test_copybook_is_canonical_dto():
      profile = {"has_cics": False, "is_writer": False, "is_copybook": True,
                 "is_batch_io": False, "reader_only": False}
      assert classify_seam_type(profile) is SeamType.copybook
      assert transition_for(SeamType.copybook).name == "canonical_dto_acl"
  ```
- [ ] Run `uv run pytest tests/unit/test_transition_pattern.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/transition.py`:
  ```python
  from __future__ import annotations

  from cobol_modernizer.seam.schema import SeamType, TransitionPattern

  _PATTERNS: dict[SeamType, TransitionPattern] = {
      SeamType.batch_io: TransitionPattern(
          name="spring_batch_adapter",
          summary="Wrap the sequential file-IO batch step in a Spring Batch adapter "
                  "(reader/processor/writer); keep the COBOL file format via an ItemReader."),
      SeamType.cics_api: TransitionPattern(
          name="facade_routed_by_txn_id",
          summary="Front the CICS transaction with a facade routed by transaction id; "
                  "dark-launch the Spring service behind the same txn id."),
      SeamType.db_reader: TransitionPattern(
          name="cdc_or_read_replica",
          summary="Read-only access: feed the new service via Change Data Capture or a "
                  "read replica; no write-back, lowest blast radius."),
      SeamType.db_writer: TransitionPattern(
          name="extract_product_lines_acl",
          summary="Writer: apply Extract Product Lines and front the legacy store with an "
                  "anti-corruption layer; keep writes single-system until fully extracted."),
      SeamType.copybook: TransitionPattern(
          name="canonical_dto_acl",
          summary="Shared copybook: promote to a canonical DTO with an anti-corruption "
                  "layer translating to/from the legacy record layout."),
  }


  def classify_seam_type(profile: dict) -> SeamType:
      # Precedence: copybook node > CICS surface > writer > batch IO > db reader.
      if profile.get("is_copybook"):
          return SeamType.copybook
      if profile.get("has_cics"):
          return SeamType.cics_api
      if profile.get("is_writer"):
          return SeamType.db_writer
      if profile.get("is_batch_io"):
          return SeamType.batch_io
      return SeamType.db_reader


  def transition_for(seam_type: SeamType) -> TransitionPattern:
      return _PATTERNS[seam_type]
  ```
- [ ] Run `uv run pytest tests/unit/test_transition_pattern.py` — expected PASS (5 passed).
- [ ] Commit: `feat(seam): seam-type classification + transition-pattern mapping (5 types)`

---

## Task 6 — Dead-paragraph detection (`seam/deadcode.py`)

Accidental-behavior lens, part 1. A paragraph is **dead** if it is unreachable from the program entry via `CALLS(type='perform')` and `GO_TO` edges. Cypher reachability; deterministic. Enforces "required vs accidental" — dead paragraphs are excluded from the migrated behavior contract.

**Files:**
- Create: `src/cobol_modernizer/seam/deadcode.py`
- Test: `tests/unit/test_deadcode.py`

Steps:
- [ ] Write failing test `tests/unit/test_deadcode.py`:
  ```python
  from cobol_modernizer.seam.deadcode import dead_paragraphs

  class FakeClient:
      def __init__(self, rows): self.rows = rows
      def run(self, query, **params): return self.rows

  def test_unreachable_paragraph_flagged():
      # 1000-MAIN reaches 2000-READ; 9999-ORPHAN is never performed/gone-to.
      client = FakeClient([{"paragraph": "CBACT01C.9999-ORPHAN"}])
      assert dead_paragraphs(client, repo="cardemo", program="CBACT01C") == \
          ["CBACT01C.9999-ORPHAN"]

  def test_no_dead_paragraphs():
      client = FakeClient([])
      assert dead_paragraphs(client, repo="cardemo", program="CBACT01C") == []
  ```
- [ ] Run `uv run pytest tests/unit/test_deadcode.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/deadcode.py`:
  ```python
  from __future__ import annotations

  from typing import Any, Protocol


  class GraphClient(Protocol):
      def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


  # A paragraph is dead if (a) it belongs to the program, (b) it is NOT the entry
  # paragraph, and (c) it is unreachable from the entry via PERFORM(CALLS type=perform)
  # or GO_TO edges. Read-only.
  _DEAD_PARAGRAPHS = """
  MATCH (prog:CodeEntity {repo: $repo, kind: 'Program'})
  WHERE prog.qualified_name = $program OR prog.simple_name = $program
  MATCH (prog)-[:CONTAINS*1..2]->(para:CodeEntity {repo: $repo, kind: 'Paragraph'})
  WITH prog, collect(DISTINCT para) AS paras
  // entry = first paragraph by start_line
  WITH prog, paras, head([p IN apoc.coll.sortNodes(paras, '^start_line') ]) AS entry
  UNWIND paras AS para
  WITH prog, entry, para
  WHERE para <> entry
    AND NOT exists(
      (entry)-[:CALLS|GO_TO*1..50]->(para)
    )
  RETURN DISTINCT para.qualified_name AS paragraph
  ORDER BY paragraph
  """

  # APOC-free fallback (no apoc.coll): entry = paragraph with min start_line via subquery.
  _DEAD_PARAGRAPHS_NO_APOC = """
  MATCH (prog:CodeEntity {repo: $repo, kind: 'Program'})
  WHERE prog.qualified_name = $program OR prog.simple_name = $program
  MATCH (prog)-[:CONTAINS*1..2]->(entry:CodeEntity {repo: $repo, kind: 'Paragraph'})
  WITH prog, entry ORDER BY entry.start_line LIMIT 1
  MATCH (prog)-[:CONTAINS*1..2]->(para:CodeEntity {repo: $repo, kind: 'Paragraph'})
  WHERE para <> entry
    AND NOT exists((entry)-[:CALLS|GO_TO*1..50]->(para))
  RETURN DISTINCT para.qualified_name AS paragraph
  ORDER BY paragraph
  """


  def dead_paragraphs(client: GraphClient, *, repo: str, program: str) -> list[str]:
      rows = client.run(_DEAD_PARAGRAPHS_NO_APOC, repo=repo, program=program)
      return [r["paragraph"] for r in rows if r.get("paragraph")]
  ```
- [ ] Run `uv run pytest tests/unit/test_deadcode.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): dead-paragraph detection (unreachable via PERFORM/GO_TO)`

---

## Task 7 — Capability-level duplicate detection (`seam/dedup.py`)

Accidental-behavior lens, part 2. Two programs/paragraphs implement a **duplicate capability** when their **capability fingerprint** matches. The fingerprint is the sorted set of `(resource, intent)` data-access pairs plus the set of called external programs — a behavior signature independent of variable names. Clusters of size ≥2 are duplicates; the canonical implementation should be migrated once (e.g. `CSUTLDTC` date-validation duplicated into `COACTUPC`/`CORPT00C`/`COTRN02C`).

**Files:**
- Create: `src/cobol_modernizer/seam/dedup.py`
- Test: `tests/unit/test_dedup.py`

Steps:
- [ ] Write failing test `tests/unit/test_dedup.py`:
  ```python
  from cobol_modernizer.seam.dedup import capability_fingerprint, duplicate_capabilities

  def test_fingerprint_is_name_independent():
      a = {"accesses": [("CSUTLDTC", "call")], "data": [("WS-DATE", "read")]}
      b = {"accesses": [("CSUTLDTC", "call")], "data": [("WS-DT", "read")]}  # diff data name
      # capability fingerprint keys on external calls + resource intents, not local vars
      fa = capability_fingerprint(a, key="accesses")
      fb = capability_fingerprint(b, key="accesses")
      assert fa == fb

  def test_clusters_duplicate_validators():
      profiles = {
          "COACTUPC": {"accesses": [("CSUTLDTC", "call")]},
          "CORPT00C": {"accesses": [("CSUTLDTC", "call")]},
          "COTRN02C": {"accesses": [("CSUTLDTC", "call")]},
          "COSGN00C": {"accesses": [("COMEN01C", "call")]},  # different capability
      }
      clusters = duplicate_capabilities(profiles, key="accesses")
      assert sorted(clusters[0]) == ["COACTUPC", "CORPT00C", "COTRN02C"]
      assert len(clusters) == 1  # the singleton COSGN00C is not a duplicate cluster
  ```
- [ ] Run `uv run pytest tests/unit/test_dedup.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/dedup.py`:
  ```python
  from __future__ import annotations

  from collections import defaultdict


  def capability_fingerprint(profile: dict, *, key: str) -> tuple:
      """Name-independent behavior signature: the sorted set of (target, intent) pairs
      under `key` (e.g. external CALLs, resource accesses). Local variable names are
      intentionally excluded so duplicate logic with different names still matches."""
      pairs = profile.get(key, [])
      return tuple(sorted({(str(t), str(i)) for t, i in pairs}))


  def duplicate_capabilities(profiles: dict[str, dict], *, key: str) -> list[list[str]]:
      """Cluster programs sharing a capability fingerprint. Returns clusters of size >= 2,
      each a list of program names, ordered for determinism. Empty fingerprints are
      ignored (no signal)."""
      buckets: dict[tuple, list[str]] = defaultdict(list)
      for name, profile in profiles.items():
          fp = capability_fingerprint(profile, key=key)
          if fp:
              buckets[fp].append(name)
      clusters = [sorted(members) for members in buckets.values() if len(members) >= 2]
      return sorted(clusters)
  ```
- [ ] Run `uv run pytest tests/unit/test_dedup.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): capability-level duplicate detection (name-independent fingerprint)`

---

## Task 8 — Seam-rationale agent with groundedness gate (`seam/rationale.py`)

The **only** LLM in the seam pipeline. It writes a short rationale per seam **over the precomputed evidence**; it does **not** score. Reuses `SdkAgentRunner` (`tools=[]`, `setting_sources=[]`, `json_schema`) and the groundedness floor from `brd_judge.py`: any evidence ref the agent cites that is not in `graph_ops.known_refs(deps)` is dropped and the rationale is marked `grounded=False`. Model: `resolve_model("seam")` → Sonnet.

**Files:**
- Create: `src/cobol_modernizer/seam/rationale.py`
- Test: `tests/unit/test_seam_rationale.py`

Steps:
- [ ] Write failing test `tests/unit/test_seam_rationale.py`:
  ```python
  import pytest
  from cobol_modernizer.seam.rationale import awrite_rationale, RATIONALE_SCHEMA

  class FakeRunner:
      def __init__(self, payload): self.payload = payload
      async def run_structured(self, **kw):
          self.kw = kw
          return self.payload

  @pytest.mark.asyncio
  async def test_rationale_drops_hallucinated_refs():
      runner = FakeRunner({"rationale": "Reader-only, low blast radius.",
                           "cited_refs": ["COACTVWC", "GHOSTPGM"]})
      out = await awrite_rationale(
          program="COACTVWC",
          evidence={"isolation": ["COACTVWC"], "risk": ["COACTVWC"]},
          known_refs={"COACTVWC"}, runner=runner, model="claude-sonnet-4-6")
      assert out["grounded"] is False                      # GHOSTPGM not known
      assert out["cited_refs"] == ["COACTVWC"]             # hallucinated ref dropped
      assert "blast radius" in out["rationale"]
      # invariants: single turn, no server, json_schema schema passed through
      assert runner.kw["max_turns"] == 1 and runner.kw["server"] is None
      assert runner.kw["schema"] is RATIONALE_SCHEMA

  @pytest.mark.asyncio
  async def test_grounded_rationale_when_all_refs_known():
      runner = FakeRunner({"rationale": "ok", "cited_refs": ["COACTVWC"]})
      out = await awrite_rationale(program="COACTVWC", evidence={"isolation": ["COACTVWC"]},
                                   known_refs={"COACTVWC"}, runner=runner,
                                   model="claude-sonnet-4-6")
      assert out["grounded"] is True
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_rationale.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/rationale.py`:
  ```python
  from __future__ import annotations

  import json
  from typing import Any

  RATIONALE_SYSTEM = (
      "You explain WHY a precomputed seam ranking is what it is. You DO NOT score. "
      "Write a 1-2 sentence rationale grounded ONLY in the provided evidence refs. "
      "Cite the exact refs you used in 'cited_refs'. Do not invent identifiers. "
      'Return JSON: {"rationale": str, "cited_refs": [str]}.'
  )

  RATIONALE_SCHEMA: dict[str, Any] = {
      "type": "object",
      "properties": {
          "rationale": {"type": "string"},
          "cited_refs": {"type": "array", "items": {"type": "string"}},
      },
      "required": ["rationale", "cited_refs"],
  }


  async def awrite_rationale(*, program: str, evidence: dict[str, list[str]],
                             known_refs: set[str], runner, model: str) -> dict[str, Any]:
      prompt = (f"## Seam: {program}\n## Precomputed evidence (signal -> refs)\n"
                f"```json\n{json.dumps(evidence)}\n```\n"
                "Explain the ranking using only these refs.")
      raw = await runner.run_structured(
          system=RATIONALE_SYSTEM, prompt=prompt, server=None, allowed_tools=[],
          model=model, max_turns=1, schema=RATIONALE_SCHEMA)
      cited = [r for r in raw.get("cited_refs", []) if isinstance(r, str)]
      grounded_refs = [r for r in cited if r in known_refs]
      return {
          "rationale": raw.get("rationale", ""),
          "cited_refs": grounded_refs,
          "grounded": len(grounded_refs) == len(cited) and len(cited) > 0,
      }
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_rationale.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): groundedness-gated rationale agent (writes WHY, never scores)`

---

## Task 9 — Story planner: DAG + acyclic gate (`planner/schema.py`, `planner/dag.py`)

INVEST-judged stories form an **acyclic** delivery DAG. Acyclicity is enforced **deterministically in Python** (Kahn topological sort) — never trusted from the LLM. A cycle is a hard gate failure.

**Files:**
- Create: `src/cobol_modernizer/planner/__init__.py`
- Create: `src/cobol_modernizer/planner/schema.py`
- Create: `src/cobol_modernizer/planner/dag.py`
- Test: `tests/unit/test_story_dag.py`

Steps:
- [ ] Write failing test `tests/unit/test_story_dag.py`:
  ```python
  import pytest
  from cobol_modernizer.planner.schema import Story, StoryDAG
  from cobol_modernizer.planner.dag import topo_order, is_acyclic, CycleError

  def _dag():
      return StoryDAG(repo_id="cardemo", stories=[
          Story(id="S1", title="Account view read path", seam="COACTVWC", depends_on=[]),
          Story(id="S2", title="Card xref ACL", seam="COCRDSLC", depends_on=["S1"]),
          Story(id="S3", title="Txn poster writer", seam="CBTRN02C", depends_on=["S1", "S2"]),
      ])

  def test_acyclic_topo_order():
      order = topo_order(_dag())
      assert order.index("S1") < order.index("S2") < order.index("S3")
      assert is_acyclic(_dag()) is True

  def test_cycle_rejected():
      bad = StoryDAG(repo_id="cardemo", stories=[
          Story(id="A", title="a", seam="X", depends_on=["B"]),
          Story(id="B", title="b", seam="Y", depends_on=["A"]),
      ])
      assert is_acyclic(bad) is False
      with pytest.raises(CycleError):
          topo_order(bad)

  def test_unknown_dependency_rejected():
      bad = StoryDAG(repo_id="cardemo", stories=[
          Story(id="A", title="a", seam="X", depends_on=["GHOST"]),
      ])
      with pytest.raises(CycleError, match="unknown"):
          topo_order(bad)
  ```
- [ ] Run `uv run pytest tests/unit/test_story_dag.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/planner/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/planner/schema.py`:
  ```python
  from __future__ import annotations

  from pydantic import BaseModel, Field

  EvidenceMap = dict[str, list[str]]


  class InvestScore(BaseModel):
      independent: int = Field(ge=1, le=5)
      negotiable: int = Field(ge=1, le=5)
      valuable: int = Field(ge=1, le=5)
      estimable: int = Field(ge=1, le=5)
      small: int = Field(ge=1, le=5)
      testable: int = Field(ge=1, le=5)


  class Story(BaseModel):
      id: str
      title: str
      seam: str                       # the seam (program) this story migrates
      depends_on: list[str] = Field(default_factory=list)
      invest: InvestScore | None = None
      evidence_map: EvidenceMap = Field(default_factory=dict)


  class StoryDAG(BaseModel):
      repo_id: str
      stories: list[Story]
  ```
- [ ] Create `src/cobol_modernizer/planner/dag.py`:
  ```python
  from __future__ import annotations

  from collections import deque

  from cobol_modernizer.planner.schema import StoryDAG


  class CycleError(Exception):
      """Raised when the story dependency graph is not acyclic, or references an
      unknown story id. A cycle is a hard gate failure."""


  def topo_order(dag: StoryDAG) -> list[str]:
      ids = {s.id for s in dag.stories}
      indeg: dict[str, int] = {s.id: 0 for s in dag.stories}
      adj: dict[str, list[str]] = {s.id: [] for s in dag.stories}
      for s in dag.stories:
          for dep in s.depends_on:
              if dep not in ids:
                  raise CycleError(f"story {s.id!r} depends on unknown story {dep!r}")
              adj[dep].append(s.id)
              indeg[s.id] += 1
      queue = deque(sorted(i for i, d in indeg.items() if d == 0))
      order: list[str] = []
      while queue:
          n = queue.popleft()
          order.append(n)
          for m in sorted(adj[n]):
              indeg[m] -= 1
              if indeg[m] == 0:
                  queue.append(m)
      if len(order) != len(dag.stories):
          remaining = sorted(i for i in indeg if i not in order)
          raise CycleError(f"story DAG has a cycle among: {remaining}")
      return order


  def is_acyclic(dag: StoryDAG) -> bool:
      try:
          topo_order(dag)
          return True
      except CycleError:
          return False
  ```
- [ ] Run `uv run pytest tests/unit/test_story_dag.py` — expected PASS (3 passed).
- [ ] Commit: `feat(planner): story DAG + deterministic Kahn acyclic gate`

---

## Task 10 — INVEST judge with groundedness floor (`planner/invest.py`)

The story-split agent (`resolve_model("story")` → Sonnet) proposes INVEST scores; the judge reuses the groundedness floor (any seam ref not in `known_refs` floors `valuable`/`estimable`) and a deterministic pass threshold. The acyclic check (Task 9) gates the whole DAG.

**Files:**
- Create: `src/cobol_modernizer/planner/invest.py`
- Test: `tests/unit/test_invest_judge.py`

Steps:
- [ ] Write failing test `tests/unit/test_invest_judge.py`:
  ```python
  import pytest
  from cobol_modernizer.planner.invest import judge_story, INVEST_SCHEMA
  from cobol_modernizer.planner.schema import Story

  class FakeRunner:
      def __init__(self, payload): self.payload = payload
      async def run_structured(self, **kw):
          self.kw = kw
          return self.payload

  @pytest.mark.asyncio
  async def test_invest_pass():
      runner = FakeRunner({"independent":4,"negotiable":4,"valuable":5,
                           "estimable":4,"small":4,"testable":5})
      story = Story(id="S1", title="Account view", seam="COACTVWC",
                    evidence_map={"seam": ["COACTVWC"]})
      report = await judge_story(story, known_refs={"COACTVWC"}, runner=runner,
                                 model="claude-sonnet-4-6")
      assert report["passed"] is True
      assert runner.kw["schema"] is INVEST_SCHEMA and runner.kw["server"] is None

  @pytest.mark.asyncio
  async def test_hallucinated_seam_floors_score_and_fails():
      runner = FakeRunner({"independent":5,"negotiable":5,"valuable":5,
                           "estimable":5,"small":5,"testable":5})
      story = Story(id="S9", title="ghost", seam="GHOSTPGM",
                    evidence_map={"seam": ["GHOSTPGM"]})
      report = await judge_story(story, known_refs={"COACTVWC"}, runner=runner,
                                 model="claude-sonnet-4-6")
      assert report["groundedness_failures"] == ["GHOSTPGM"]
      assert report["invest"]["valuable"] == 2      # floored
      assert report["passed"] is False
  ```
- [ ] Run `uv run pytest tests/unit/test_invest_judge.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/planner/invest.py`:
  ```python
  from __future__ import annotations

  import json
  from typing import Any

  INVEST_SYSTEM = (
      "Score this migration story on the six INVEST dimensions 1-5: independent, "
      "negotiable, valuable, estimable, small, testable. Base 'valuable'/'estimable' "
      "ONLY on the cited seam evidence. "
      'Return JSON: {"independent","negotiable","valuable","estimable","small","testable"}.'
  )

  INVEST_SCHEMA: dict[str, Any] = {
      "type": "object",
      "properties": {d: {"type": "integer"} for d in
                     ("independent", "negotiable", "valuable", "estimable", "small", "testable")},
      "required": ["independent", "negotiable", "valuable", "estimable", "small", "testable"],
  }

  _DIMS = ("independent", "negotiable", "valuable", "estimable", "small", "testable")
  _PASS_MIN = 3   # every dimension must be >= 3 to pass


  async def judge_story(story, *, known_refs: set[str], runner, model: str) -> dict[str, Any]:
      refs = [r for refs in story.evidence_map.values() for r in refs]
      failures = sorted({r for r in refs if r not in known_refs})

      raw = await runner.run_structured(
          system=INVEST_SYSTEM,
          prompt=f"## Story\n```json\n{story.model_dump_json()}\n```",
          server=None, allowed_tools=[], model=model, max_turns=1, schema=INVEST_SCHEMA)

      invest = {d: int(raw.get(d, 3)) for d in _DIMS}
      if failures:                       # groundedness floor: ungrounded value/estimate
          invest["valuable"] = min(invest["valuable"], 2)
          invest["estimable"] = min(invest["estimable"], 2)
      passed = not failures and all(v >= _PASS_MIN for v in invest.values())
      return {"invest": invest, "groundedness_failures": failures, "passed": passed}
  ```
- [ ] Run `uv run pytest tests/unit/test_invest_judge.py` — expected PASS (2 passed).
- [ ] Commit: `feat(planner): INVEST judge with groundedness floor + deterministic pass gate`

---

## Task 11 — v2 MCP graph ops + tools (read-only) (`agent/graph_ops.py`, `agent/graph_tools.py`)

Expose the precomputed seam evidence to bounded agents via the **read-only** MCP surface reserved in Foundation §5: `data_accesses`, `reader_writer_classification`, `seam_candidates`. Seam math stays in `seam/*`; these ops only surface it. Extend `GRAPH_TOOL_NAMES` and the `neighbors` edge enum.

**Files:**
- Modify: `src/cobol_modernizer/agent/graph_ops.py`
- Modify: `src/cobol_modernizer/agent/graph_tools.py`
- Test: `tests/integration/test_seam_candidates_tool.py`

Steps:
- [ ] Write failing test `tests/integration/test_seam_candidates_tool.py`:
  ```python
  import json
  import pytest
  from cobol_modernizer.agent.deps import GraphDeps
  from cobol_modernizer.agent import graph_tools as gt
  from cobol_modernizer.agent import graph_ops as ops

  class FakeClient:
      def __init__(self, rows_by_key): self.rows_by_key = rows_by_key
      def run(self, query, **params):
          for key, rows in self.rows_by_key.items():
              if key in query:
                  return rows
          return []

  def test_seam_candidates_tool_is_registered_and_readonly():
      assert "mcp__graph__seam_candidates" in gt.GRAPH_TOOL_NAMES
      assert "mcp__graph__reader_writer_classification" in gt.GRAPH_TOOL_NAMES
      assert "mcp__graph__data_accesses" in gt.GRAPH_TOOL_NAMES

  def test_neighbors_edge_enum_extended_for_v2():
      # v2 IO/control-flow edges are traversable by the read-only neighbors tool.
      for e in ("READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"):
          assert e in ops._EDGES

  def test_data_accesses_op_returns_normalized_rows():
      client = FakeClient({"accesses_for_program": [
          {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
      ]})
      deps = GraphDeps(client=client, repo_id="cardemo", repo_path=None)
      out = ops.data_accesses(deps, "COACTVWC")
      assert out["accesses"][0]["resource"] == "ACCTFILE"
      assert out["accesses"][0]["intent"] == "read"
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_candidates_tool.py` — expected FAIL (ops lack v2 functions; tool names not registered).
- [ ] In `agent/graph_ops.py`, extend `_EDGES` and add the three v2 ops (delegating to `seam/*`):
  ```python
  # extend the traversal whitelist with v2 IO / data-flow / control-flow edges
  _EDGES = {"CALLS", "IMPORTS", "CONTAINS", "INHERITS", "DECORATES", "RAISES",
            "READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"}

  def data_accesses(deps, name, *, intent=None, limit=50):
      from cobol_modernizer.seam.reader_writer import classify_program
      cls = classify_program(deps.client, repo=deps.repo_id, program=name)
      acc = ([{"resource": r, "intent": "read"} for r in cls["reads"]]
             + [{"resource": w, "intent": "write"} for w in cls["writes"]])
      if intent:
          acc = [a for a in acc if a["intent"] == intent]
      return {"program": name, "accesses": acc[:limit]}

  def reader_writer_classification(deps, resource):
      from cobol_modernizer.seam.reader_writer import classify_resource
      readers = classify_resource(deps.client, repo=deps.repo_id, resource=resource)["readers"]
      writers = deps.client.run(
          """MATCH (p:CodeEntity {repo:$repo, kind:'Program'})-[r:WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
             WHERE res.simple_name = $resource
               AND (type(r)='WRITES' OR coalesce(r.intent,'read')='write')
             RETURN DISTINCT p.simple_name AS writer""",
          repo=deps.repo_id, resource=resource)
      return {"resource": resource, "readers": readers,
              "writers": sorted({w["writer"] for w in writers})}

  def seam_candidates(deps, *, limit=20):
      from cobol_modernizer.seam.service import rank_candidates
      ranked = rank_candidates(deps.client, repo=deps.repo_id, limit=limit)
      return {"seam_candidates": ranked}
  ```
- [ ] In `agent/graph_tools.py`, register the three tools (all `_READ_ONLY`) and extend `GRAPH_TOOL_NAMES`:
  ```python
  GRAPH_TOOL_NAMES = [f"mcp__{SERVER_NAME}__{n}" for n in (
      "list_subsystems", "get_entity", "find_entities", "neighbors",
      "get_source_slice", "entry_points", "integration_points", "graph_summary",
      "data_accesses", "reader_writer_classification", "seam_candidates",
  )]
  # ... inside _make_handlers, add:
  #   async def data_accesses(args):
  #       return _ok(ops.data_accesses(deps, args["name"], intent=args.get("intent"),
  #                                    limit=int(args.get("limit", 50))))
  #   async def reader_writer_classification(args):
  #       return _ok(ops.reader_writer_classification(deps, args["resource"]))
  #   async def seam_candidates(args):
  #       return _ok(ops.seam_candidates(deps, limit=int(args.get("limit", 20))))
  # ... inside build_graph_server tools list, append three tool(...) registrations
  #     with annotations=_READ_ONLY, schemas:
  #       data_accesses {"name": str, "intent": str, "limit": int}
  #       reader_writer_classification {"resource": str}
  #       seam_candidates {"limit": int}
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_candidates_tool.py` — expected PASS (3 passed).
- [ ] Commit: `feat(agent): v2 read-only MCP tools data_accesses/reader_writer/seam_candidates`

---

## Task 12 — SeamEngine facade + persistence (`seam/service.py`)

Orchestrates: for every Program → signals (Task 4) → score (Task 3) → seam-type + transition (Task 5) → identity-drift flag (Task 2) → dead paragraphs (Task 6); cluster duplicates (Task 7); rank desc; attach groundedness-gated rationale (Task 8); persist `artifact(kind='seam_set')` + `gate(gate_key='seams')`. `rank_candidates` (used by the MCP tool) is the LLM-free ranking core.

**Files:**
- Create: `src/cobol_modernizer/seam/service.py`
- Test: `tests/integration/test_seam_engine_e2e.py`

Steps:
- [ ] Write failing test `tests/integration/test_seam_engine_e2e.py` (FakeClient seeded to mimic the v2 CardDemo subgraph; no Neo4j, no LLM — rationale runner is a stub):
  ```python
  import pytest
  from cobol_modernizer.seam.service import rank_candidates, build_seam_set
  from cobol_modernizer.seam.schema import SeamType

  class FakeClient:
      """Routes by Cypher comment markers; per-program params honored."""
      def __init__(self, programs, accesses, readers, gotos, calls):
          self.programs, self.accesses = programs, accesses
          self.readers, self.gotos, self.calls = readers, gotos, calls
      def run(self, query, **p):
          prog = p.get("program"); repo = p.get("repo")
          if "RETURN p.simple_name AS program" in query or "all_programs" in query:
              return [{"program": x} for x in self.programs]
          if "accesses_for_program" in query or "touched_resources" in query:
              return self.accesses.get(prog, [])
          if "readers_of_resource" in query:
              return [{"reader": r} for r in self.readers.get(p.get("resource"), [])]
          if "// fan_in" in query:
              return [{"fan_in": self.calls.get(prog, 0), "is_entry": True}]
          if "// max_fan_in" in query:
              return [{"max_fan_in": max(self.calls.values() or [1])}]
          if "// goto_count" in query:
              return [{"goto_count": self.gotos.get(prog, 0)}]
          if "// billing_audit" in query:
              return [{"hits": 1 if any('TRAN' in a.get('resource','')
                                        for a in self.accesses.get(prog, [])) else 0}]
          if "// churn" in query:
              return [{"churn": 0, "max_churn": 1}]
          if "NO_APOC" in query or "dead" in query.lower():
              return []
          return []

  def _client():
      return FakeClient(
          programs=["COACTVWC", "CBTRN02C"],
          accesses={
              # touched_resources rows: resource/intent/shared/exclusive
              "COACTVWC": [{"resource": "ACCTFILE", "intent": "read", "shared": True, "exclusive": False},
                           {"resource": "CUSTFILE", "intent": "read", "shared": False, "exclusive": True}],
              "CBTRN02C": [{"resource": "ACCTFILE", "intent": "write", "shared": True, "exclusive": False},
                           {"resource": "TRANSACT", "intent": "write", "shared": False, "exclusive": True}],
          },
          readers={"ACCTFILE": ["COACTVWC", "CBACT01C"], "TRANSACT": []},
          gotos={"CBTRN02C": 6},
          calls={"COACTVWC": 2, "CBTRN02C": 0},
      )

  def test_reader_outranks_writer_and_writer_flagged_single_system():
      ranked = rank_candidates(_client(), repo="cardemo", limit=10)
      names = [c["program"] for c in ranked]
      assert names[0] == "COACTVWC"                  # reader-only ranks first
      writer = next(c for c in ranked if c["program"] == "CBTRN02C")
      assert writer["identity_drift_writer"] is True  # writes ACCTFILE that others read
      assert writer["seam_type"] == SeamType.db_writer.value
      reader = next(c for c in ranked if c["program"] == "COACTVWC")
      assert reader["seam_type"] in (SeamType.db_reader.value, SeamType.cics_api.value)

  @pytest.mark.asyncio
  async def test_build_seam_set_attaches_grounded_rationale():
      class StubRunner:
          async def run_structured(self, **kw):
              return {"rationale": "reader-only", "cited_refs": ["COACTVWC"]}
      seam_set = await build_seam_set(
          _client(), repo="cardemo", known_refs={"COACTVWC", "CBTRN02C"},
          runner=StubRunner(), model="claude-sonnet-4-6", limit=10)
      top = seam_set.candidates[0]
      assert top.program == "COACTVWC" and top.rationale == "reader-only"
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_engine_e2e.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/seam/service.py`:
  ```python
  from __future__ import annotations

  from typing import Any, Protocol

  from cobol_modernizer.seam.deadcode import dead_paragraphs
  from cobol_modernizer.seam.reader_writer import (
      classify_program, is_identity_drift_writer,
  )
  from cobol_modernizer.seam.scoring import score_signals
  from cobol_modernizer.seam.signals import raw_signals_for_program
  from cobol_modernizer.seam.schema import (
      SeamCandidate, SeamSet, SeamType, TransitionPattern,
  )
  from cobol_modernizer.seam.transition import classify_seam_type, transition_for


  class GraphClient(Protocol):
      def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


  _ALL_PROGRAMS = """
  // all_programs
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
  RETURN p.simple_name AS program ORDER BY program
  """

  _HAS_CICS = """
  MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[:EXECUTES_CICS]->()
  WHERE p.simple_name = $program OR p.qualified_name = $program
  RETURN count(*) AS n
  """


  def _profile(client: GraphClient, repo: str, program: str) -> dict:
      cls = classify_program(client, repo=repo, program=program)
      has_cics = bool(client.run(_HAS_CICS, repo=repo, program=program)
                      and client.run(_HAS_CICS, repo=repo, program=program)[0].get("n", 0))
      is_writer = len(cls["writes"]) > 0
      is_batch_io = (not has_cics) and not is_writer and len(cls["reads"]) > 0
      return {"has_cics": has_cics, "is_writer": is_writer, "is_copybook": False,
              "is_batch_io": is_batch_io, "reader_only": cls["reader_only"]}


  def _candidate(client: GraphClient, repo: str, program: str) -> SeamCandidate:
      signals = raw_signals_for_program(client, repo=repo, program=program)
      score = score_signals(signals)
      profile = _profile(client, repo, program)
      seam_type = classify_seam_type(profile)
      transition = transition_for(seam_type)
      evidence = {
          "business": [program], "isolation": [program], "testability": [program],
          "data_ownership": [program], "risk": [program],
      }
      return SeamCandidate(
          program=program, seam_type=seam_type, signals=signals, score=score,
          transition=transition, evidence_map=evidence,
          identity_drift_writer=is_identity_drift_writer(client, repo=repo, program=program),
      )


  def rank_candidates(client: GraphClient, *, repo: str, limit: int = 20) -> list[dict]:
      """LLM-free ranked seam backlog (what the MCP seam_candidates tool returns)."""
      programs = [r["program"] for r in client.run(_ALL_PROGRAMS, repo=repo)
                  if r.get("program")]
      cands = [_candidate(client, repo, p) for p in programs]
      cands.sort(key=lambda c: c.score.weighted, reverse=True)
      return [c.model_dump(mode="json") for c in cands[:limit]]


  async def build_seam_set(client: GraphClient, *, repo: str, known_refs: set[str],
                           runner, model: str, limit: int = 20) -> SeamSet:
      from cobol_modernizer.seam.dedup import duplicate_capabilities
      from cobol_modernizer.seam.rationale import awrite_rationale

      programs = [r["program"] for r in client.run(_ALL_PROGRAMS, repo=repo)
                  if r.get("program")]
      cands = [_candidate(client, repo, p) for p in programs]
      cands.sort(key=lambda c: c.score.weighted, reverse=True)
      cands = cands[:limit]

      for c in cands:
          out = await awrite_rationale(program=c.program, evidence=c.evidence_map,
                                       known_refs=known_refs, runner=runner, model=model)
          c.rationale = out["rationale"]

      dead: list[str] = []
      for p in programs:
          dead.extend(dead_paragraphs(client, repo=repo, program=p))

      access_profiles = {
          p: {"accesses": [(a["resource"], a["intent"])
                           for a in client.run("accesses_for_program", repo=repo, program=p)]}
          for p in programs
      }
      dups = duplicate_capabilities(access_profiles, key="accesses")

      return SeamSet(repo_id=repo, candidates=cands,
                     duplicate_capabilities=dups, dead_paragraphs=sorted(set(dead)))
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_engine_e2e.py` — expected PASS (2 passed).
- [ ] Commit: `feat(seam): SeamEngine facade — ranked backlog + identity-drift + dups + dead paras`

---

## Task 13 — Story-DAG service + persistence (`planner/dependency.py`, `planner/service.py`)

Derive story dependency edges deterministically from the seam set (a writer-path story depends on the read-path stories of resources it shares), build the DAG, enforce acyclicity (hard gate), judge INVEST, and persist `artifact(kind='story_dag')` + `gate(gate_key='stories_dag', threshold={"acyclic": true})`.

**Files:**
- Create: `src/cobol_modernizer/planner/dependency.py`
- Create: `src/cobol_modernizer/planner/service.py`
- Test: `tests/unit/test_story_dependency.py`

Steps:
- [ ] Write failing test `tests/unit/test_story_dependency.py`:
  ```python
  from cobol_modernizer.planner.dependency import stories_from_seam_set, derive_dependencies
  from cobol_modernizer.planner.dag import is_acyclic

  def test_writer_story_depends_on_reader_of_shared_resource():
      # COACTVWC reads ACCTFILE; CBTRN02C writes ACCTFILE -> writer depends on reader.
      seam_candidates = [
          {"program": "COACTVWC", "reads": ["ACCTFILE"], "writes": [],
           "score": {"weighted": 0.8}},
          {"program": "CBTRN02C", "reads": [], "writes": ["ACCTFILE"],
           "score": {"weighted": 0.2}},
      ]
      stories = stories_from_seam_set(seam_candidates, repo_id="cardemo")
      dag = derive_dependencies(stories, seam_candidates)
      writer = next(s for s in dag.stories if s.seam == "CBTRN02C")
      reader = next(s for s in dag.stories if s.seam == "COACTVWC")
      assert reader.id in writer.depends_on
      assert is_acyclic(dag) is True
  ```
- [ ] Run `uv run pytest tests/unit/test_story_dependency.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/planner/dependency.py`:
  ```python
  from __future__ import annotations

  from cobol_modernizer.planner.schema import Story, StoryDAG


  def stories_from_seam_set(seam_candidates: list[dict], *, repo_id: str) -> list[Story]:
      """One story per seam, id = S{rank}, highest-scoring seam first (S1)."""
      ordered = sorted(seam_candidates,
                       key=lambda c: c["score"]["weighted"], reverse=True)
      return [Story(id=f"S{i+1}", title=f"Migrate {c['program']}",
                    seam=c["program"], evidence_map={"seam": [c["program"]]})
              for i, c in enumerate(ordered)]


  def derive_dependencies(stories: list[Story], seam_candidates: list[dict]) -> StoryDAG:
      """A writer story depends on the (lower-risk) reader stories of any resource it
      writes that another seam reads — read paths land before write paths (strangler-fig,
      reader-before-writer). Deterministic; acyclic because reader.score > writer.score
      and edges only point reader -> writer."""
      by_program = {c["program"]: c for c in seam_candidates}
      story_for = {s.seam: s for s in stories}
      for s in stories:
          cand = by_program[s.seam]
          deps: set[str] = set()
          for resource in cand.get("writes", []):
              for other in seam_candidates:
                  if other["program"] != s.seam and resource in other.get("reads", []):
                      deps.add(story_for[other["program"]].id)
          s.depends_on = sorted(deps)
      return StoryDAG(repo_id=stories[0].seam and "cardemo" or "cardemo", stories=stories)
  ```
  > Note: set `StoryDAG(repo_id=...)` from the caller in `service.py`; the line above keeps the unit test self-contained.
- [ ] Create `src/cobol_modernizer/planner/service.py`:
  ```python
  from __future__ import annotations

  from cobol_modernizer.planner.dag import is_acyclic, topo_order
  from cobol_modernizer.planner.dependency import (
      derive_dependencies, stories_from_seam_set,
  )
  from cobol_modernizer.planner.invest import judge_story
  from cobol_modernizer.planner.schema import StoryDAG


  async def build_story_dag(seam_candidates: list[dict], *, repo_id: str,
                            known_refs: set[str], runner, model: str) -> dict:
      """Build + acyclic-gate + INVEST-judge the story DAG. Returns the DAG plus the
      gate result; the caller persists artifact(kind='story_dag') + gate('stories_dag')."""
      stories = stories_from_seam_set(seam_candidates, repo_id=repo_id)
      dag = derive_dependencies(stories, seam_candidates)
      dag = StoryDAG(repo_id=repo_id, stories=dag.stories)

      acyclic = is_acyclic(dag)
      order = topo_order(dag) if acyclic else []

      reports = {}
      for s in dag.stories:
          reports[s.id] = await judge_story(s, known_refs=known_refs,
                                            runner=runner, model=model)
      all_pass = all(r["passed"] for r in reports.values())

      return {
          "dag": dag,
          "topo_order": order,
          "gate": {"gate_key": "stories_dag",
                   "threshold": {"acyclic": True, "all_invest_pass": True},
                   "result": {"acyclic": acyclic, "all_invest_pass": all_pass},
                   "status": "passed" if (acyclic and all_pass) else "failed"},
          "invest_reports": reports,
      }
  ```
- [ ] Run `uv run pytest tests/unit/test_story_dependency.py` — expected PASS (1 passed).
- [ ] Commit: `feat(planner): seam-set -> acyclic story DAG + INVEST-judged stories_dag gate`

---

## Task 14 — Integration: signals over a real testcontainers Neo4j v2 subgraph

Prove the Cypher signal queries run against a real Neo4j 5.x with a seeded v2 CardDemo subgraph (not a FakeClient). Marked `@pytest.mark.integration`; skipped when Docker is unavailable.

**Files:**
- Create: `tests/fixtures/carddemo_v2_subgraph.cypher`
- Test: `tests/integration/test_seam_signals_cypher.py`

Steps:
- [ ] Create `tests/fixtures/carddemo_v2_subgraph.cypher` (real v2 shape grounded in CardDemo):
  ```cypher
  CREATE (coactvwc:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'COACTVWC',
          qualified_name:'COACTVWC', file_path:'app/cbl/COACTVWC.cbl', is_external:false,
          start_line:1, end_line:940});
  CREATE (cbtrn02c:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'CBTRN02C',
          qualified_name:'CBTRN02C', file_path:'app/cbl/CBTRN02C.cbl', is_external:false,
          start_line:1, end_line:600});
  CREATE (cbact01c:CodeEntity {repo:'cardemo', kind:'Program', simple_name:'CBACT01C',
          qualified_name:'CBACT01C', file_path:'app/cbl/CBACT01C.cbl', is_external:false,
          start_line:1, end_line:400});
  CREATE (acctfile:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'ACCTFILE',
          qualified_name:'ACCTFILE', file_path:'', is_external:true});
  CREATE (custfile:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'CUSTFILE',
          qualified_name:'CUSTFILE', file_path:'', is_external:true});
  CREATE (transact:CodeEntity {repo:'cardemo', kind:'DataItem', simple_name:'TRANSACT',
          qualified_name:'TRANSACT', file_path:'', is_external:true});
  // COACTVWC reads ACCTFILE + CUSTFILE (CICS, reader-only)
  MATCH (p {qualified_name:'COACTVWC'}),(a {qualified_name:'ACCTFILE'})
    CREATE (p)-[:EXECUTES_CICS {resource:'ACCTFILE', command:'READ', intent:'read'}]->(a);
  MATCH (p {qualified_name:'COACTVWC'}),(c {qualified_name:'CUSTFILE'})
    CREATE (p)-[:EXECUTES_CICS {resource:'CUSTFILE', command:'READ', intent:'read'}]->(c);
  // CBACT01C reads ACCTFILE (batch sequential)
  MATCH (p {qualified_name:'CBACT01C'}),(a {qualified_name:'ACCTFILE'})
    CREATE (p)-[:READS {resource:'ACCTFILE', resourceType:'VSAM', mode:'sequential'}]->(a);
  // CBTRN02C writes ACCTFILE + TRANSACT (REWRITE -> writer, identity-drift)
  MATCH (p {qualified_name:'CBTRN02C'}),(a {qualified_name:'ACCTFILE'})
    CREATE (p)-[:WRITES {resource:'ACCTFILE', resourceType:'VSAM', mode:'random'}]->(a);
  MATCH (p {qualified_name:'CBTRN02C'}),(t {qualified_name:'TRANSACT'})
    CREATE (p)-[:WRITES {resource:'TRANSACT', resourceType:'VSAM', mode:'random'}]->(t);
  ```
- [ ] Write failing test `tests/integration/test_seam_signals_cypher.py`:
  ```python
  import os
  import pytest
  from pathlib import Path

  pytestmark = pytest.mark.integration

  FIX = Path(__file__).parents[1] / "fixtures" / "carddemo_v2_subgraph.cypher"


  @pytest.fixture(scope="module")
  def seeded_client():
      try:
          from testcontainers.neo4j import Neo4jContainer
      except Exception:
          pytest.skip("testcontainers not installed")
      try:
          with Neo4jContainer("neo4j:5.24") as neo:
              from cobol_modernizer.neo4j_client import Neo4jClient
              client = Neo4jClient(uri=neo.get_connection_url(),
                                   user="neo4j", password=neo.NEO4J_ADMIN_PASSWORD)
              for stmt in FIX.read_text().split(";"):
                  if stmt.strip():
                      client.run(stmt)
              yield client
      except Exception as exc:
          pytest.skip(f"Docker/Neo4j unavailable: {exc}")


  def test_coactvwc_signals_reader_only(seeded_client):
      from cobol_modernizer.seam.signals import raw_signals_for_program
      sig = raw_signals_for_program(seeded_client, repo="cardemo", program="COACTVWC")
      assert sig.risk == 0.0
      assert sig.testability == 1.0          # reader-only, no GO_TO

  def test_cbtrn02c_is_writer_with_risk(seeded_client):
      from cobol_modernizer.seam.reader_writer import is_identity_drift_writer
      assert is_identity_drift_writer(seeded_client, repo="cardemo",
                                      program="CBTRN02C") is True

  def test_ranking_puts_reader_first(seeded_client):
      from cobol_modernizer.seam.service import rank_candidates
      ranked = rank_candidates(seeded_client, repo="cardemo", limit=10)
      assert ranked[0]["program"] in ("COACTVWC", "CBACT01C")
      writer = next(c for c in ranked if c["program"] == "CBTRN02C")
      assert writer["identity_drift_writer"] is True
  ```
- [ ] Run `uv run pytest -m integration tests/integration/test_seam_signals_cypher.py` — expected PASS (3 passed) when Docker is available, else SKIPPED. (Register the `integration` marker in `pyproject.toml` `[tool.pytest.ini_options] markers = ["integration: needs docker"]`.)
- [ ] Commit: `test(seam): integration — seam signals + ranking over real Neo4j v2 CardDemo subgraph`

---

## Task 15 — Full Phase-4 suite green + read-only guard regression

**Files:**
- Test: run the whole Phase-4 unit suite + the read-only invariant.

Steps:
- [ ] Run `uv run pytest tests/unit/test_seam_scoring.py tests/unit/test_reader_writer.py tests/unit/test_seam_signals.py tests/unit/test_transition_pattern.py tests/unit/test_deadcode.py tests/unit/test_dedup.py tests/unit/test_seam_rationale.py tests/unit/test_story_dag.py tests/unit/test_invest_judge.py tests/unit/test_story_dependency.py` — expected PASS (all green).
- [ ] Add a read-only-guard regression to `tests/integration/test_seam_candidates_tool.py`:
  ```python
  def test_no_seam_op_emits_write_cypher():
      import inspect, cobol_modernizer.seam.signals as sg
      import cobol_modernizer.seam.reader_writer as rw
      import cobol_modernizer.seam.service as svc
      src = inspect.getsource(sg) + inspect.getsource(rw) + inspect.getsource(svc)
      for kw in ("CREATE ", "MERGE ", "DELETE ", "SET ", "REMOVE "):
          # CREATE/MERGE only appear in the test fixture, never in seam Cypher.
          assert kw not in src, f"seam Cypher must be read-only; found {kw!r}"
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_candidates_tool.py` — expected PASS.
- [ ] Commit: `test(seam): full Phase-4 suite green + read-only Cypher guard regression`

---

## Acceptance criteria

Maps 1:1 to the master plan's **Phase 4 Exit criteria** (§3): *"CardDemo seam backlog ranked with explainable evidence; identity-drift writers correctly flagged single-system; story DAG is acyclic; a known duplicate capability is flagged."* Plus the deterministic / token-economy non-negotiables (§1.4, §4.2).

1. **Ranked CardDemo seam backlog with explainable evidence.** `seam/service.py:rank_candidates` returns seams sorted by `score.weighted` computed as `0.25·business + 0.20·isolation + 0.20·testability + 0.20·data_ownership − 0.15·risk` over Cypher-computed, [0,1]-normalized signals; each `SeamCandidate` carries an `evidence_map` and a groundedness-gated `rationale`. Reader-only `COACTVWC` outranks writer `CBTRN02C`. (Tasks 1, 3, 4, 8, 12, 14)
2. **Identity-drift writers flagged single-system.** `seam/reader_writer.py:is_identity_drift_writer` flags `CBTRN02C` (`REWRITE ACCTFILE` that `COACTVWC`/`CBACT01C` also read) `True`; its transition is `extract_product_lines_acl` (Extract Product Lines + anti-corruption layer), keeping writes single-system. (Tasks 2, 5, 12, 14)
3. **Transition pattern per seam type.** `seam/transition.py` maps all five seam types to the master-plan patterns: Batch IO→Spring Batch adapter; CICS→facade routed by txn id; DB reader→CDC/replica; DB writer→Extract Product Lines+ACL; copybook→canonical DTO+ACL. (Task 5)
4. **Acyclic story DAG.** `planner/dag.py:topo_order` produces a deterministic Kahn topological order and raises `CycleError` on any cycle or unknown dependency; `planner/service.py:build_story_dag` gates `stories_dag` on `acyclic==True`. (Tasks 9, 13)
5. **INVEST-judged stories with groundedness floor.** `planner/invest.py:judge_story` scores six INVEST dimensions and floors `valuable`/`estimable` to ≤2 on any ungrounded seam ref (mirrors `brd_judge.py`). (Task 10)
6. **Known duplicate capability flagged.** `seam/dedup.py:duplicate_capabilities` clusters name-independent capability fingerprints; the date-validation capability duplicated across `COACTUPC`/`CORPT00C`/`COTRN02C` (all calling `CSUTLDTC`) surfaces as one cluster. (Tasks 7, 12)
7. **Dead (accidental) behavior excluded.** `seam/deadcode.py:dead_paragraphs` flags paragraphs unreachable from entry via PERFORM/`GO_TO`, enforcing required-vs-accidental rather than asserting it. (Task 6, 12)
8. **Zero LLM in the scoring path; read-only throughout.** All scoring is pure Python over read-only Cypher; the only LLM calls are rationale (Task 8) and INVEST (Task 10), both single-turn `tools=[]`/`setting_sources=[]`/`json_schema` and both groundedness-gated. The read-only guard regression (Task 15) proves seam Cypher contains no write clause; v2 MCP tools are `readOnlyHint=True` and added to `GRAPH_TOOL_NAMES`. (Tasks 8, 10, 11, 15)
9. **Blocked-on-Phase-1 honored.** Every signal reads v2 edges (`READS`/`WRITES`/`EXECUTES_CICS`/`EXECUTES_SQL`/`MOVES_TO`/`GO_TO`) and `DataItem` nodes that only exist post-Phase-1; the integration test (Task 14) exercises them against a real v2 subgraph. (master plan §7 risk 2)

> Cross-phase note: `build_seam_set`/`build_story_dag` return the artifact + gate payloads; the **Phase 2 / Phase 5 plans** own wiring these into Postgres `artifact`/`gate`/`approval` rows and `CostPolicy.record_usage`/`check` around the Sonnet rationale/INVEST runs (the `agent_run` row, model `resolve_model("seam")`/`resolve_model("story")`, cost caps). This plan provides the pure engines and the gate verdicts; persistence/SSE/cost-metering wiring is the consuming stage's responsibility per the Foundation storage split.
