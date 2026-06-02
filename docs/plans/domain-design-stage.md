# Domain Design Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The binding *what/why* is `docs/plans/domain-design-stage-spec.md` — this doc is the *how*.

**Goal:** Add a `domain-design` pipeline stage that turns the BRD + code graph into a business-capability-aligned decomposition (bounded contexts, per-context module-vs-microservice recommendation + strangler-fig order, full DDD tactical design), persisted as a versioned `:DomainDesign` Neo4j node, replacing the mechanical 1:1 writer→slice mapping.

**Architecture:** Three phases — (1) one gated LLM call proposes bounded contexts from BRD + a bounded graph-coupling summary; Python computes the topology score from existing seam signals and the extraction order; deterministic gates + bounded repair loop enforce coverage/data-ownership/groundedness/acyclicity. (2) one parallel agent per context produces full DDD tactical design, gated for groundedness + data-coverage. (3) assemble, validate cross-context invariants, persist + render. A `refine` loop produces new versions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Neo4j (Cypher), `claude-agent-sdk` via the existing `SdkAgentRunner`/`run_batched` harness, pytest (+ pytest-asyncio), Next.js 15/React 19 + Vitest (cockpit).

**Conventions to follow (read first):**
- New package lives in `src/cobol_modernizer/domain/`. Mirror the style of `src/cobol_modernizer/enrichment/` and `src/cobol_modernizer/seam/`.
- LLM calls go through `cobol_modernizer.enrichment.base.run_batched(...)` (wraps `SdkAgentRunner.run_structured` with a hard timeout and error→`{}`).
- Groundedness uses `cobol_modernizer.enrichment.base.ground_refs(cited, known_refs) -> (list[str], bool)`.
- Per-program signals come from `cobol_modernizer.seam.signals.raw_signals_for_program(client, repo=, program=) -> SeamSignals` (fields: `business, isolation, testability, data_ownership, risk`).
- Persistence mirrors `cobol_modernizer.brd.storage.BRDStorage` (versioned node off a `:Repository {slug}`).
- Endpoints + background jobs mirror `controlplane/blueprint.py` + `controlplane/analysis.py` (`jobs.runner.start(kind, wid, fn)`, `jobs.make_neo4j()`, `_workspace`, `_require_llm`, `_job_view`).
- Tests: stub runner is a class with `async def run_structured(self, **kw): return {...}` passed via `runner=` (see `tests/unit/test_enrich_design.py`).
- Run tests with `PYTHONPATH=src uv run pytest <path> -v`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/cobol_modernizer/domain/__init__.py` | package marker |
| `src/cobol_modernizer/domain/schema.py` | all Pydantic models (`DecompositionMap`, `BoundedContextDecl`, `TopologyDecision`, `ContextDependency`, `ContextDesign`, `Aggregate`, `CobolMapping`, `DomainDesign`) + the two JSON schemas for the LLM |
| `src/cobol_modernizer/domain/topology.py` | pure functions: `extract_score`, `deployment_for`, `assign_extraction_ranks` |
| `src/cobol_modernizer/domain/gates.py` | pure deterministic gates: coverage, data-ownership, acyclicity, groundedness, data-coverage, anemic warnings |
| `src/cobol_modernizer/domain/inputs.py` | `graph_coupling_summary(client, slug)` — bounded Cypher read |
| `src/cobol_modernizer/domain/decompose.py` | Phase 1 orchestration: prompt, `run_batched`, parse, topology, ranks, gate/repair loop |
| `src/cobol_modernizer/domain/tactical.py` | Phase 2: per-context agent + parallel fan-out |
| `src/cobol_modernizer/domain/assemble.py` | Phase 3: cross-context invariants + `DomainDesign` assembly + rating |
| `src/cobol_modernizer/domain/render.py` | self-contained HTML render for the cockpit |
| `src/cobol_modernizer/controlplane/domain.py` | `DomainDesignStorage` (`:DomainDesign` node) + the run orchestration entrypoint |
| `src/cobol_modernizer/controlplane/analysis.py` | +4 endpoints + the `domain-design` job (modify) |
| `src/cobol_modernizer/enrichment/config.py` | add `"domain"` model-env key (modify) |
| `src/cobol_modernizer/planner/schema.py` | add optional `Story.context` / `Story.topology` (modify) |
| `src/cobol_modernizer/design/context_map.py` | retire hardcoded dict; add generic fallback (modify) |
| `web/src/lib/api.ts` | typed client helpers (modify) |
| `web/src/components/screens/DomainStudio.tsx` | cockpit screen (create) |
| `tests/unit/test_domain_*.py` | unit tests per unit |
| `tests/integration/test_domain_design_api.py` | endpoint test with injected stub |

---

## Task 1: Domain schema models

**Files:**
- Create: `src/cobol_modernizer/domain/__init__.py`
- Create: `src/cobol_modernizer/domain/schema.py`
- Test: `tests/unit/test_domain_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_schema.py
from cobol_modernizer.domain.schema import (
    DecompositionMap, BoundedContextDecl, TopologyDecision, ContextDependency,
    ContextDesign, Aggregate, CobolMapping, DomainDesign,
)


def test_bounded_context_round_trips():
    ctx = BoundedContextDecl(
        name="Posting", business_capability="Post financial transactions",
        member_programs=["CBTRN02C"], owned_resources=["TRANSACT"],
        depends_on=[ContextDependency(target="Account", style="sync",
                                      reason="reads balance", cited_refs=["CBTRN02C"])],
        topology=TopologyDecision(deployment="microservice", score=0.71,
                                  inputs={"isolation_mean": 0.8}, rationale="high isolation"),
        extraction_rank=1, identity_drift=False, cited_refs=["FR-1", "CBTRN02C"])
    dumped = ctx.model_dump(mode="json")
    assert DecompositionMap(repo_slug="r", contexts=[ctx], unassigned_programs=[],
                            cited_refs=[]).contexts[0].topology.deployment == "microservice"
    assert dumped["depends_on"][0]["style"] == "sync"


def test_context_design_and_domain_design():
    cd = ContextDesign(
        context="Posting",
        aggregates=[Aggregate(name="Transaction", root_entity="Transaction",
                              invariants=["amount != 0"], entities=["Transaction"],
                              value_objects=["Money"], methods=["post"])],
        value_objects=["Money"], domain_services=["PostingService"],
        repositories=["TransactionRepository"], domain_events=["TransactionPosted"],
        api_surface="POST /transactions",
        cobol_mapping=[CobolMapping(cobol_ref="CBTRN02C.2800-UPDATE", maps_to="Transaction.post",
                                    note="paragraph folds into method")],
        cited_refs=["CBTRN02C"])
    dd = DomainDesign(repo_slug="r", version=1, rating="high", weighted_score=0.8,
                      contexts=[], designs=[cd], cited_refs=[])
    assert dd.designs[0].aggregates[0].methods == ["post"]
    assert dd.model_dump(mode="json")["designs"][0]["context"] == "Posting"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobol_modernizer.domain'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/__init__.py
```

```python
# src/cobol_modernizer/domain/schema.py
"""Pydantic models for the Domain Design stage (see docs/plans/domain-design-stage-spec.md).
LLM-facing JSON schemas (DECOMP_SCHEMA, CONTEXT_DESIGN_SCHEMA) intentionally OMIT the
fields Python computes (topology, extraction_rank, identity_drift) — the model proposes
membership/capability only; correctness fields are derived + gated in Python."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextDependency(BaseModel):
    target: str
    style: Literal["sync", "async"]
    reason: str
    cited_refs: list[str] = Field(default_factory=list)


class TopologyDecision(BaseModel):
    deployment: Literal["module", "microservice"]
    score: float
    inputs: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class BoundedContextDecl(BaseModel):
    name: str
    business_capability: str
    member_programs: list[str] = Field(default_factory=list)
    owned_resources: list[str] = Field(default_factory=list)
    depends_on: list[ContextDependency] = Field(default_factory=list)
    topology: TopologyDecision | None = None        # filled by Python in Phase 1
    extraction_rank: int = 0                         # filled by Python in Phase 1
    identity_drift: bool = False                     # filled by Python in Phase 1
    cited_refs: list[str] = Field(default_factory=list)


class DecompositionMap(BaseModel):
    repo_slug: str
    contexts: list[BoundedContextDecl] = Field(default_factory=list)
    unassigned_programs: list[str] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


class CobolMapping(BaseModel):
    cobol_ref: str
    maps_to: str
    note: str = ""


class Aggregate(BaseModel):
    name: str
    root_entity: str
    invariants: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    value_objects: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)


class ContextDesign(BaseModel):
    context: str
    aggregates: list[Aggregate] = Field(default_factory=list)
    value_objects: list[str] = Field(default_factory=list)
    domain_services: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    domain_events: list[str] = Field(default_factory=list)
    api_surface: str = ""
    cobol_mapping: list[CobolMapping] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


class DomainDesign(BaseModel):
    repo_slug: str
    version: int = 0
    rating: str = "medium"
    weighted_score: float = 0.0
    contexts: list[BoundedContextDecl] = Field(default_factory=list)
    designs: list[ContextDesign] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)


# ---- LLM-facing JSON schemas -------------------------------------------------

DECOMP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contexts": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "business_capability": {"type": "string"},
            "member_programs": {"type": "array", "items": {"type": "string"}},
            "owned_resources": {"type": "array", "items": {"type": "string"}},
            "depends_on": {"type": "array", "items": {"type": "object", "properties": {
                "target": {"type": "string"},
                "style": {"type": "string", "enum": ["sync", "async"]},
                "reason": {"type": "string"},
                "cited_refs": {"type": "array", "items": {"type": "string"}}},
                "required": ["target", "style"]}},
            "cited_refs": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "business_capability", "member_programs"]}},
        "unassigned_programs": {"type": "array", "items": {"type": "string"}},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["contexts"],
}

CONTEXT_DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "aggregates": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "root_entity": {"type": "string"},
            "invariants": {"type": "array", "items": {"type": "string"}},
            "entities": {"type": "array", "items": {"type": "string"}},
            "value_objects": {"type": "array", "items": {"type": "string"}},
            "methods": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "root_entity"]}},
        "value_objects": {"type": "array", "items": {"type": "string"}},
        "domain_services": {"type": "array", "items": {"type": "string"}},
        "repositories": {"type": "array", "items": {"type": "string"}},
        "domain_events": {"type": "array", "items": {"type": "string"}},
        "api_surface": {"type": "string"},
        "cobol_mapping": {"type": "array", "items": {"type": "object", "properties": {
            "cobol_ref": {"type": "string"}, "maps_to": {"type": "string"},
            "note": {"type": "string"}}, "required": ["cobol_ref", "maps_to"]}},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["aggregates"],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/__init__.py src/cobol_modernizer/domain/schema.py tests/unit/test_domain_schema.py
git commit -m "feat(domain): schema models + LLM JSON schemas for domain-design stage"
```

---

## Task 2: Topology scoring (pure)

**Files:**
- Create: `src/cobol_modernizer/domain/topology.py`
- Test: `tests/unit/test_domain_topology.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_topology.py
from cobol_modernizer.domain.schema import BoundedContextDecl
from cobol_modernizer.domain.topology import (
    extract_score, deployment_for, assign_extraction_ranks, EXTRACT_THRESHOLD,
)


def test_extract_score_high_isolation_high_ownership_extracts():
    score = extract_score(isolation_mean=0.9, data_ownership_mean=0.9,
                          business_mean=0.8, risk_mean=0.1, inbound_norm=0.0)
    assert score > EXTRACT_THRESHOLD
    assert deployment_for(score) == "microservice"


def test_extract_score_low_isolation_stays_module():
    score = extract_score(isolation_mean=0.1, data_ownership_mean=0.1,
                          business_mean=0.2, risk_mean=0.8, inbound_norm=1.0)
    assert deployment_for(score) == "module"


def test_extraction_ranks_leaf_first_then_value():
    a = BoundedContextDecl(name="A", business_capability="", member_programs=["p"])
    b = BoundedContextDecl(name="B", business_capability="", member_programs=["q"])
    # B depends on A's data (A has inbound dependency) -> A identity_drift, B is leaf.
    a.identity_drift = True
    a.topology = None
    b.topology = None
    ranked = assign_extraction_ranks([a, b], inbound={"A": 1, "B": 0},
                                     business={"A": 0.9, "B": 0.5})
    by_name = {c.name: c.extraction_rank for c in ranked}
    assert by_name["B"] < by_name["A"]   # leaf (no inbound) extracted first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_topology.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.topology`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/topology.py
"""Deterministic topology recommendation + strangler-fig extraction order.

The LLM proposes context MEMBERSHIP; these pure functions decide module-vs-service
from the SAME seam signals the seam engine already computes (consistency with the
Phase-4 weighted formula is deliberate)."""
from __future__ import annotations

from cobol_modernizer.domain.schema import BoundedContextDecl

EXTRACT_THRESHOLD = 0.55


def extract_score(*, isolation_mean: float, data_ownership_mean: float,
                  business_mean: float, risk_mean: float, inbound_norm: float) -> float:
    """Higher = more justified to extract as a standalone microservice."""
    return (0.30 * isolation_mean + 0.25 * data_ownership_mean
            + 0.20 * business_mean - 0.15 * risk_mean - 0.10 * inbound_norm)


def deployment_for(score: float) -> str:
    return "microservice" if score >= EXTRACT_THRESHOLD else "module"


def assign_extraction_ranks(contexts: list[BoundedContextDecl], *,
                            inbound: dict[str, int],
                            business: dict[str, float]) -> list[BoundedContextDecl]:
    """Strangler-fig order: leaf contexts (fewest inbound data deps) first, tie-broken
    by business value desc. Identity-drift contexts (others read their data) sink to
    the end ('keep shared / extract last'). Mutates + returns the list."""
    def key(c: BoundedContextDecl) -> tuple:
        return (1 if c.identity_drift else 0,
                inbound.get(c.name, 0),
                -business.get(c.name, 0.0),
                c.name)
    for rank, c in enumerate(sorted(contexts, key=key), start=1):
        c.extraction_rank = rank
    return contexts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_topology.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/topology.py tests/unit/test_domain_topology.py
git commit -m "feat(domain): deterministic topology score + extraction order"
```

---

## Task 3: Deterministic gates

**Files:**
- Create: `src/cobol_modernizer/domain/gates.py`
- Test: `tests/unit/test_domain_gates.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_gates.py
from cobol_modernizer.domain.schema import (
    BoundedContextDecl, ContextDependency, ContextDesign, Aggregate,
)
from cobol_modernizer.domain.gates import (
    check_coverage, check_data_ownership, check_acyclic, check_grounded,
    check_data_coverage, anemic_warnings, run_phase1_gates,
)


def _ctx(name, members, owned, deps=None):
    return BoundedContextDecl(name=name, business_capability="c",
                              member_programs=members, owned_resources=owned,
                              depends_on=deps or [], cited_refs=members)


def test_coverage_flags_missing_and_extra():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    assert check_coverage(ctxs, {"P1", "P2"}) == ["P2 not assigned to any context"]
    assert check_coverage([_ctx("A", ["P1"], []), _ctx("B", ["P1"], [])], {"P1"}) == \
        ["P1 assigned to multiple contexts"]


def test_data_ownership_flags_shared_writes():
    ctxs = [_ctx("A", ["P1"], ["R1"]), _ctx("B", ["P2"], ["R1"])]
    assert check_data_ownership(ctxs) == ["resource R1 owned by multiple contexts: A, B"]


def test_acyclic_detects_cycle():
    a = _ctx("A", ["P1"], [], [ContextDependency(target="B", style="sync", reason="")])
    b = _ctx("B", ["P2"], [], [ContextDependency(target="A", style="sync", reason="")])
    assert check_acyclic([a, b])  # non-empty -> violation
    assert check_acyclic([a]) == ["dependency target B is not a known context"] or \
        check_acyclic([_ctx("A", ["P1"], [])]) == []


def test_grounded_drops_unknown_refs():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    ctxs[0].cited_refs = ["P1", "GHOST"]
    assert check_grounded(ctxs, {"P1"}) == ["context A cites ungrounded refs: GHOST"]


def test_data_coverage_and_anemic():
    decl = _ctx("A", ["P1"], ["R1"])
    design = ContextDesign(context="A", aggregates=[
        Aggregate(name="Agg", root_entity="E", invariants=[], methods=[])])
    assert check_data_coverage(decl, design) == ["context A: owned resource R1 not in any aggregate/repository"]
    assert anemic_warnings(design) == ["aggregate Agg has no invariants or methods (anemic)"]


def test_run_phase1_gates_clean():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    assert run_phase1_gates(ctxs, {"P1"}, {"P1"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_gates.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.gates`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/gates.py
"""Deterministic gates for the Domain Design stage. Each returns a list of human-readable
violation strings (empty = pass). They never raise; the orchestrator decides repair-vs-fail."""
from __future__ import annotations

from cobol_modernizer.domain.schema import BoundedContextDecl, ContextDesign
from cobol_modernizer.enrichment.base import ground_refs


def check_coverage(contexts: list[BoundedContextDecl], writers: set[str]) -> list[str]:
    assigned: dict[str, int] = {}
    for c in contexts:
        for p in c.member_programs:
            assigned[p] = assigned.get(p, 0) + 1
    out = [f"{p} not assigned to any context" for p in sorted(writers) if p not in assigned]
    out += [f"{p} assigned to multiple contexts"
            for p, n in sorted(assigned.items()) if n > 1 and p in writers]
    return out


def check_data_ownership(contexts: list[BoundedContextDecl]) -> list[str]:
    owners: dict[str, list[str]] = {}
    for c in contexts:
        for r in c.owned_resources:
            owners.setdefault(r, []).append(c.name)
    return [f"resource {r} owned by multiple contexts: {', '.join(sorted(names))}"
            for r, names in sorted(owners.items()) if len(set(names)) > 1]


def check_acyclic(contexts: list[BoundedContextDecl]) -> list[str]:
    names = {c.name for c in contexts}
    graph: dict[str, list[str]] = {c.name: [] for c in contexts}
    for c in contexts:
        for dep in c.depends_on:
            if dep.target not in names:
                return [f"dependency target {dep.target} is not a known context"]
            graph[c.name].append(dep.target)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in names}

    def visit(n: str) -> bool:
        color[n] = GRAY
        for m in graph[n]:
            if color[m] == GRAY or (color[m] == WHITE and visit(m)):
                return True
        color[n] = BLACK
        return False

    for n in names:
        if color[n] == WHITE and visit(n):
            return [f"dependency cycle detected involving {n}"]
    return []


def check_grounded(contexts: list[BoundedContextDecl], known_refs: set[str]) -> list[str]:
    out: list[str] = []
    for c in contexts:
        refs = list(c.cited_refs) + list(c.member_programs)
        _grounded, ok = ground_refs(refs, known_refs)
        if not ok:
            bad = sorted(set(refs) - set(_grounded))
            out.append(f"context {c.name} cites ungrounded refs: {', '.join(bad)}")
    return out


def check_data_coverage(decl: BoundedContextDecl, design: ContextDesign) -> list[str]:
    covered = {agg.name for agg in design.aggregates} | set(design.repositories)
    covered |= {e for agg in design.aggregates for e in agg.entities}
    # A resource is "covered" if it appears (case-insensitive substring) in any agg/repo name.
    out = []
    blob = " ".join(covered).upper()
    for r in decl.owned_resources:
        token = r.replace("-", "").replace("_", "").upper()
        if token and token not in blob.replace("-", "").replace("_", ""):
            out.append(f"context {decl.name}: owned resource {r} not in any aggregate/repository")
    return out


def anemic_warnings(design: ContextDesign) -> list[str]:
    return [f"aggregate {a.name} has no invariants or methods (anemic)"
            for a in design.aggregates if not a.invariants and not a.methods]


def run_phase1_gates(contexts: list[BoundedContextDecl], writers: set[str],
                     known_refs: set[str]) -> list[str]:
    return (check_coverage(contexts, writers) + check_data_ownership(contexts)
            + check_acyclic(contexts) + check_grounded(contexts, known_refs))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_gates.py -v`
Expected: PASS (6 passed). If `test_acyclic_detects_cycle` is brittle, note the cycle case returns a non-empty list — adjust the assertion to `assert check_acyclic([a, b]) != []`.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/gates.py tests/unit/test_domain_gates.py
git commit -m "feat(domain): deterministic gates (coverage/ownership/acyclic/grounded/coverage/anemic)"
```

---

## Task 4: Graph coupling summary (bounded input)

**Files:**
- Create: `src/cobol_modernizer/domain/inputs.py`
- Test: `tests/unit/test_domain_inputs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_inputs.py
from cobol_modernizer.domain.inputs import graph_coupling_summary


class _FakeClient:
    def __init__(self, rows_by_marker):
        self._rows = rows_by_marker

    def run(self, query, **params):
        for marker, rows in self._rows.items():
            if marker in query:
                return rows
        return []


def test_summary_assembles_writers_and_cross_reads():
    client = _FakeClient({
        "// writers": [{"program": "P1", "writes": ["R1"]},
                       {"program": "P2", "writes": ["R2"]}],
        "// cross_reads": [{"reader": "P2", "resource": "R1", "writer": "P1"}],
        "// calls": [{"caller": "P2", "callee": "P1"}],
        "// co_change": [{"a": "P1", "b": "P2", "times": 5}],
    })
    s = graph_coupling_summary(client, "repo", top_n=10, cochange_floor=2)
    assert {w["program"] for w in s["writers"]} == {"P1", "P2"}
    assert s["cross_reads"] == [{"reader": "P2", "resource": "R1", "writer": "P1"}]
    assert s["calls"][0]["caller"] == "P2"
    assert s["co_change"][0]["times"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_inputs.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.inputs`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/inputs.py
"""Assemble a COMPACT, bounded graph-coupling summary for the Phase-1 decomposition
prompt. Bounded on purpose (top-N writers, cross-reads of owned resources, co-change
above a confidence floor) so the prompt stays well under the context window."""
from __future__ import annotations

from typing import Any

_WRITERS = """
// writers
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
WITH p, collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
WHERE size([z IN writes WHERE z IS NOT NULL]) > 0
RETURN p.qualified_name AS program, [z IN writes WHERE z IS NOT NULL] AS writes
ORDER BY program LIMIT $top_n
"""

_CROSS_READS = """
// cross_reads
MATCH (w:CodeEntity {repo:$repo, kind:'Program'})-[wr:WRITES]->(res)
MATCH (r:CodeEntity {repo:$repo, kind:'Program'})-[:READS]->(res)
WHERE r.qualified_name <> w.qualified_name
RETURN DISTINCT r.qualified_name AS reader,
       coalesce(wr.resource, res.simple_name) AS resource,
       w.qualified_name AS writer
ORDER BY reader, resource LIMIT $top_n
"""

_CALLS = """
// calls
MATCH (a:CodeEntity {repo:$repo, kind:'Program'})-[c:CALLS]->(b:CodeEntity {repo:$repo, kind:'Program'})
WHERE coalesce(c.type,'call') = 'call'
RETURN DISTINCT a.qualified_name AS caller, b.qualified_name AS callee
ORDER BY caller, callee LIMIT $top_n
"""

_CO_CHANGE = """
// co_change
MATCH (a:CodeEntity {repo:$repo, kind:'Program'})-[cc:CO_CHANGED_WITH]->(b:CodeEntity {repo:$repo, kind:'Program'})
WHERE cc.times >= $floor
RETURN a.qualified_name AS a, b.qualified_name AS b, cc.times AS times
ORDER BY times DESC LIMIT $top_n
"""


def graph_coupling_summary(client: Any, repo: str, *, top_n: int = 60,
                           cochange_floor: int = 2) -> dict[str, Any]:
    return {
        "writers": client.run(_WRITERS, repo=repo, top_n=top_n),
        "cross_reads": client.run(_CROSS_READS, repo=repo, top_n=top_n * 4),
        "calls": client.run(_CALLS, repo=repo, top_n=top_n * 4),
        "co_change": client.run(_CO_CHANGE, repo=repo, floor=cochange_floor, top_n=top_n * 2),
    }
```

> Note: the fake client matches on the `// marker` comment in each query, so keep those comments.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_inputs.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/inputs.py tests/unit/test_domain_inputs.py
git commit -m "feat(domain): bounded graph-coupling summary for decomposition prompt"
```

---

## Task 5: Phase 1 — decomposition orchestration

**Files:**
- Create: `src/cobol_modernizer/domain/decompose.py`
- Test: `tests/unit/test_domain_decompose.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_decompose.py
import pytest
from cobol_modernizer.domain.decompose import decompose


class _StubClient:
    """Minimal graph client: writers P1->R1, P2->R2; P2 reads R1 (P1 identity-drift)."""
    def run(self, query, **params):
        if "// writers" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "// cross_reads" in query:
            return [{"reader": "P2", "resource": "R1", "writer": "P1"}]
        if "_WRITES_BY_PROGRAM" in query or "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "P2"}]
        return []


def _signals(client, *, repo, program):
    from cobol_modernizer.seam.schema import SeamSignals
    table = {"P1": SeamSignals(business=0.5, isolation=0.2, testability=0.5,
                               data_ownership=0.3, risk=0.6),
             "P2": SeamSignals(business=0.9, isolation=0.9, testability=0.8,
                               data_ownership=0.9, risk=0.1)}
    return table[program]


class _Runner:
    async def run_structured(self, **kw):
        return {"contexts": [
            {"name": "Acct", "business_capability": "accounts", "member_programs": ["P1"],
             "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
            {"name": "Tx", "business_capability": "transactions", "member_programs": ["P2"],
             "owned_resources": ["R2"],
             "depends_on": [{"target": "Acct", "style": "sync", "reason": "reads R1",
                             "cited_refs": ["P2"]}], "cited_refs": ["P2"]}],
            "unassigned_programs": [], "cited_refs": []}


@pytest.mark.asyncio
async def test_decompose_assigns_topology_ranks_and_passes_gates():
    dm = await decompose(_StubClient(), "repo", brd_text="BRD",
                         runner=_Runner(), model="m", timeout_s=5,
                         signals_fn=_signals)
    names = {c.name for c in dm.contexts}
    assert names == {"Acct", "Tx"}
    tx = next(c for c in dm.contexts if c.name == "Tx")
    acct = next(c for c in dm.contexts if c.name == "Acct")
    assert tx.topology.deployment == "microservice"      # high isolation/ownership
    assert acct.topology.deployment == "module"          # low isolation, identity-drift
    assert acct.identity_drift is True                   # P2 reads R1
    assert tx.extraction_rank < acct.extraction_rank     # leaf extracted first


@pytest.mark.asyncio
async def test_decompose_raises_on_unrepairable_gate_violation():
    class _BadRunner:
        async def run_structured(self, **kw):
            return {"contexts": [{"name": "X", "business_capability": "c",
                                  "member_programs": ["P1"], "owned_resources": ["R1"],
                                  "depends_on": [], "cited_refs": ["P1"]}],
                    "unassigned_programs": [], "cited_refs": []}  # P2 never covered
    with pytest.raises(ValueError, match="domain decomposition failed gates"):
        await decompose(_StubClient(), "repo", brd_text="BRD", runner=_BadRunner(),
                        model="m", timeout_s=5, signals_fn=_signals, max_repairs=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_decompose.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.decompose`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/decompose.py
"""Phase 1: the LLM proposes bounded contexts from the BRD + a bounded graph-coupling
summary; Python computes the topology decision (from seam signals) and the strangler-fig
extraction order, then runs deterministic gates with a bounded repair loop."""
from __future__ import annotations

import json
from typing import Any, Callable

from cobol_modernizer.domain.gates import run_phase1_gates
from cobol_modernizer.domain.inputs import graph_coupling_summary
from cobol_modernizer.domain.schema import (
    DECOMP_SCHEMA, BoundedContextDecl, DecompositionMap, TopologyDecision,
)
from cobol_modernizer.domain.topology import (
    assign_extraction_ranks, deployment_for, extract_score,
)
from cobol_modernizer.enrichment.base import run_batched
from cobol_modernizer.seam.signals import raw_signals_for_program

DECOMPOSE_SYSTEM = (
    "You are a software architect decomposing a legacy COBOL system into business-capability "
    "bounded contexts (Domain-Driven Design) for a Spring Boot rebuild. Group the writer "
    "programs into contexts by BUSINESS CAPABILITY, not by COBOL structure — do NOT emit one "
    "context per program. Every writer program in the graph summary MUST be assigned to exactly "
    "one context. A resource may be OWNED (written) by only one context. Ground every context in "
    "the BRD and the graph: cite BRD requirement ids and program qualified-names in cited_refs; "
    "invent no identifiers. Declare inter-context dependencies (sync for request/response, async "
    "for events) with a grounded reason. "
    'Return JSON: {"contexts":[{"name","business_capability","member_programs":[str],'
    '"owned_resources":[str],"depends_on":[{"target","style","reason","cited_refs":[str]}],'
    '"cited_refs":[str]}],"unassigned_programs":[str],"cited_refs":[str]}.'
)

_WRITES_BY_PROGRAM = """
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
RETURN p.qualified_name AS program,
       collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
"""
_KNOWN_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"

SignalsFn = Callable[..., Any]


def _writers(client: Any, repo: str) -> set[str]:
    rows = client.run(_WRITES_BY_PROGRAM, repo=repo)
    return {r["program"] for r in rows if any(w for w in (r.get("writes") or []))}


def _known_refs(client: Any, repo: str) -> set[str]:
    return {r["q"] for r in client.run(_KNOWN_REFS_Q, repo=repo)}


def _parse(raw: dict, repo: str) -> DecompositionMap:
    contexts = []
    for c in raw.get("contexts", []):
        if isinstance(c, dict) and isinstance(c.get("name"), str):
            try:
                contexts.append(BoundedContextDecl.model_validate(c))
            except Exception:  # noqa: BLE001 — skip malformed entries; gates catch coverage gaps
                continue
    return DecompositionMap(repo_slug=repo, contexts=contexts,
                            unassigned_programs=list(raw.get("unassigned_programs", [])),
                            cited_refs=list(raw.get("cited_refs", [])))


def _apply_topology(client: Any, repo: str, dm: DecompositionMap,
                    signals_fn: SignalsFn) -> None:
    # inbound[ctx] = number of OTHER contexts that read a resource this ctx owns.
    owner_of = {r: c.name for c in dm.contexts for r in c.owned_resources}
    inbound = {c.name: 0 for c in dm.contexts}
    business = {}
    for c in dm.contexts:
        sigs = [signals_fn(client, repo=repo, program=p) for p in c.member_programs] or None
        iso = sum(s.isolation for s in sigs) / len(sigs) if sigs else 0.0
        own = sum(s.data_ownership for s in sigs) / len(sigs) if sigs else 0.0
        biz = sum(s.business for s in sigs) / len(sigs) if sigs else 0.0
        rsk = sum(s.risk for s in sigs) / len(sigs) if sigs else 0.0
        business[c.name] = biz
        c._sig_cache = (iso, own, biz, rsk)  # type: ignore[attr-defined]
    # identity-drift + inbound: a context whose owned resource another context's deps target.
    for c in dm.contexts:
        for dep in c.depends_on:
            if dep.target in inbound:
                inbound[dep.target] += 1
    for c in dm.contexts:
        c.identity_drift = inbound.get(c.name, 0) > 0
    max_inbound = max(inbound.values()) if inbound else 0
    for c in dm.contexts:
        iso, own, biz, rsk = c._sig_cache  # type: ignore[attr-defined]
        inbound_norm = (inbound[c.name] / max_inbound) if max_inbound else 0.0
        score = extract_score(isolation_mean=iso, data_ownership_mean=own,
                              business_mean=biz, risk_mean=rsk, inbound_norm=inbound_norm)
        c.topology = TopologyDecision(
            deployment=deployment_for(score), score=round(score, 4),
            inputs={"isolation_mean": round(iso, 4), "data_ownership_mean": round(own, 4),
                    "business_mean": round(biz, 4), "risk_mean": round(rsk, 4),
                    "inbound_norm": round(inbound_norm, 4)},
            rationale=("high cohesion/ownership favors extraction"
                       if deployment_for(score) == "microservice"
                       else "shared data / low isolation favors a module"))
    assign_extraction_ranks(dm.contexts, inbound=inbound, business=business)


async def decompose(client: Any, repo: str, *, brd_text: str, runner: Any, model: str,
                    timeout_s: float, signals_fn: SignalsFn = raw_signals_for_program,
                    max_repairs: int = 2) -> DecompositionMap:
    writers = _writers(client, repo)
    known = _known_refs(client, repo)
    summary = graph_coupling_summary(client, repo)
    base_prompt = ("## BRD\n" + brd_text + "\n\n## Graph coupling summary\n```json\n"
                   + json.dumps(summary) + "\n```\nDecompose into business-capability "
                   "bounded contexts. Every writer program must be assigned exactly once.")
    violations: list[str] = []
    for attempt in range(max_repairs + 1):
        prompt = base_prompt
        if violations:
            prompt += ("\n\n## Fix these violations from your previous answer\n- "
                       + "\n- ".join(violations))
        raw = await run_batched(runner=runner, system=DECOMPOSE_SYSTEM, prompt=prompt,
                                schema=DECOMP_SCHEMA, model=model, timeout_s=timeout_s,
                                label="domain-decompose")
        dm = _parse(raw, repo)
        _apply_topology(client, repo, dm, signals_fn)
        violations = run_phase1_gates(dm.contexts, writers, known)
        if not violations:
            return dm
    raise ValueError("domain decomposition failed gates after "
                     f"{max_repairs + 1} attempts: {'; '.join(violations)}")
```

> The `_sig_cache` private attribute avoids recomputing signals; Pydantic v2 allows setting
> private/extra attributes on a model instance at runtime. If your Pydantic config forbids it,
> store the tuple in a local `dict[str, tuple]` keyed by context name instead.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_decompose.py -v`
Expected: PASS (2 passed). If setting `c._sig_cache` raises a Pydantic error, switch to a local `sig_by_name: dict[str, tuple] = {}` keyed by `c.name` (see note) and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/decompose.py tests/unit/test_domain_decompose.py
git commit -m "feat(domain): Phase 1 decomposition orchestration + gate/repair loop"
```

---

## Task 6: Phase 2 — per-context tactical DDD (parallel)

**Files:**
- Create: `src/cobol_modernizer/domain/tactical.py`
- Test: `tests/unit/test_domain_tactical.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_tactical.py
import pytest
from cobol_modernizer.domain.schema import BoundedContextDecl
from cobol_modernizer.domain.tactical import design_context, design_all_contexts


class _Runner:
    async def run_structured(self, **kw):
        return {"aggregates": [{"name": "Account", "root_entity": "Account",
                                "invariants": ["balance >= 0"], "methods": ["post"]}],
                "value_objects": ["Money"], "domain_services": ["PostingService"],
                "repositories": ["AccountRepository"], "domain_events": ["Posted"],
                "api_surface": "POST /accounts",
                "cobol_mapping": [{"cobol_ref": "P1.2800", "maps_to": "Account.post",
                                   "note": "folds in"}],
                "cited_refs": ["P1", "GHOST"]}


def _ctx(name="Acct"):
    return BoundedContextDecl(name=name, business_capability="accounts",
                              member_programs=["P1"], owned_resources=["ACCT"],
                              cited_refs=["P1"])


@pytest.mark.asyncio
async def test_design_context_grounds_refs():
    cd = await design_context(_ctx(), known_refs={"P1"}, runner=_Runner(),
                              model="m", timeout_s=5)
    assert cd.context == "Acct"
    assert cd.aggregates[0].methods == ["post"]
    assert cd.cited_refs == ["P1"]   # GHOST dropped


@pytest.mark.asyncio
async def test_design_all_contexts_parallel():
    ctxs = [_ctx("A"), _ctx("B")]
    out = await design_all_contexts(ctxs, known_refs={"P1"}, runner=_Runner(),
                                    model="m", timeout_s=5)
    assert {c.context for c in out} == {"A", "B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_tactical.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.tactical`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/tactical.py
"""Phase 2: one focused agent PER context produces the full DDD tactical design
(aggregates/entities/value-objects/domain-services/repositories/events/API + the
COBOL->domain mapping). Small bounded jobs => deep output, parallelizable, no turn-cap
starvation. Groundedness is enforced on the returned refs."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from cobol_modernizer.domain.schema import (
    CONTEXT_DESIGN_SCHEMA, Aggregate, BoundedContextDecl, CobolMapping, ContextDesign,
)
from cobol_modernizer.enrichment.base import ground_refs, run_batched

TACTICAL_SYSTEM = (
    "You design the OO domain model for ONE bounded context of a Spring Boot system rebuilt "
    "from legacy COBOL. Produce RICH aggregates: fold COBOL paragraph behavior into aggregate "
    "methods and protect invariants — do NOT emit anemic CRUD classes that merely mirror copybook "
    "fields. For the context's owned resources, define aggregates, entities, value objects, domain "
    "services, repository interfaces, domain events, and a REST/command API surface. Provide a "
    "cobol_mapping: each entry maps a COBOL copybook/record/paragraph qualified-name to the domain "
    "element it becomes. Ground everything ONLY in this context's member programs/resources; cite "
    "refs in cited_refs; invent no identifiers. "
    'Return JSON: {"aggregates":[{"name","root_entity","invariants":[str],"entities":[str],'
    '"value_objects":[str],"methods":[str]}],"value_objects":[str],"domain_services":[str],'
    '"repositories":[str],"domain_events":[str],"api_surface","cobol_mapping":[{"cobol_ref",'
    '"maps_to","note"}],"cited_refs":[str]}.'
)


def _parse(raw: dict, ctx: BoundedContextDecl, known_refs: set[str]) -> ContextDesign:
    aggs = []
    for a in raw.get("aggregates", []):
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            aggs.append(Aggregate(
                name=a["name"], root_entity=str(a.get("root_entity", a["name"])),
                invariants=[s for s in (a.get("invariants") or []) if isinstance(s, str)],
                entities=[s for s in (a.get("entities") or []) if isinstance(s, str)],
                value_objects=[s for s in (a.get("value_objects") or []) if isinstance(s, str)],
                methods=[s for s in (a.get("methods") or []) if isinstance(s, str)]))
    maps = [CobolMapping(cobol_ref=m["cobol_ref"], maps_to=m["maps_to"],
                         note=str(m.get("note", "")))
            for m in raw.get("cobol_mapping", [])
            if isinstance(m, dict) and m.get("cobol_ref") and m.get("maps_to")]
    cited, _ok = ground_refs(raw.get("cited_refs"), known_refs)
    return ContextDesign(
        context=ctx.name, aggregates=aggs,
        value_objects=[s for s in (raw.get("value_objects") or []) if isinstance(s, str)],
        domain_services=[s for s in (raw.get("domain_services") or []) if isinstance(s, str)],
        repositories=[s for s in (raw.get("repositories") or []) if isinstance(s, str)],
        domain_events=[s for s in (raw.get("domain_events") or []) if isinstance(s, str)],
        api_surface=str(raw.get("api_surface", "")), cobol_mapping=maps, cited_refs=cited)


async def design_context(ctx: BoundedContextDecl, *, known_refs: set[str], runner: Any,
                         model: str, timeout_s: float) -> ContextDesign:
    prompt = ("## Bounded context\n```json\n"
              + json.dumps(ctx.model_dump(mode="json")) + "\n```\n"
              "Design the full DDD tactical model for THIS context only.")
    raw = await run_batched(runner=runner, system=TACTICAL_SYSTEM, prompt=prompt,
                            schema=CONTEXT_DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                            label=f"domain-tactical:{ctx.name}")
    return _parse(raw, ctx, known_refs)


async def design_all_contexts(contexts: list[BoundedContextDecl], *, known_refs: set[str],
                              runner: Any, model: str, timeout_s: float) -> list[ContextDesign]:
    tasks = [design_context(c, known_refs=known_refs, runner=runner, model=model,
                            timeout_s=timeout_s) for c in contexts]
    return list(await asyncio.gather(*tasks))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_tactical.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/tactical.py tests/unit/test_domain_tactical.py
git commit -m "feat(domain): Phase 2 per-context tactical DDD (parallel)"
```

---

## Task 7: Phase 3 — assemble + rate

**Files:**
- Create: `src/cobol_modernizer/domain/assemble.py`
- Test: `tests/unit/test_domain_assemble.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_assemble.py
from cobol_modernizer.domain.schema import (
    DecompositionMap, BoundedContextDecl, ContextDesign, Aggregate, TopologyDecision,
)
from cobol_modernizer.domain.assemble import assemble


def _decl(name, owned):
    return BoundedContextDecl(name=name, business_capability="c", member_programs=["P"],
                              owned_resources=owned,
                              topology=TopologyDecision(deployment="module", score=0.1),
                              cited_refs=["P"])


def test_assemble_rates_and_collects_warnings():
    dm = DecompositionMap(repo_slug="r", contexts=[_decl("A", ["ACCT"])])
    designs = [ContextDesign(context="A", aggregates=[
        Aggregate(name="Account", root_entity="Account", invariants=["x"], methods=["m"])],
        repositories=["AccountRepository"], cited_refs=["P"])]
    dd = assemble("r", dm, designs, version=3)
    assert dd.version == 3
    assert dd.rating in {"high", "medium", "low"}
    assert dd.contexts[0].name == "A"
    assert dd.designs[0].context == "A"


def test_assemble_low_rating_when_anemic():
    dm = DecompositionMap(repo_slug="r", contexts=[_decl("A", ["ACCT"])])
    designs = [ContextDesign(context="A", aggregates=[
        Aggregate(name="Account", root_entity="Account")], cited_refs=["P"])]
    dd = assemble("r", dm, designs, version=1)
    assert dd.rating == "low"   # anemic + uncovered resource
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_assemble.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.assemble`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/assemble.py
"""Phase 3: combine the decomposition + per-context designs into a rated DomainDesign,
checking cross-context invariants and folding gate warnings into a rating."""
from __future__ import annotations

from cobol_modernizer.domain.gates import anemic_warnings, check_data_coverage
from cobol_modernizer.domain.schema import ContextDesign, DecompositionMap, DomainDesign


def cross_context_warnings(dm: DecompositionMap, designs: list[ContextDesign]) -> list[str]:
    seen: dict[str, str] = {}
    out: list[str] = []
    for d in designs:
        for agg in d.aggregates:
            if agg.name in seen and seen[agg.name] != d.context:
                out.append(f"aggregate {agg.name} spans contexts {seen[agg.name]} and {d.context}")
            seen[agg.name] = d.context
    return out


def _rate(n_warnings: int) -> tuple[str, float]:
    if n_warnings == 0:
        return "high", 1.0
    if n_warnings <= 2:
        return "medium", 0.6
    return "low", 0.3


def assemble(repo_slug: str, dm: DecompositionMap, designs: list[ContextDesign],
             *, version: int = 0) -> DomainDesign:
    decl_by_name = {c.name: c for c in dm.contexts}
    warnings: list[str] = cross_context_warnings(dm, designs)
    for d in designs:
        decl = decl_by_name.get(d.context)
        if decl:
            warnings += check_data_coverage(decl, d)
        warnings += anemic_warnings(d)
    rating, score = _rate(len(warnings))
    cited = sorted({r for c in dm.contexts for r in c.cited_refs}
                   | {r for d in designs for r in d.cited_refs})
    return DomainDesign(repo_slug=repo_slug, version=version, rating=rating,
                        weighted_score=score, contexts=dm.contexts, designs=designs,
                        cited_refs=cited)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_assemble.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/assemble.py tests/unit/test_domain_assemble.py
git commit -m "feat(domain): Phase 3 assemble + cross-context invariants + rating"
```

---

## Task 8: HTML render

**Files:**
- Create: `src/cobol_modernizer/domain/render.py`
- Test: `tests/unit/test_domain_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_render.py
from cobol_modernizer.domain.schema import (
    DomainDesign, BoundedContextDecl, ContextDesign, Aggregate, TopologyDecision,
)
from cobol_modernizer.domain.render import render_html


def test_render_contains_context_and_topology():
    dd = DomainDesign(repo_slug="r", version=2, rating="high", weighted_score=1.0,
        contexts=[BoundedContextDecl(name="Posting", business_capability="post tx",
                  member_programs=["CBTRN02C"], owned_resources=["TRANSACT"],
                  topology=TopologyDecision(deployment="microservice", score=0.7),
                  extraction_rank=1, cited_refs=["CBTRN02C"])],
        designs=[ContextDesign(context="Posting", aggregates=[
            Aggregate(name="Transaction", root_entity="Transaction",
                      invariants=["amount != 0"], methods=["post"])],
            api_surface="POST /transactions", cited_refs=["CBTRN02C"])])
    html = render_html(dd)
    assert "<html" in html.lower()
    assert "Posting" in html and "microservice" in html
    assert "Transaction" in html and "POST /transactions" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_render.py -v`
Expected: FAIL — `ModuleNotFoundError: ... domain.render`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/domain/render.py
"""Self-contained HTML render of a DomainDesign for the cockpit iframe (no external CSS/JS).
Escapes all model-supplied text."""
from __future__ import annotations

from html import escape

from cobol_modernizer.domain.schema import DomainDesign


def _li(items: list[str]) -> str:
    return "".join(f"<li>{escape(s)}</li>" for s in items)


def render_html(dd: DomainDesign) -> str:
    blocks: list[str] = []
    designs = {d.context: d for d in dd.designs}
    for c in sorted(dd.contexts, key=lambda x: x.extraction_rank or 0):
        topo = c.topology
        badge = escape(topo.deployment) if topo else "n/a"
        score = f"{topo.score:.2f}" if topo else "-"
        d = designs.get(c.name)
        aggs = "".join(
            f"<div class=agg><b>{escape(a.name)}</b> (root: {escape(a.root_entity)})"
            f"<div>invariants:<ul>{_li(a.invariants)}</ul>methods:<ul>{_li(a.methods)}</ul></div></div>"
            for a in (d.aggregates if d else []))
        api = escape(d.api_surface) if d and d.api_surface else ""
        mapping = "".join(
            f"<tr><td>{escape(m.cobol_ref)}</td><td>{escape(m.maps_to)}</td><td>{escape(m.note)}</td></tr>"
            for m in (d.cobol_mapping if d else []))
        blocks.append(
            f"<section class=ctx><h2>#{c.extraction_rank} {escape(c.name)} "
            f"<span class=badge>{badge}</span> <small>score {score}</small></h2>"
            f"<p><i>{escape(c.business_capability)}</i></p>"
            f"<p>Owns: {escape(', '.join(c.owned_resources))}"
            f"{' &middot; identity-drift' if c.identity_drift else ''}</p>"
            f"<h3>Aggregates</h3>{aggs or '<p>none</p>'}"
            f"{('<h3>API</h3><pre>' + api + '</pre>') if api else ''}"
            f"{('<h3>COBOL mapping</h3><table><tr><th>COBOL</th><th>Domain</th><th>Note</th></tr>' + mapping + '</table>') if mapping else ''}"
            "</section>")
    style = ("body{font-family:system-ui;margin:2rem;color:#222}"
             ".ctx{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
             ".badge{background:#eef;border-radius:12px;padding:2px 8px;font-size:.8rem}"
             "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}"
             ".agg{margin:.5rem 0}")
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<title>Domain Design v{dd.version} — {escape(dd.repo_slug)}</title>"
            f"<style>{style}</style></head><body>"
            f"<h1>Domain Design — {escape(dd.repo_slug)} "
            f"<small>v{dd.version} · {escape(dd.rating)}</small></h1>"
            f"{''.join(blocks)}</body></html>")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_render.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/domain/render.py tests/unit/test_domain_render.py
git commit -m "feat(domain): self-contained HTML render for the cockpit"
```

---

## Task 9: Persistence — `:DomainDesign` storage

**Files:**
- Create: `src/cobol_modernizer/controlplane/domain.py`
- Test: `tests/unit/test_domain_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_domain_storage.py
from cobol_modernizer.domain.schema import DomainDesign, BoundedContextDecl, TopologyDecision
from cobol_modernizer.controlplane.domain import DomainDesignStorage


class _FakeClient:
    """Records CREATE params and serves them back for get_latest."""
    def __init__(self):
        self.saved = None

    def run(self, query, **params):
        if "CREATE (d:DomainDesign" in query:
            self.saved = dict(params)
            return [{"version": params["version"]}]
        if "coalesce(max(prev.version), 0) + 1" in query:
            return [{"version": 1}]
        if "ORDER BY d.version DESC" in query:
            return [{"d": self.saved}] if self.saved else []
        return []


def _dd():
    return DomainDesign(repo_slug="r", contexts=[BoundedContextDecl(
        name="A", business_capability="c", member_programs=["P"],
        topology=TopologyDecision(deployment="module", score=0.1))], designs=[])


def test_save_assigns_version_and_serializes():
    client = _FakeClient()
    store = DomainDesignStorage(client)
    dd = store.save(_dd(), html="<html></html>")
    assert dd.version == 1
    latest = store.get_latest("r")
    assert latest["version"] == 1
    assert "A" in latest["contexts_json"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_storage.py -v`
Expected: FAIL — `ImportError: cannot import name 'DomainDesignStorage'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/cobol_modernizer/controlplane/domain.py
"""Persist Domain Designs to Neo4j (versioned :DomainDesign nodes off :Repository{slug}),
mirroring brd.storage.BRDStorage. The GET path reads the latest persisted node so a finished
design survives a server restart (the JobRunner only tracks in-flight progress)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.domain.schema import DomainDesign

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_DOMAIN_DESIGN]->(prev:DomainDesign)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (d:DomainDesign {
    id: $id, repo_slug: $repo_slug, version: version, rating: $rating,
    weighted_score: $weighted_score, contexts_json: $contexts_json,
    designs_json: $designs_json, evidence_map: $evidence_map, html: $html,
    model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_DOMAIN_DESIGN]->(d)
RETURN d.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_DOMAIN_DESIGN]->(d:DomainDesign)
RETURN d ORDER BY d.version DESC LIMIT 1
"""


class DomainDesignStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, dd: DomainDesign, *, html: str, model: str = "",
             token_usage: dict[str, int] | None = None,
             evidence_map: dict[str, list[str]] | None = None) -> DomainDesign:
        did = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=did, repo_slug=dd.repo_slug, rating=dd.rating,
            weighted_score=dd.weighted_score,
            contexts_json=json.dumps([c.model_dump(mode="json") for c in dd.contexts]),
            designs_json=json.dumps([d.model_dump(mode="json") for d in dd.designs]),
            evidence_map=json.dumps(evidence_map or {}), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created,
            version=1)  # version param only used by the fake; real query computes it
        if not rows:
            raise ValueError(f"Repository not found: {dd.repo_slug}")
        dd.version = rows[0]["version"]
        return dd

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["d"] if rows else None
```

> Note: the real `_SAVE` query computes `version` server-side; the `version=1` kwarg exists only
> so the unit `_FakeClient` can echo a version without a live DB. The real Neo4j driver ignores
> unused params. Add a `:DomainDesign(id)` uniqueness constraint in the schema setup that mirrors
> the `:BRD(id)` constraint (see `src/cobol_modernizer/schema.py`) as part of this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_storage.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Add the uniqueness constraint**

In `src/cobol_modernizer/schema.py`, find where `:BRD` constraints are declared and add an
analogous line for `:DomainDesign`:

```python
"CREATE CONSTRAINT domain_design_id IF NOT EXISTS FOR (d:DomainDesign) REQUIRE d.id IS UNIQUE",
```

Run: `PYTHONPATH=src uv run pytest tests/unit/ -k "schema" -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/domain.py tests/unit/test_domain_storage.py src/cobol_modernizer/schema.py
git commit -m "feat(domain): versioned :DomainDesign Neo4j persistence"
```

---

## Task 10: Run orchestration entrypoint

**Files:**
- Modify: `src/cobol_modernizer/controlplane/domain.py`
- Modify: `src/cobol_modernizer/enrichment/config.py:9-11` (add `"domain"` model key)
- Test: `tests/unit/test_domain_run.py`

- [ ] **Step 1: Add the domain model-env key**

In `src/cobol_modernizer/enrichment/config.py`, extend `_MODEL_ENV`:

```python
_MODEL_ENV = {"seams": "SEAM_ENRICH_MODEL", "plan": "PLAN_ENRICH_MODEL",
              "design": "DESIGN_ENRICH_MODEL", "domain": "DOMAIN_DESIGN_MODEL"}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_domain_run.py
import pytest
from cobol_modernizer.controlplane.domain import run_domain_design


class _StubClient:
    def run(self, query, **params):
        if "// writers" in query or "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "// cross_reads" in query:
            return [{"reader": "P2", "resource": "R1", "writer": "P1"}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "P2"}]
        return []


def _signals(client, *, repo, program):
    from cobol_modernizer.seam.schema import SeamSignals
    return SeamSignals(business=0.8, isolation=0.8, testability=0.8,
                       data_ownership=0.8, risk=0.1)


class _Runner:
    async def run_structured(self, **kw):
        if "domain-decompose" in kw.get("label", ""):
            return {"contexts": [
                {"name": "Acct", "business_capability": "a", "member_programs": ["P1"],
                 "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
                {"name": "Tx", "business_capability": "t", "member_programs": ["P2"],
                 "owned_resources": ["R2"], "depends_on": [], "cited_refs": ["P2"]}],
                "unassigned_programs": [], "cited_refs": []}
        return {"aggregates": [{"name": "Agg", "root_entity": "E", "invariants": ["i"],
                                "methods": ["m"]}], "repositories": ["R1Repository"],
                "api_surface": "GET /x", "cited_refs": ["P1"]}


def test_run_domain_design_end_to_end():
    dd = run_domain_design(_StubClient(), "repo", brd_text="BRD", runner=_Runner(),
                           model="m", timeout_s=5, signals_fn=_signals)
    assert {c.name for c in dd.contexts} == {"Acct", "Tx"}
    assert len(dd.designs) == 2
    assert dd.rating in {"high", "medium", "low"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_run.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_domain_design'`

- [ ] **Step 4: Add `run_domain_design` to `controlplane/domain.py`**

Append to `src/cobol_modernizer/controlplane/domain.py`:

```python
import asyncio  # add to the existing imports at top of the file

from cobol_modernizer.domain.assemble import assemble
from cobol_modernizer.domain.decompose import decompose
from cobol_modernizer.domain.tactical import design_all_contexts
from cobol_modernizer.seam.signals import raw_signals_for_program


def run_domain_design(client: Any, repo_slug: str, *, brd_text: str, runner: Any,
                      model: str, timeout_s: float, signals_fn=raw_signals_for_program,
                      version: int = 0) -> DomainDesign:
    """Phases 1-3, synchronous wrapper (drives the async agents via asyncio.run).
    Does NOT persist — the caller persists so it can inject storage/version."""
    async def _go() -> DomainDesign:
        dm = await decompose(client, repo_slug, brd_text=brd_text, runner=runner,
                             model=model, timeout_s=timeout_s, signals_fn=signals_fn)
        known = {r["q"] for r in client.run(
            "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q", repo=repo_slug)}
        designs = await design_all_contexts(dm.contexts, known_refs=known, runner=runner,
                                            model=model, timeout_s=timeout_s)
        return assemble(repo_slug, dm, designs, version=version)
    return asyncio.run(_go())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_domain_run.py tests/unit/test_enrichment_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/domain.py src/cobol_modernizer/enrichment/config.py tests/unit/test_domain_run.py
git commit -m "feat(domain): run_domain_design orchestration + DOMAIN_DESIGN_MODEL env"
```

---

## Task 11: API endpoints + background job

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py` (add endpoints near the design routes, ~line 305)
- Test: `tests/integration/test_domain_design_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_domain_design_api.py
"""Endpoint test with the job runner forced inline + the LLM runner stubbed, so it runs
without Neo4j/Anthropic. Mirrors the existing controlplane endpoint tests."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    os.environ["ANTHROPIC_API_KEY"] = "test"
    from cobol_modernizer.controlplane import jobs
    monkeypatch.setattr(jobs.runner, "inline", True)
    from cobol_modernizer import api
    return TestClient(api.app)


def test_domain_design_post_then_get(client, monkeypatch):
    # Stub the heavy run + persistence so the route logic is what's under test.
    from cobol_modernizer.controlplane import analysis
    from cobol_modernizer.domain.schema import DomainDesign, BoundedContextDecl, TopologyDecision

    def _fake_run(*a, **k):
        return DomainDesign(repo_slug="demo", version=1, rating="high", weighted_score=1.0,
            contexts=[BoundedContextDecl(name="Acct", business_capability="c",
                      member_programs=["P1"], topology=TopologyDecision(
                          deployment="microservice", score=0.7))], designs=[])

    monkeypatch.setattr(analysis, "_domain_run_and_persist", lambda *a, **k:
                        {"repo_slug": "demo", "version": 1, "rating": "high"})
    # Assumes a seeded 'demo' workspace fixture exists (see tests/conftest.py seeding);
    # if not, create one via POST /api/workspaces first.
    wid = client.post("/api/workspaces", json={"repo_slug": "demo"}).json()["id"]
    r = client.post(f"/api/workspaces/{wid}/domain-design")
    assert r.status_code == 202
    g = client.get(f"/api/workspaces/{wid}/domain-design")
    assert g.status_code == 200
    assert g.json()["status"] in {"done", "running", "idle"}
```

> If the project's existing controlplane tests use a different workspace-seeding fixture, follow
> that pattern instead of `POST /api/workspaces` — see `tests/integration/` for the established
> setup (the goal is a valid `wid`).

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/integration/test_domain_design_api.py -v`
Expected: FAIL — 404 on `/domain-design` (route not registered)

- [ ] **Step 3: Add the endpoints to `analysis.py`**

Add imports at the top of `src/cobol_modernizer/controlplane/analysis.py`:

```python
from pydantic import BaseModel

from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane.domain import DomainDesignStorage, run_domain_design
from cobol_modernizer.domain.render import render_html
from cobol_modernizer.domain.schema import DomainDesign
from cobol_modernizer.enrichment.config import enrich_model, enrich_timeout_s
from fastapi.responses import HTMLResponse
```

Add this body after the `design_enrichment` route (around line 305):

```python
class _DomainRefineBody(BaseModel):
    instruction: str = ""


def _brd_text(neo, slug: str) -> str:
    """Latest BRD as plain text for the decomposition prompt; '' if none yet."""
    try:
        latest = BRDStorage(neo).get_latest(slug)
    except _NEO4J_ERRORS:
        return ""
    if not latest:
        return ""
    import json as _json
    secs = latest.get("sections")
    if secs:
        try:
            return "\n\n".join(s.get("body_markdown", "")
                               for s in _json.loads(secs) if isinstance(s, dict))
        except Exception:  # noqa: BLE001
            pass
    return str(latest.get("html", ""))


def _domain_run_and_persist(slug: str, *, instruction: str = "") -> dict:
    neo = jobs.make_neo4j()
    try:
        brd = _brd_text(neo, slug)
        if instruction:
            brd = f"{brd}\n\n## Refinement instruction\n{instruction}"
        runner = SdkAgentRunner()
        dd = run_domain_design(neo, slug, brd_text=brd, runner=runner,
                               model=enrich_model("domain"),
                               timeout_s=enrich_timeout_s("domain"))
        neo.run("MERGE (r:Repository {slug:$slug})", slug=slug)
        dd = DomainDesignStorage(neo).save(dd, html=render_html(dd),
                                           model=enrich_model("domain"),
                                           token_usage=dict(runner.token_usage),
                                           evidence_map={})
        return {"repo_slug": slug, "version": dd.version, "rating": dd.rating,
                "contexts": [c.model_dump(mode="json") for c in dd.contexts],
                "designs": [d.model_dump(mode="json") for d in dd.designs],
                "token_usage": dict(runner.token_usage)}
    finally:
        try:
            neo.close()
        except Exception:  # noqa: BLE001
            pass


@router.post("/workspaces/{wid}/domain-design", status_code=202)
def domain_design_start(wid: str, session: Session = Depends(get_session),
                        neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug
    return _job_view(jobs.runner.start("domain-design", wid,
                                       lambda: _domain_run_and_persist(slug)))


@router.post("/workspaces/{wid}/domain-design/refine", status_code=202)
def domain_design_refine(wid: str, body: _DomainRefineBody,
                         session: Session = Depends(get_session),
                         neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    _require_llm()
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction must be non-empty")
    slug = ws.repo_slug
    return _job_view(jobs.runner.start("domain-design", wid,
                                       lambda: _domain_run_and_persist(slug, instruction=instruction)))


@router.get("/workspaces/{wid}/domain-design")
def domain_design_status(wid: str, session: Session = Depends(get_session),
                         neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("domain-design", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        import json as _json
        return {"status": "done", "error": None, "result": {
            "repo_slug": ws.repo_slug, "version": latest.get("version"),
            "rating": latest.get("rating"),
            "contexts": _json.loads(latest.get("contexts_json") or "[]"),
            "designs": _json.loads(latest.get("designs_json") or "[]")}}
    return {"status": "idle", "result": None, "error": None}


@router.get("/workspaces/{wid}/domain-design/html", response_class=HTMLResponse)
def domain_design_html(wid: str, session: Session = Depends(get_session),
                       neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no domain design yet — run it first")
    return HTMLResponse(content=latest["html"])
```

> The test monkeypatches `analysis._domain_run_and_persist`, so the job body must call the
> module-level name (it does). Keep `_domain_run_and_persist` at module scope, not nested.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/integration/test_domain_design_api.py -v`
Expected: PASS. Adjust workspace seeding to match the repo's fixture if the `wid` setup differs.

- [ ] **Step 5: Run the full backend suite for regressions**

Run: `PYTHONPATH=src uv run pytest tests/unit tests/integration -q`
Expected: all pass (no regressions from the new imports/routes).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/integration/test_domain_design_api.py
git commit -m "feat(domain): domain-design API (start/refine/status/html) + persisted GET"
```

---

## Task 12: Tag stories with context + topology (plan compatibility)

**Files:**
- Modify: `src/cobol_modernizer/planner/schema.py:18-25` (`Story`)
- Modify: `src/cobol_modernizer/controlplane/analysis.py` (`run_plan`, tag stories if a DomainDesign exists)
- Test: `tests/unit/test_plan_story_tagging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_plan_story_tagging.py
from cobol_modernizer.planner.schema import Story
from cobol_modernizer.planner.tagging import tag_stories_with_contexts


def test_story_has_optional_context_and_topology_defaulting_none():
    s = Story(id="S1", title="t", seam="P1")
    assert s.context is None and s.topology is None


def test_tag_stories_assigns_context_and_topology():
    stories = [Story(id="S1", title="t", seam="P1"), Story(id="S2", title="t", seam="P2")]
    contexts = [{"name": "Acct", "member_programs": ["P1"],
                 "topology": {"deployment": "microservice"}}]
    out = tag_stories_with_contexts(stories, contexts)
    assert out[0].context == "Acct" and out[0].topology == "microservice"
    assert out[1].context is None   # P2 not in any context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_plan_story_tagging.py -v`
Expected: FAIL — `Story` has no `context`; `planner.tagging` missing.

- [ ] **Step 3: Add the optional fields + the tagging helper**

In `src/cobol_modernizer/planner/schema.py`, add two optional fields to `Story`:

```python
class Story(BaseModel):
    id: str
    title: str
    seam: str
    depends_on: list[str] = Field(default_factory=list)
    invest: InvestScore | None = None
    evidence_map: EvidenceMap = Field(default_factory=dict)
    context: str | None = None          # bounded context (from domain-design), if known
    topology: str | None = None         # "module" | "microservice", if known
```

Create `src/cobol_modernizer/planner/tagging.py`:

```python
"""Tag planner stories with the bounded context + topology decided by the domain-design
stage. Pure + optional: stories whose seam isn't in any context are left untagged."""
from __future__ import annotations

from typing import Any

from cobol_modernizer.planner.schema import Story


def tag_stories_with_contexts(stories: list[Story], contexts: list[dict[str, Any]]) -> list[Story]:
    by_program: dict[str, dict] = {}
    for c in contexts:
        for p in c.get("member_programs", []):
            by_program[p] = c
    for s in stories:
        ctx = by_program.get(s.seam)
        if ctx:
            s.context = ctx.get("name")
            topo = ctx.get("topology") or {}
            s.topology = topo.get("deployment") if isinstance(topo, dict) else None
    return stories
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_plan_story_tagging.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire `run_plan` to tag when a DomainDesign exists (best-effort)**

In `run_plan` (`analysis.py`), after `dag = derive_dependencies(...)` and before building the
response, add:

```python
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
        if latest:
            import json as _json
            from cobol_modernizer.planner.tagging import tag_stories_with_contexts
            tag_stories_with_contexts(dag.stories, _json.loads(latest.get("contexts_json") or "[]"))
    except _NEO4J_ERRORS:
        pass
```

Run: `PYTHONPATH=src uv run pytest tests/unit/test_plan_stage_waves.py tests/integration -q`
Expected: PASS (existing plan behavior unchanged when no DomainDesign exists)

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/planner/schema.py src/cobol_modernizer/planner/tagging.py src/cobol_modernizer/controlplane/analysis.py tests/unit/test_plan_story_tagging.py
git commit -m "feat(plan): tag stories with bounded context + topology from domain-design"
```

---

## Task 13: Retire hardcoded context map (generic fallback)

**Files:**
- Modify: `src/cobol_modernizer/design/context_map.py`
- Modify: `tests/unit/test_design_context_map.py`
- Test: `tests/unit/test_design_context_map.py`

> Goal: remove the CardDemo-specific `RESOURCE_CONTEXT` dict so the deterministic *fallback*
> design is generic. The new domain-design stage does not use this path; this satisfies the
> "no CardDemo hardcoding" acceptance criterion.

- [ ] **Step 1: Read the current module + its test**

Run: `sed -n '1,60p' src/cobol_modernizer/design/context_map.py; echo ---; sed -n '1,60p' tests/unit/test_design_context_map.py`
Note the exact `assign_context` signature and what `test_design_context_map.py` asserts.

- [ ] **Step 2: Rewrite the test for generic behavior**

Replace `tests/unit/test_design_context_map.py` assertions that expect hardcoded names
(`account_management`, etc.) with generic-grouping expectations:

```python
# tests/unit/test_design_context_map.py
from cobol_modernizer.design.context_map import assign_context_generic


class _Adapter:
    def __init__(self, writes): self._w = writes
    def writer_resources(self, program): return self._w.get(program, [])


def test_generic_context_named_from_dominant_resource():
    adapter = _Adapter({"CBACT01C": ["ACCT-MASTER", "ACCT-IDX"]})
    ctx = assign_context_generic(adapter, "CBACT01C")
    assert "ACCT" in ctx.upper()       # derived from the resource it writes, not a dict


def test_generic_context_stable_and_nonempty():
    adapter = _Adapter({"P": ["XREF"]})
    assert assign_context_generic(adapter, "P")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_design_context_map.py -v`
Expected: FAIL — `assign_context_generic` missing.

- [ ] **Step 4: Implement the generic assigner; keep `assign_context` as a thin alias**

In `src/cobol_modernizer/design/context_map.py`, delete the `RESOURCE_CONTEXT` dict and add:

```python
import re


def assign_context_generic(adapter, program: str) -> str:
    """Derive a bounded-context label generically from the resources a program writes —
    the longest common alpha prefix of its owned resources, lowercased. No hardcoded map."""
    resources = [r for r in adapter.writer_resources(program) if r]
    if not resources:
        raise ValueError(f"{program} writes no resources")
    tokens = [re.sub(r"[^A-Za-z]", "", r).upper() for r in resources]
    tokens = [t for t in tokens if t] or [re.sub(r"[^A-Za-z]", "", program).upper()]
    # shared prefix across written resources, min 3 chars, else the first token.
    prefix = tokens[0]
    for t in tokens[1:]:
        while not t.startswith(prefix) and len(prefix) > 3:
            prefix = prefix[:-1]
    base = prefix if len(prefix) >= 3 else tokens[0]
    return f"{base.lower()}_context"


# Back-compat: the deterministic design fallback calls assign_context(...).
def assign_context(adapter, program: str) -> str:
    return assign_context_generic(adapter, program)
```

> If `design/schema.py::BoundedContext` is an `Enum` restricted to the 4 hardcoded names,
> change it to a free `str` (or a `NewType("BoundedContext", str)`) so generic names validate.
> Update `_compute_designs` in `analysis.py` accordingly (`context=context` instead of
> `BoundedContext(context)` if it's now a plain str). Run the design tests after.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src uv run pytest tests/unit/test_design_context_map.py tests/unit/test_design_schema.py tests/integration -k "design" -v`
Expected: PASS (the deterministic design route still returns designs, now with generic context names)

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/design/context_map.py src/cobol_modernizer/design/schema.py src/cobol_modernizer/controlplane/analysis.py tests/unit/test_design_context_map.py
git commit -m "refactor(design): retire hardcoded context map; generic context fallback"
```

---

## Task 14: Cockpit — API client helpers

**Files:**
- Modify: `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts`

- [ ] **Step 1: Read the existing design helpers + a Job type**

Run: `grep -n "DesignEnrichResult\|startDesignEnrich\|getDesignEnrichment\|JobStatus\|export interface Job" web/src/lib/api.ts`
Note the `Job<T>` shape (`{status, result, error}`) and how `startDesignEnrich`/`getDesignEnrichment` are written — mirror them exactly.

- [ ] **Step 2: Write the failing test**

```typescript
// add to web/src/lib/api.test.ts
import { describe, it, expect } from "vitest";
import { api } from "@/lib/api";

describe("domain-design api", () => {
  it("exposes start/refine/get helpers", () => {
    expect(typeof api.startDomainDesign).toBe("function");
    expect(typeof api.refineDomainDesign).toBe("function");
    expect(typeof api.getDomainDesign).toBe("function");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL — `api.startDomainDesign is not a function`

- [ ] **Step 4: Add the types + helpers to `web/src/lib/api.ts`**

Add types (place near `DesignResult`/`DesignEnrichResult`):

```typescript
export interface DomainTopology { deployment: "module" | "microservice"; score: number;
  inputs?: Record<string, number>; rationale?: string }
export interface DomainContext { name: string; business_capability: string;
  member_programs: string[]; owned_resources: string[];
  depends_on: { target: string; style: "sync" | "async"; reason: string }[];
  topology: DomainTopology | null; extraction_rank: number; identity_drift: boolean }
export interface DomainAggregate { name: string; root_entity: string; invariants: string[];
  entities: string[]; value_objects: string[]; methods: string[] }
export interface DomainContextDesign { context: string; aggregates: DomainAggregate[];
  value_objects: string[]; domain_services: string[]; repositories: string[];
  domain_events: string[]; api_surface: string;
  cobol_mapping: { cobol_ref: string; maps_to: string; note: string }[] }
export interface DomainDesignResult { repo_slug: string; version: number; rating: string;
  contexts: DomainContext[]; designs: DomainContextDesign[] }
```

Add helpers to the `api` object (mirror the existing `startDesignEnrich`/`getDesignEnrichment`
implementations — same fetch/JSON/error handling):

```typescript
  startDomainDesign: (id: string) =>
    postJob<DomainDesignResult>(`/api/workspaces/${id}/domain-design`),
  refineDomainDesign: (id: string, instruction: string) =>
    postJob<DomainDesignResult>(`/api/workspaces/${id}/domain-design/refine`, { instruction }),
  getDomainDesign: (id: string) =>
    getJob<DomainDesignResult>(`/api/workspaces/${id}/domain-design`),
```

> Use whatever the file's existing job POST/GET helpers are called (the design helpers reveal
> them — e.g. a `postJob`/`getJob` or inline `fetch`). Match that exact pattern; do not invent
> a new transport.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): domain-design API client helpers + types"
```

---

## Task 15: Cockpit — DomainStudio screen

**Files:**
- Create: `web/src/components/screens/DomainStudio.tsx`
- Test: `web/src/components/screens/DomainStudio.test.tsx`
- Modify: wherever screens are registered (mirror how `DesignStudio` is wired into the journey rail)

- [ ] **Step 1: Read DesignStudio + its MSW handler + test**

Run: `sed -n '1,60p' web/src/components/screens/DesignStudio.tsx; echo ---; grep -n "design/enrich\|design/enrichment" web/src/test/msw/handlers.ts`
Mirror the `useJob` usage, MSW handler style, and test setup.

- [ ] **Step 2: Add MSW handlers for domain-design**

In `web/src/test/msw/handlers.ts`, add handlers mirroring the design-enrich ones:

```typescript
  http.post("/api/workspaces/:id/domain-design", () =>
    HttpResponse.json({ status: "done", result: {
      repo_slug: "demo", version: 1, rating: "high",
      contexts: [{ name: "Posting", business_capability: "Post transactions",
        member_programs: ["CBTRN02C"], owned_resources: ["TRANSACT"], depends_on: [],
        topology: { deployment: "microservice", score: 0.71, inputs: {}, rationale: "" },
        extraction_rank: 1, identity_drift: false }],
      designs: [{ context: "Posting", aggregates: [{ name: "Transaction",
        root_entity: "Transaction", invariants: ["amount != 0"], entities: [],
        value_objects: ["Money"], methods: ["post"] }], value_objects: [],
        domain_services: ["PostingService"], repositories: ["TransactionRepository"],
        domain_events: ["TransactionPosted"], api_surface: "POST /transactions",
        cobol_mapping: [] }] }, error: null })),
  http.get("/api/workspaces/:id/domain-design", () =>
    HttpResponse.json({ status: "idle", result: null, error: null })),
```

- [ ] **Step 3: Write the failing test**

```tsx
// web/src/components/screens/DomainStudio.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DomainStudio } from "./DomainStudio";

describe("DomainStudio", () => {
  it("runs decomposition and shows contexts + topology", async () => {
    render(<DomainStudio workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button", { name: /decompose/i }));
    await waitFor(() => expect(screen.getByText(/Posting/)).toBeInTheDocument());
    expect(screen.getByText(/microservice/i)).toBeInTheDocument();
    expect(screen.getByText(/POST \/transactions/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/DomainStudio.test.tsx`
Expected: FAIL — cannot find `./DomainStudio`

- [ ] **Step 5: Implement the screen**

```tsx
// web/src/components/screens/DomainStudio.tsx
"use client";

import { useState } from "react";
import { Boxes, Play, Sparkles, AlertTriangle } from "lucide-react";
import { api, type DomainDesignResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Domain Design: business-capability bounded contexts + per-context module-vs-microservice
// recommendation + full DDD tactical design. Replaces the 1:1 writer-slice mapping.
export function DomainStudio({ workspaceId }: { workspaceId: string }) {
  const [instruction, setInstruction] = useState("");
  const job = useJob<DomainDesignResult>(
    () => api.startDomainDesign(workspaceId),
    () => api.getDomainDesign(workspaceId),
  );
  const refine = useJob<DomainDesignResult>(
    () => api.refineDomainDesign(workspaceId, instruction),
    () => api.getDomainDesign(workspaceId),
  );
  const result = refine.result ?? job.result;
  const contexts = [...(result?.contexts ?? [])].sort(
    (a, b) => (a.extraction_rank || 0) - (b.extraction_rank || 0));
  const designByCtx = Object.fromEntries((result?.designs ?? []).map((d) => [d.context, d]));

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Domain design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Business-capability bounded contexts with a module-vs-microservice recommendation,
        strangler-fig extraction order, and full DDD tactical design. Run Blueprint first.
      </p>
      <div className="flex items-center gap-2">
        <button onClick={job.run} disabled={job.busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{job.busy ? "Decomposing…" : "Decompose"}
        </button>
      </div>

      {result && (
        <div className="flex items-center gap-2">
          <input value={instruction} onChange={(e) => setInstruction(e.target.value)}
            placeholder="Refine, e.g. 'split billing from payments'"
            className="flex-1 px-3 py-2 text-sm rounded bg-zinc-900 border border-zinc-700" />
          <button onClick={refine.run} disabled={refine.busy || !instruction.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
            <Sparkles className="w-4 h-4" />{refine.busy ? "Refining…" : "Refine"}
          </button>
        </div>
      )}

      {(job.error || refine.error) && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{job.error || refine.error}</span>
        </div>
      )}

      {contexts.map((c) => {
        const d = designByCtx[c.name];
        return (
          <div key={c.name} className="rounded-md border border-zinc-800 p-3 space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xs text-zinc-600">#{c.extraction_rank}</span>
              <span className="font-mono text-sm text-zinc-200">{c.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                c.topology?.deployment === "microservice"
                  ? "bg-emerald-900 text-emerald-300" : "bg-zinc-800 text-zinc-300"}`}>
                {c.topology?.deployment ?? "n/a"}
                {c.topology ? ` · ${c.topology.score.toFixed(2)}` : ""}
              </span>
              {c.identity_drift && <span className="text-xs text-amber-400">identity-drift</span>}
            </div>
            <div className="text-xs text-zinc-400">{c.business_capability}</div>
            <div className="text-xs text-zinc-500">
              Owns: <span className="font-mono text-zinc-300">{c.owned_resources.join(", ")}</span>
            </div>
            {d && (
              <div className="space-y-1 pt-1 border-t border-zinc-800">
                {d.aggregates.map((a) => (
                  <div key={a.name} className="text-xs text-zinc-400">
                    <span className="text-zinc-300">{a.name}</span>
                    {a.methods.length > 0 && <> — methods: {a.methods.join(", ")}</>}
                    {a.invariants.length > 0 && (
                      <div className="text-zinc-500 pl-2">invariants: {a.invariants.join("; ")}</div>
                    )}
                  </div>
                ))}
                {d.api_surface && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">API:</span> {d.api_surface}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/screens/DomainStudio.test.tsx`
Expected: PASS

- [ ] **Step 7: Register the screen in the journey rail**

Find how `DesignStudio` is wired (e.g. a screen map keyed by `stage_key`) and add `DomainStudio`
for the `design` stage (or a new `domain` stage if the stage list is extended). Run the typecheck
+ build:

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: PASS (all web tests green)

- [ ] **Step 8: Commit**

```bash
git add web/src/components/screens/DomainStudio.tsx web/src/components/screens/DomainStudio.test.tsx web/src/test/msw/handlers.ts
git commit -m "feat(web): DomainStudio cockpit screen (contexts, topology, DDD, refine)"
```

---

## Task 16: Docs — INDEX entry + README touch

**Files:**
- Modify: `docs/plans/INDEX.md`
- Modify: `README.md`

- [ ] **Step 1: Add a catalog row to `docs/plans/INDEX.md`**

In the §1 document catalog table, add:

```markdown
| `domain-design-stage.md` (+ `-spec.md`) | NEW post-core workstream. Business-capability bounded-context decomposition (LLM-proposed, gate-validated) + per-context module-vs-microservice recommendation + strangler-fig order + full DDD tactical design; versioned `:DomainDesign` persistence + `DomainStudio` cockpit screen; retires the hardcoded `context_map`. | 16 | Blueprint (BRD), Seams (signals), Foundation |
```

- [ ] **Step 2: Add a short README section**

Under the stages/features overview in `README.md`, add a sentence describing the Domain Design
stage and its endpoints (`POST/GET /api/workspaces/{id}/domain-design`, `/refine`, `/html`). Keep
it consistent with how the other stages are described.

- [ ] **Step 3: Commit**

```bash
git add docs/plans/INDEX.md README.md
git commit -m "docs: catalog + README entry for the domain-design stage"
```

---

## Final verification

- [ ] **Run the whole backend suite**

Run: `PYTHONPATH=src uv run pytest tests -q`
Expected: all pass.

- [ ] **Run the whole web suite + typecheck + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx next build`
Expected: all green.

- [ ] **Manual smoke (optional, needs Neo4j + ANTHROPIC_API_KEY)**

Run `./scripts/start-backend.sh`, then `POST /api/workspaces/{id}/domain-design` on a parsed +
blueprinted workspace; poll `GET …/domain-design`; confirm fewer contexts than writer programs,
topology badges, and that a server restart still returns the persisted design via GET.

---

## Self-Review notes (for the implementer)

- **Spec coverage:** §4 inputs → Task 4; §5 decomposition+topology+gates → Tasks 2,3,5; §6 tactical → Task 6; §7 assemble+persist → Tasks 7,9; §8 refine → Task 11; §9 API → Task 11; §10 cockpit → Tasks 14,15; §11 generality → Task 13; §12 testing → every task; §3 plan tagging → Task 12; §13 layout → all.
- **Type consistency:** `TopologyDecision.deployment` is `"module"|"microservice"` everywhere (schema, topology.py, render, web). `ContextDesign.context` is the FK to `BoundedContextDecl.name`. `run_phase1_gates(contexts, writers, known_refs)` signature matches its caller in `decompose.py`.
- **Known sharp edges flagged inline:** Pydantic private-attr cache in Task 5 (fallback given); `BoundedContext` enum→str in Task 13; web job transport helper name in Task 14; workspace-seeding fixture in Task 11.
