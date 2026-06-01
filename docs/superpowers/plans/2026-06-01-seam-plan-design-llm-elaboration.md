# Seam / Plan / Design LLM Elaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add batched, prompt-grounded LLM narrative on top of the three deterministic stages (seams, plan, design) — delivered two-phase (instant deterministic result + async enrich job) — plus deterministic delivery-wave planning for the plan stage.

**Architecture:** The deterministic stages are unchanged (instant). A parallel `enrich` background job per stage re-runs the fast deterministic compute, makes ONE batched structured-LLM call to add narrative, validates grounding against the graph, and stores the result by item id. The UI renders deterministic output immediately and merges enrichment when its job completes. Enrichment never blocks a stage or gate; on failure/timeout the stage degrades to deterministic-only.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, Neo4j, `claude-agent-sdk` (via the existing `SdkAgentRunner`), the in-process `jobs.runner`; Next.js 15 / React 19 / Vitest / MSW on the web side.

**Spec:** `docs/superpowers/specs/2026-06-01-seam-plan-design-llm-elaboration-design.md`

**Conventions to follow:**
- TDD: write the failing test, see it fail, implement minimally, see it pass, commit.
- Run Python tests with `PYTHONPATH=src .venv/bin/python -m pytest <path> -v`.
- Run web tests with `cd web && npx vitest run <path>`.
- Enrichers are pure async functions (deterministic inputs in, dict-by-id out) so they test with a `FakeRunner` and no network.
- Defensive parsing everywhere (mirror `src/cobol_modernizer/agent/brd_judge.py` `_norm_*`/`_parse_*`): skip malformed rows, never raise out of an enricher.

---

## Phase 1 — Deterministic delivery waves (no LLM)

### Task 1: `delivery_waves` DAG level-sets

**Files:**
- Modify: `src/cobol_modernizer/planner/dag.py`
- Test: `tests/unit/test_delivery_waves.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_delivery_waves.py
from cobol_modernizer.planner.dag import delivery_waves, topo_order
from cobol_modernizer.planner.schema import Story, StoryDAG


def _dag(*edges_by_story):
    # edges_by_story: (id, [deps]) tuples
    return StoryDAG(repo_id="r",
                    stories=[Story(id=i, title=i, seam=i, depends_on=list(d))
                             for i, d in edges_by_story])


def test_independent_stories_share_wave_one():
    dag = _dag(("S1", []), ("S2", []), ("S3", []))
    assert delivery_waves(dag) == [["S1", "S2", "S3"]]


def test_dependents_land_in_later_waves():
    # S2 depends on S1; S3 depends on S2  -> three single-story waves
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S2"]))
    assert delivery_waves(dag) == [["S1"], ["S2"], ["S3"]]


def test_diamond_dag():
    # S1 -> S2, S1 -> S3, (S2,S3) -> S4
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S1"]), ("S4", ["S2", "S3"]))
    assert delivery_waves(dag) == [["S1"], ["S2", "S3"], ["S4"]]


def test_waves_agree_with_topo_order():
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S1"]), ("S4", ["S2", "S3"]))
    waves = delivery_waves(dag)
    flat = [s for w in waves for s in w]
    assert sorted(flat) == sorted(topo_order(dag))   # every story exactly once
    pos = {s: wi for wi, w in enumerate(waves) for s in w}
    for s in dag.stories:                            # deps strictly earlier
        for dep in s.depends_on:
            assert pos[dep] < pos[s.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_delivery_waves.py -v`
Expected: FAIL with `ImportError: cannot import name 'delivery_waves'`.

- [ ] **Step 3: Implement `delivery_waves`**

Add to `src/cobol_modernizer/planner/dag.py` (after `topo_order`):

```python
def delivery_waves(dag: StoryDAG) -> list[list[str]]:
    """Group the story DAG into delivery WAVES (level-sets): wave 0 is every story
    with no dependencies, wave 1 every story whose deps are all in wave 0, etc.
    Stories in the same wave have no edges between them and can migrate in parallel.
    Same Kahn's-algorithm pass as topo_order, batched by level. Raises CycleError on
    a cycle / unknown id (a cycle is a hard gate failure, like topo_order)."""
    ids = {s.id for s in dag.stories}
    indeg: dict[str, int] = {s.id: 0 for s in dag.stories}
    adj: dict[str, list[str]] = {s.id: [] for s in dag.stories}
    for s in dag.stories:
        for dep in s.depends_on:
            if dep not in ids:
                raise CycleError(f"story {s.id!r} depends on unknown story {dep!r}")
            adj[dep].append(s.id)
            indeg[s.id] += 1
    frontier = sorted(i for i, d in indeg.items() if d == 0)
    waves: list[list[str]] = []
    seen = 0
    while frontier:
        waves.append(frontier)
        seen += len(frontier)
        nxt: list[str] = []
        for n in frontier:
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    nxt.append(m)
        frontier = sorted(nxt)
    if seen != len(dag.stories):
        remaining = sorted(i for i, d in indeg.items() if d > 0)
        raise CycleError(f"story DAG has a cycle among: {remaining}")
    return waves
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_delivery_waves.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/planner/dag.py tests/unit/test_delivery_waves.py
git commit -m "feat(planner): delivery_waves (DAG level-sets = parallel migration tracks)"
```

### Task 2: Return `delivery_waves` from the plan stage

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py` (the `run_plan` function, ~lines 74-91)
- Test: `tests/integration/test_controlplane_analysis.py` (modify if present; else create a focused unit test below)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_plan_stage_waves.py
from cobol_modernizer.controlplane import analysis


class _FakeNeo:
    def run(self, q, **kw):
        return []


def test_run_plan_includes_delivery_waves(monkeypatch):
    # Three seams: S1 reads R, S2 writes R (so S2 depends on S1), S3 independent.
    cands = [
        {"program": "P1", "reads": ["R"], "writes": [], "score": {"weighted": 0.9}},
        {"program": "P2", "reads": [], "writes": ["R"], "score": {"weighted": 0.5}},
        {"program": "P3", "reads": [], "writes": [], "score": {"weighted": 0.7}},
    ]
    monkeypatch.setattr(analysis, "rank_candidates", lambda *a, **k: cands)

    class _WS:
        repo_slug = "demo"
    monkeypatch.setattr(analysis, "_workspace", lambda s, w: _WS())
    monkeypatch.setattr(analysis, "_mark_passed", lambda *a, **k: None)

    class _Sess:
        def flush(self):
            pass
    out = analysis.run_plan("wid", session=_Sess(), neo4j=_FakeNeo())
    assert out["acyclic"] is True
    assert "delivery_waves" in out
    # P2 (writer of R) depends on P1 (reader of R); P1 & P3 ship first.
    waves = out["delivery_waves"]
    assert "S1" in waves[0] and "S3" in waves[0]
    flat = [s for w in waves for s in w]
    assert sorted(flat) == ["S1", "S2", "S3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_plan_stage_waves.py -v`
Expected: FAIL with `KeyError: 'delivery_waves'`.

- [ ] **Step 3: Wire `delivery_waves` into `run_plan`**

In `src/cobol_modernizer/controlplane/analysis.py`, update the import line:

```python
from cobol_modernizer.planner.dag import delivery_waves, is_acyclic, topo_order
```

In `run_plan`, after `order = topo_order(dag) if acyclic else []`, add:

```python
    waves = delivery_waves(dag) if acyclic else []
```

And add `delivery_waves` to the returned dict:

```python
    return {
        "repo_slug": ws.repo_slug, "acyclic": acyclic, "topo_order": order,
        "delivery_waves": waves,
        "stories": [s.model_dump(mode="json") for s in dag.stories],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_plan_stage_waves.py -v`
Expected: PASS.

- [ ] **Step 5: Run the existing analysis tests to confirm no regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -k "analysis or plan or seam" -v`
Expected: PASS (existing tests unaffected — `delivery_waves` is additive).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/unit/test_plan_stage_waves.py
git commit -m "feat(plan): return delivery_waves alongside topo_order"
```

---

## Phase 2 — Enrichment foundation

### Task 3: Model + timeout resolution

**Files:**
- Create: `src/cobol_modernizer/enrichment/__init__.py`
- Create: `src/cobol_modernizer/enrichment/config.py`
- Test: `tests/unit/test_enrichment_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrichment_config.py
from cobol_modernizer.enrichment.config import enrich_model, enrich_timeout_s
from cobol_modernizer.cost.tiering import SONNET


def test_enrich_model_defaults_to_sonnet(monkeypatch):
    for k in ("SEAM_ENRICH_MODEL", "PLAN_ENRICH_MODEL", "DESIGN_ENRICH_MODEL",
              "COBOL_MOD_LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert enrich_model("seams") == SONNET
    assert enrich_model("plan") == SONNET
    assert enrich_model("design") == SONNET


def test_per_stage_env_overrides(monkeypatch):
    monkeypatch.setenv("SEAM_ENRICH_MODEL", "claude-haiku-4-5-20251001")
    assert enrich_model("seams") == "claude-haiku-4-5-20251001"


def test_global_pin_applies_when_no_stage_env(monkeypatch):
    monkeypatch.delenv("PLAN_ENRICH_MODEL", raising=False)
    monkeypatch.setenv("COBOL_MOD_LLM_MODEL", "claude-opus-4-8")
    assert enrich_model("plan") == "claude-opus-4-8"


def test_timeout_default_and_override(monkeypatch):
    monkeypatch.delenv("SEAMS_ENRICH_TIMEOUT_S", raising=False)
    assert enrich_timeout_s("seams") == 180.0
    monkeypatch.setenv("SEAMS_ENRICH_TIMEOUT_S", "30")
    assert enrich_timeout_s("seams") == 30.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cobol_modernizer.enrichment'`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/__init__.py
```
(empty file)

```python
# src/cobol_modernizer/enrichment/config.py
"""Model + timeout resolution for the LLM enrichment stages. Enrichment is
narrative (not a hard judgement) on a serial path, so it defaults to Sonnet — never
Opus. Per-stage env override wins, then the global model pin, then Sonnet."""
from __future__ import annotations

import os

from cobol_modernizer.cost.tiering import GLOBAL_ENV, SONNET

_MODEL_ENV = {"seams": "SEAM_ENRICH_MODEL", "plan": "PLAN_ENRICH_MODEL",
              "design": "DESIGN_ENRICH_MODEL"}


def enrich_model(stage: str) -> str:
    stage_env = _MODEL_ENV.get(stage, "")
    return (stage_env and os.getenv(stage_env)) or os.getenv(GLOBAL_ENV) or SONNET


def enrich_timeout_s(stage: str, default: float = 180.0) -> float:
    return float(os.getenv(f"{stage.upper()}_ENRICH_TIMEOUT_S", str(default)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/__init__.py src/cobol_modernizer/enrichment/config.py tests/unit/test_enrichment_config.py
git commit -m "feat(enrichment): model + timeout resolution (Sonnet default, env override)"
```

### Task 4: Shared batched-call + grounding helpers

**Files:**
- Create: `src/cobol_modernizer/enrichment/base.py`
- Test: `tests/unit/test_enrichment_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrichment_base.py
import asyncio

from cobol_modernizer.enrichment.base import ground_refs, run_batched


class _OkRunner:
    async def run_structured(self, **kw):
        return {"items": [{"x": 1}]}


class _HangRunner:
    async def run_structured(self, **kw):
        await asyncio.sleep(5)
        return {"never": True}


class _BoomRunner:
    async def run_structured(self, **kw):
        raise RuntimeError("api down")


def test_ground_refs_filters_to_known_and_flags():
    grounded, ok = ground_refs(["A", "B", "ghost"], {"A", "B"})
    assert grounded == ["A", "B"] and ok is False
    grounded, ok = ground_refs(["A"], {"A", "B"})
    assert grounded == ["A"] and ok is True
    grounded, ok = ground_refs([], {"A"})
    assert grounded == [] and ok is False  # nothing cited => not grounded


async def test_run_batched_passes_through_result():
    out = await run_batched(runner=_OkRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {"items": [{"x": 1}]}


async def test_run_batched_returns_empty_on_timeout():
    out = await run_batched(runner=_HangRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=0.05, label="t")
    assert out == {}


async def test_run_batched_returns_empty_on_error():
    out = await run_batched(runner=_BoomRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_base.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/base.py
"""Shared plumbing for the batched LLM enrichers: a timeout-guarded structured call
that NEVER raises (returns {} on timeout/error, so a stage degrades to
deterministic-only), and a groundedness filter for cited refs."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_batched(*, runner, system: str, prompt: str, schema: dict[str, Any],
                      model: str, timeout_s: float, label: str,
                      max_turns: int = 2) -> dict[str, Any]:
    """One batched structured-output call, tool-free, with a hard timeout. The
    harness already swallows its own errors to {}, but it has no timeout — wrap it so
    a hung subprocess can't hang the enrich job forever."""
    try:
        return await asyncio.wait_for(
            runner.run_structured(system=system, prompt=prompt, server=None,
                                  allowed_tools=[], model=model, max_turns=max_turns,
                                  schema=schema, label=label),
            timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("enrichment %s timed out after %.0fs", label, timeout_s)
        return {}
    except Exception:  # noqa: BLE001 — never let enrichment crash a stage
        logger.exception("enrichment %s failed", label)
        return {}


def ground_refs(cited: Any, known_refs: set[str]) -> tuple[list[str], bool]:
    """Keep only cited refs that exist in the graph; 'grounded' is True iff every
    cited ref was known AND at least one ref was cited (mirrors awrite_rationale)."""
    cited_list = [c for c in (cited or []) if isinstance(c, str)]
    grounded = [c for c in cited_list if c in known_refs]
    return grounded, (len(grounded) == len(cited_list) and len(cited_list) > 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_base.py -v`
Expected: PASS (4 tests; the async ones run under the repo's existing `asyncio_mode=auto` pytest config — confirm by the suite running without an explicit decorator, matching `test_brd_judge_groundedness.py`).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/base.py tests/unit/test_enrichment_base.py
git commit -m "feat(enrichment): timeout-guarded batched call + groundedness filter"
```

### Task 5: Enrichment contract schemas

**Files:**
- Create: `src/cobol_modernizer/enrichment/schema.py`
- Test: `tests/unit/test_enrichment_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrichment_schema.py
from cobol_modernizer.enrichment.schema import (
    DesignNarrative, PlanDeliveryNarrative, SeamNarrative, StoryNarrative,
)


def test_defaults_are_safe_empty():
    assert SeamNarrative(program="P").grounded is False
    assert StoryNarrative(story_id="S1").acceptance_criteria == []
    assert PlanDeliveryNarrative().edge_rationale == {}
    assert DesignNarrative(slice_id="x").adrs == []


def test_round_trips_to_json():
    sn = SeamNarrative(program="P", rationale="r", cited_refs=["P"], grounded=True)
    assert sn.model_dump()["program"] == "P"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_schema.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/schema.py
"""Pydantic contracts for the LLM enrichment payloads. These are returned BY ID
(program / story_id / slice_id) and merged into the deterministic output in the UI;
the deterministic schemas are never mutated."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SeamNarrative(BaseModel):
    program: str
    rationale: str = ""
    cited_refs: list[str] = Field(default_factory=list)
    grounded: bool = False


class StoryNarrative(BaseModel):
    story_id: str
    invest: dict[str, int] = Field(default_factory=dict)   # 6 dims, 1-5
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    groundedness_failures: list[str] = Field(default_factory=list)


class WaveNote(BaseModel):
    wave: int
    narrative: str = ""


class PlanDeliveryNarrative(BaseModel):
    edge_rationale: dict[str, str] = Field(default_factory=dict)   # "S3->S1" -> why
    wave_narrative: list[WaveNote] = Field(default_factory=list)


class DesignADR(BaseModel):
    number: int
    title: str
    context: str = ""
    decision: str = ""
    consequences: str = ""
    alternatives: str = ""


class DesignNarrative(BaseModel):
    slice_id: str
    adrs: list[DesignADR] = Field(default_factory=list)
    component_descriptions: list[str] = Field(default_factory=list)
    api_surface: str = ""
    data_model_notes: str = ""
    cited_refs: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrichment_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/schema.py tests/unit/test_enrichment_schema.py
git commit -m "feat(enrichment): pydantic contracts for narrative payloads"
```

---

## Phase 3 — Seam enricher + endpoints (proves the pattern end-to-end)

### Task 6: `enrich_seams`

**Files:**
- Create: `src/cobol_modernizer/enrichment/seams.py`
- Test: `tests/unit/test_enrich_seams.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrich_seams.py
from cobol_modernizer.enrichment.seams import enrich_seams

_CANDS = [
    {"program": "CBACT01M", "seam_type": "db_reader",
     "signals": {"risk": 0.2}, "score": {"weighted": 0.9},
     "evidence_map": {"reads": ["CBACT01M"]}},
    {"program": "CBPOST1M", "seam_type": "db_writer",
     "signals": {"risk": 0.8}, "score": {"weighted": 0.4},
     "evidence_map": {"writes": ["CBPOST1M"]}},
]


class _Runner:
    """Returns a batched result; one good ref, one hallucinated ref."""
    async def run_structured(self, **kw):
        return {"items": [
            {"program": "CBACT01M", "rationale": "reader, low risk",
             "cited_refs": ["CBACT01M"]},
            {"program": "CBPOST1M", "rationale": "writer, identity drift",
             "cited_refs": ["GHOST"]},
            {"program": "NOT_A_SEAM", "rationale": "noise", "cited_refs": []},
            "garbage-not-a-dict",
        ]}


async def test_enrich_seams_grounds_and_skips_garbage():
    out = await enrich_seams(_CANDS, {"CBACT01M", "CBPOST1M"},
                             runner=_Runner(), model="m", timeout_s=5)
    assert set(out) == {"CBACT01M", "CBPOST1M"}        # NOT_A_SEAM dropped (not a candidate)
    assert out["CBACT01M"]["grounded"] is True
    assert out["CBACT01M"]["cited_refs"] == ["CBACT01M"]
    assert out["CBPOST1M"]["grounded"] is False        # GHOST not in graph
    assert out["CBPOST1M"]["cited_refs"] == []          # hallucinated ref dropped


class _EmptyRunner:
    async def run_structured(self, **kw):
        return {}


async def test_enrich_seams_empty_on_no_llm_output():
    out = await enrich_seams(_CANDS, {"CBACT01M"}, runner=_EmptyRunner(),
                             model="m", timeout_s=5)
    assert out == {}                                    # degrade gracefully
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_seams.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/seams.py
"""Batched seam-rationale enrichment: ONE structured call explains WHY each
precomputed seam ranks where it does, grounded only in the provided evidence refs.
Generalizes seam/rationale.py:awrite_rationale from per-candidate to one batched call."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import ground_refs, run_batched
from cobol_modernizer.enrichment.schema import SeamNarrative

SEAMS_SYSTEM = (
    "You explain WHY each precomputed seam ranking is what it is. You DO NOT score. "
    "For EACH seam, write a 1-2 sentence rationale (why it ranks here + the main "
    "migration risk), grounded ONLY in the provided evidence refs. Cite the exact "
    "refs you used in 'cited_refs'. Do not invent identifiers. Return JSON: "
    '{"items":[{"program","rationale","cited_refs":[str]}...]}.'
)

SEAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object",
        "properties": {"program": {"type": "string"},
                       "rationale": {"type": "string"},
                       "cited_refs": {"type": "array", "items": {"type": "string"}}},
        "required": ["program"]}}},
    "required": ["items"],
}


async def enrich_seams(candidates: list[dict], known_refs: set[str], *,
                       runner, model: str, timeout_s: float) -> dict[str, dict]:
    if not candidates:
        return {}
    valid = {c["program"] for c in candidates if c.get("program")}
    payload = [{"program": c.get("program"), "seam_type": c.get("seam_type"),
                "signals": c.get("signals"), "score": c.get("score"),
                "evidence_map": c.get("evidence_map", {})} for c in candidates]
    prompt = ("## Precomputed seam candidates (signal scores + evidence)\n```json\n"
              + json.dumps(payload) + "\n```\nExplain each ranking using only its refs.")
    raw = await run_batched(runner=runner, system=SEAMS_SYSTEM, prompt=prompt,
                            schema=SEAMS_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-seams")
    out: dict[str, dict] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        prog = item.get("program")
        if not isinstance(prog, str) or prog not in valid:
            continue
        grounded_refs, grounded = ground_refs(item.get("cited_refs"), known_refs)
        out[prog] = SeamNarrative(program=prog,
                                  rationale=str(item.get("rationale", "")),
                                  cited_refs=grounded_refs,
                                  grounded=grounded).model_dump()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_seams.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/seams.py tests/unit/test_enrich_seams.py
git commit -m "feat(enrichment): batched seam rationale enricher (grounded)"
```

### Task 7: Seam enrich + enrichment endpoints

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py`
- Test: `tests/integration/test_controlplane_enrich.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_controlplane_enrich.py
"""Enrich endpoints: inject stub enrichers so wiring + job + poll + response shaping
are exercised without a live LLM or Neo4j. Mirrors test_controlplane_blueprint_api.py
(SQLite engine, dependency_overrides, jobs.runner.inline, fake Neo4j factory)."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import analysis, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class _FakeNeo4j:
    def run(self, query, **params):
        return []

    def close(self):
        pass


def _setup(monkeypatch):
    """Build a TestClient whose enrich background job runs inline against an in-memory
    SQLite session + a fake Neo4j. Returns the client; caller clears overrides."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="demo", created_by="x"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j()
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    monkeypatch.setattr(analysis, "_known_refs", lambda neo, slug: {"P1"})
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app)


def test_seams_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        monkeypatch.setattr(analysis, "rank_candidates",
                            lambda *a, **k: [{"program": "P1", "score": {"weighted": 1.0}}])

        async def _fake(cands, known, **kw):
            return {"P1": {"program": "P1", "rationale": "why",
                           "cited_refs": ["P1"], "grounded": True}}
        monkeypatch.setattr(analysis, "enrich_seams", _fake)

        assert c.post("/api/workspaces/ws-1/seams/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/seams/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["narratives"]["P1"]["rationale"] == "why"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_enrich.py -v`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Implement the endpoints**

In `src/cobol_modernizer/controlplane/analysis.py` add imports near the top:

```python
import asyncio
import os

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.enrichment.config import enrich_model, enrich_timeout_s
from cobol_modernizer.enrichment.seams import enrich_seams
```

Add these helpers (module level):

```python
_KNOWN_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"


def _known_refs(neo4j, slug: str) -> set[str]:
    return {r["q"] for r in neo4j.run(_KNOWN_REFS_Q, repo=slug)}


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None}
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error")}


def _require_llm() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — enrichment needs an LLM.")
```

Add the endpoints:

```python
@router.post("/workspaces/{wid}/seams/enrich", status_code=202)
def seams_enrich(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    """Kick off the (multi-minute) batched seam-rationale enrichment as a background
    job. Deterministic seams are unaffected; this only ADDS narrative."""
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            cands = rank_candidates(neo, repo=slug)
            known = _known_refs(neo, slug)
            runner = SdkAgentRunner()
            narratives = asyncio.run(enrich_seams(
                cands, known, runner=runner, model=enrich_model("seams"),
                timeout_s=enrich_timeout_s("seams")))
            return {"repo_slug": slug, "narratives": narratives,
                    "token_usage": dict(runner.token_usage)}
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("seams-enrich", wid, _job))


@router.get("/workspaces/{wid}/seams/enrichment")
def seams_enrichment(wid: str, session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    _workspace(session, wid)
    return _job_view(jobs.runner.get("seams-enrich", wid))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_enrich.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/integration/test_controlplane_enrich.py
git commit -m "feat(api): seams/enrich + seams/enrichment endpoints (background job)"
```

---

## Phase 4 — Plan enricher (per-story + delivery narrative)

### Task 8: `enrich_plan`

**Files:**
- Create: `src/cobol_modernizer/enrichment/plan.py`
- Test: `tests/unit/test_enrich_plan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrich_plan.py
from cobol_modernizer.enrichment.plan import enrich_plan

_STORIES = [
    {"id": "S1", "title": "Migrate P1", "seam": "P1", "depends_on": [],
     "evidence_map": {"seam": ["P1"]}},
    {"id": "S2", "title": "Migrate P2", "seam": "P2", "depends_on": ["S1"],
     "evidence_map": {"seam": ["GHOST"]}},
]
_WAVES = [["S1"], ["S2"]]


class _Runner:
    async def run_structured(self, **kw):
        return {
            "stories": [
                {"story_id": "S1", "invest": {"independent": 5, "negotiable": 4,
                  "valuable": 5, "estimable": 4, "small": 4, "testable": 5},
                 "description": "Extract P1 reader", "acceptance_criteria": ["AC1"]},
                {"story_id": "S2", "invest": {"independent": 3, "negotiable": 3,
                  "valuable": 5, "estimable": 5, "small": 3, "testable": 3},
                 "description": "Extract P2 writer", "acceptance_criteria": ["AC2"]},
            ],
            "edge_rationale": {"S2->S1": "P2 writes what P1 reads"},
            "wave_narrative": [{"wave": 0, "narrative": "ship readers first"},
                               {"wave": 1, "narrative": "then writers"}],
        }


async def test_enrich_plan_per_story_and_delivery():
    out = await enrich_plan(_STORIES, _WAVES, {"P1"}, runner=_Runner(),
                            model="m", timeout_s=5)
    # per-story
    assert out["stories"]["S1"]["description"] == "Extract P1 reader"
    assert out["stories"]["S1"]["invest"]["valuable"] == 5
    # groundedness floor: S2 cites GHOST (not in {"P1"}) -> valuable/estimable capped at 2
    assert out["stories"]["S2"]["invest"]["valuable"] == 2
    assert out["stories"]["S2"]["invest"]["estimable"] == 2
    assert out["stories"]["S2"]["groundedness_failures"] == ["GHOST"]
    # delivery
    assert out["delivery"]["edge_rationale"]["S2->S1"] == "P2 writes what P1 reads"
    assert out["delivery"]["wave_narrative"][0]["narrative"] == "ship readers first"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_plan.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/plan.py
"""Batched plan enrichment: per-story INVEST + description + acceptance criteria AND
a plan-level delivery narrative (dependency-edge rationale + per-wave guidance). One
structured call. Reuses the INVEST groundedness floor from planner/invest.py:
ungrounded evidence caps 'valuable'/'estimable' at 2."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import run_batched
from cobol_modernizer.enrichment.schema import (
    PlanDeliveryNarrative, StoryNarrative, WaveNote,
)

_DIMS = ("independent", "negotiable", "valuable", "estimable", "small", "testable")

PLAN_SYSTEM = (
    "You enrich a migration delivery plan. (1) For EACH story, score the six INVEST "
    "dimensions 1-5, write a 1-2 sentence description, and 1-3 acceptance criteria. "
    "(2) For the DELIVERY plan: explain each dependency edge (why it exists) and, for "
    "each wave, what it delivers / de-risks (readers-before-writers, blast radius). "
    "Ground value/estimate ONLY in the story's evidence refs. Return JSON: "
    '{"stories":[{"story_id","invest":{...6 dims...},"description","acceptance_criteria":[str]}...],'
    '"edge_rationale":{"S2->S1":str,...},"wave_narrative":[{"wave":int,"narrative":str}...]}.'
)

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stories": {"type": "array", "items": {"type": "object", "properties": {
            "story_id": {"type": "string"},
            "invest": {"type": "object",
                       "properties": {d: {"type": "integer"} for d in _DIMS}},
            "description": {"type": "string"},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}}},
            "required": ["story_id"]}},
        "edge_rationale": {"type": "object", "additionalProperties": {"type": "string"}},
        "wave_narrative": {"type": "array", "items": {"type": "object", "properties": {
            "wave": {"type": "integer"}, "narrative": {"type": "string"}}}},
    },
    "required": ["stories"],
}


def _coerce_invest(raw: Any) -> dict[str, int]:
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, int] = {}
    for d in _DIMS:
        try:
            out[d] = max(1, min(5, int(raw.get(d, 3))))
        except (TypeError, ValueError):
            out[d] = 3
    return out


async def enrich_plan(stories: list[dict], waves: list[list[str]],
                      known_refs: set[str], *, runner, model: str,
                      timeout_s: float) -> dict[str, Any]:
    if not stories:
        return {"stories": {}, "delivery": PlanDeliveryNarrative().model_dump()}
    valid = {s["id"] for s in stories if s.get("id")}
    # story_id -> its evidence refs (for the groundedness floor)
    refs_by_story = {s["id"]: [r for refs in (s.get("evidence_map") or {}).values()
                               for r in refs] for s in stories}
    prompt = ("## Stories\n```json\n" + json.dumps(stories) + "\n```\n"
              "## Delivery waves (parallel tracks)\n```json\n" + json.dumps(waves)
              + "\n```\nEnrich each story and the delivery plan.")
    raw = await run_batched(runner=runner, system=PLAN_SYSTEM, prompt=prompt,
                            schema=PLAN_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-plan")

    story_out: dict[str, dict] = {}
    for item in raw.get("stories", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("story_id")
        if not isinstance(sid, str) or sid not in valid:
            continue
        invest = _coerce_invest(item.get("invest"))
        failures = sorted({r for r in refs_by_story.get(sid, []) if r not in known_refs})
        if failures:                              # INVEST groundedness floor
            invest["valuable"] = min(invest["valuable"], 2)
            invest["estimable"] = min(invest["estimable"], 2)
        crit = [c for c in (item.get("acceptance_criteria") or []) if isinstance(c, str)]
        story_out[sid] = StoryNarrative(
            story_id=sid, invest=invest, description=str(item.get("description", "")),
            acceptance_criteria=crit, groundedness_failures=failures).model_dump()

    edges = {k: str(v) for k, v in (raw.get("edge_rationale") or {}).items()
             if isinstance(k, str) and isinstance(v, str)}
    notes = [WaveNote(wave=int(w.get("wave", 0)), narrative=str(w.get("narrative", "")))
             for w in (raw.get("wave_narrative") or []) if isinstance(w, dict)]
    delivery = PlanDeliveryNarrative(edge_rationale=edges, wave_narrative=notes)
    return {"stories": story_out, "delivery": delivery.model_dump()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/plan.py tests/unit/test_enrich_plan.py
git commit -m "feat(enrichment): batched plan enricher (INVEST + delivery narrative)"
```

### Task 9: Plan enrich + enrichment endpoints

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py`
- Test: `tests/integration/test_controlplane_enrich.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_controlplane_enrich.py`:

```python
def test_plan_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        monkeypatch.setattr(analysis, "rank_candidates",
                            lambda *a, **k: [{"program": "P1", "reads": [], "writes": [],
                                              "score": {"weighted": 1.0}}])

        async def _fake(stories, waves, known, **kw):
            return {"stories": {"S1": {"story_id": "S1", "description": "d"}},
                    "delivery": {"edge_rationale": {}, "wave_narrative": []}}
        monkeypatch.setattr(analysis, "enrich_plan", _fake)

        assert c.post("/api/workspaces/ws-1/plan/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/plan/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["stories"]["S1"]["description"] == "d"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_enrich.py::test_plan_enrich_runs_and_polls -v`
Expected: FAIL with 404.

- [ ] **Step 3: Implement**

In `analysis.py` add imports:

```python
from cobol_modernizer.enrichment.plan import enrich_plan
from cobol_modernizer.planner.dag import delivery_waves, is_acyclic, topo_order
from cobol_modernizer.planner.dependency import derive_dependencies, stories_from_seam_set
```
(the planner imports already exist — ensure `delivery_waves` is included from Task 2).

Add endpoints:

```python
@router.post("/workspaces/{wid}/plan/enrich", status_code=202)
def plan_enrich(wid: str, session: Session = Depends(get_session),
                neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            cands = rank_candidates(neo, repo=slug)
            stories = stories_from_seam_set(cands, repo_id=slug)
            dag = derive_dependencies(stories, cands, repo_id=slug)
            waves = delivery_waves(dag) if is_acyclic(dag) else []
            known = _known_refs(neo, slug)
            runner = SdkAgentRunner()
            result = asyncio.run(enrich_plan(
                [s.model_dump(mode="json") for s in dag.stories], waves, known,
                runner=runner, model=enrich_model("plan"),
                timeout_s=enrich_timeout_s("plan")))
            return {"repo_slug": slug, **result,
                    "token_usage": dict(runner.token_usage)}
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("plan-enrich", wid, _job))


@router.get("/workspaces/{wid}/plan/enrichment")
def plan_enrichment(wid: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    _workspace(session, wid)
    return _job_view(jobs.runner.get("plan-enrich", wid))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_enrich.py -v`
Expected: PASS (both seam + plan enrich tests).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/integration/test_controlplane_enrich.py
git commit -m "feat(api): plan/enrich + plan/enrichment endpoints"
```

---

## Phase 5 — Design enricher + endpoints

### Task 10: `enrich_design`

**Files:**
- Create: `src/cobol_modernizer/enrichment/design.py`
- Test: `tests/unit/test_enrich_design.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enrich_design.py
from cobol_modernizer.enrichment.design import enrich_design

_DESIGNS = [
    {"slice_id": "P1-slice", "context": "account_management",
     "owned_resources": ["ACCT-MASTER"], "components": ["P1Service", "P1Repository"],
     "evidence_map": {"DR-1": ["P1"]}},
]


class _Runner:
    async def run_structured(self, **kw):
        return {"items": [{
            "slice_id": "P1-slice",
            "adrs": [{"number": 1, "title": "Single writer", "context": "c",
                      "decision": "d", "consequences": "q", "alternatives": "a"}],
            "component_descriptions": ["P1Service handles posting"],
            "api_surface": "POST /accounts", "data_model_notes": "ACCT-MASTER -> Account",
            "cited_refs": ["P1", "GHOST"]}]}


async def test_enrich_design_grounds_and_maps_by_slice():
    out = await enrich_design(_DESIGNS, {"P1"}, runner=_Runner(),
                              model="m", timeout_s=5)
    d = out["P1-slice"]
    assert d["adrs"][0]["alternatives"] == "a"
    assert d["api_surface"] == "POST /accounts"
    assert d["cited_refs"] == ["P1"]            # GHOST dropped (not in graph)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_design.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/enrichment/design.py
"""Batched design enrichment (net-new — no prior LLM design path): for each writer
slice, elaborate the template ADRs (richer context/decision/consequences +
alternatives), describe the Java components, sketch the API surface, and note the data
model — grounded in the slice's owned resources + program refs."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import ground_refs, run_batched
from cobol_modernizer.enrichment.schema import DesignADR, DesignNarrative

DESIGN_SYSTEM = (
    "You elaborate a precomputed service design for EACH writer slice. For each slice: "
    "expand its ADRs (context, decision, consequences, alternatives), describe each "
    "Java component's responsibility, sketch the API surface, and note how the owned "
    "mainframe resources map to the data model. Ground everything ONLY in the slice's "
    "owned_resources + evidence refs; cite refs in 'cited_refs'; invent no identifiers. "
    'Return JSON: {"items":[{"slice_id","adrs":[{"number","title","context","decision",'
    '"consequences","alternatives"}],"component_descriptions":[str],"api_surface",'
    '"data_model_notes","cited_refs":[str]}...]}.'
)

DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "slice_id": {"type": "string"},
        "adrs": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer"}, "title": {"type": "string"},
            "context": {"type": "string"}, "decision": {"type": "string"},
            "consequences": {"type": "string"}, "alternatives": {"type": "string"}},
            "required": ["number", "title"]}},
        "component_descriptions": {"type": "array", "items": {"type": "string"}},
        "api_surface": {"type": "string"}, "data_model_notes": {"type": "string"},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
        "required": ["slice_id"]}}},
    "required": ["items"],
}


def _parse_adrs(raw: Any) -> list[DesignADR]:
    out: list[DesignADR] = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        try:
            num = int(a.get("number"))
        except (TypeError, ValueError):
            continue
        title = a.get("title")
        if not isinstance(title, str):
            continue
        out.append(DesignADR(number=num, title=title,
                             context=str(a.get("context", "")),
                             decision=str(a.get("decision", "")),
                             consequences=str(a.get("consequences", "")),
                             alternatives=str(a.get("alternatives", ""))))
    return out


async def enrich_design(designs: list[dict], known_refs: set[str], *,
                        runner, model: str, timeout_s: float) -> dict[str, dict]:
    if not designs:
        return {}
    valid = {d["slice_id"] for d in designs if d.get("slice_id")}
    prompt = ("## Precomputed writer-slice designs\n```json\n" + json.dumps(designs)
              + "\n```\nElaborate each slice grounded only in its resources/refs.")
    raw = await run_batched(runner=runner, system=DESIGN_SYSTEM, prompt=prompt,
                            schema=DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-design")
    out: dict[str, dict] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("slice_id")
        if not isinstance(sid, str) or sid not in valid:
            continue
        cited, _grounded = ground_refs(item.get("cited_refs"), known_refs)
        comps = [c for c in (item.get("component_descriptions") or [])
                 if isinstance(c, str)]
        out[sid] = DesignNarrative(
            slice_id=sid, adrs=_parse_adrs(item.get("adrs")),
            component_descriptions=comps,
            api_surface=str(item.get("api_surface", "")),
            data_model_notes=str(item.get("data_model_notes", "")),
            cited_refs=cited).model_dump()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_enrich_design.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/enrichment/design.py tests/unit/test_enrich_design.py
git commit -m "feat(enrichment): batched design enricher (ADRs/components/API/data model)"
```

### Task 11: Design enrich + enrichment endpoints

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py`
- Test: `tests/integration/test_controlplane_enrich.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_controlplane_enrich.py`:

```python
def test_design_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        # Stub the deterministic design computation to a single slice.
        monkeypatch.setattr(analysis, "_compute_designs",
                            lambda neo, slug: [{"slice_id": "P1-slice",
                                                "owned_resources": ["R"],
                                                "evidence_map": {"DR-1": ["P1"]}}])

        async def _fake(designs, known, **kw):
            return {"P1-slice": {"slice_id": "P1-slice", "api_surface": "GET /x"}}
        monkeypatch.setattr(analysis, "enrich_design", _fake)

        assert c.post("/api/workspaces/ws-1/design/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/design/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["narratives"]["P1-slice"]["api_surface"] == "GET /x"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Refactor the deterministic design compute into `_compute_designs`**

The current `run_design` (analysis.py) computes the per-slice designs inline. Extract
that loop into a module-level helper so the enrich job can reuse it without the FastAPI
response shaping. In `analysis.py`:

```python
def _compute_designs(neo4j, slug: str) -> list[dict]:
    """The deterministic per-writer-slice design list (the same data run_design
    returns under 'designs'). Extracted so the enrich job can reuse it."""
    rows = neo4j.run(_WRITES_BY_PROGRAM, repo=slug)
    known_refs = _known_refs(neo4j, slug)
    writes_by_program = {r["program"]: [w for w in (r.get("writes") or []) if w]
                         for r in rows}
    if not known_refs:
        raise HTTPException(status_code=409,
                            detail="no graph — run the Parse stage first")
    writers_of: dict[str, list[str]] = {}
    for prog, res_list in writes_by_program.items():
        for res in res_list:
            writers_of.setdefault(res, []).append(prog)
    adapter = _WriterAdapter(writes_by_program)
    designs: list[dict] = []
    for prog in sorted(p for p, w in writes_by_program.items() if w):
        owned = sorted(set(writes_by_program[prog]))
        try:
            context = assign_context(adapter, prog)
        except ValueError:
            continue
        external = {res: [w for w in writers_of.get(res, []) if w != prog]
                    for res in owned if any(w != prog for w in writers_of.get(res, []))}
        design = ServiceDesign(
            slice_id=f"{prog}-slice", context=BoundedContext(context),
            owned_resources=owned, transition_pattern="extract_product_lines+legacy_mimic",
            components=[f"{prog}Service", f"{prog}Repository"],
            evidence_map={"DR-1": [prog]})
        adrs = default_adrs_for_writer_slice(slice_id=design.slice_id,
                                             owned_resources=owned, evidence_refs=[prog])
        report = judge_design(design, known_refs=known_refs, external_writers=external)
        designs.append({
            "design": design.model_dump(mode="json"),
            "adrs": [a.model_dump(mode="json") for a in adrs],
            "rating": report.rating, "data_ownership_ok": report.data_ownership_ok,
            "groundedness_failures": report.groundedness_failures,
            "rationale": report.rationale,
        })
    return designs
```

Then change `run_design` to delegate: replace its inline computation with
`designs = _compute_designs(neo4j, ws.repo_slug)` (keep the `_mark_passed` + return).
Run the existing design test to confirm the refactor is behavior-preserving:

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -k "design" -v`
Expected: PASS (refactor is pure extraction).

- [ ] **Step 3: Add the endpoints**

```python
from cobol_modernizer.enrichment.design import enrich_design


@router.post("/workspaces/{wid}/design/enrich", status_code=202)
def design_enrich(wid: str, session: Session = Depends(get_session),
                  neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            designs = _compute_designs(neo, slug)        # the deterministic slices
            known = _known_refs(neo, slug)
            runner = SdkAgentRunner()
            narratives = asyncio.run(enrich_design(
                designs, known, runner=runner, model=enrich_model("design"),
                timeout_s=enrich_timeout_s("design")))
            return {"repo_slug": slug, "narratives": narratives,
                    "token_usage": dict(runner.token_usage)}
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("design-enrich", wid, _job))


@router.get("/workspaces/{wid}/design/enrichment")
def design_enrichment(wid: str, session: Session = Depends(get_session),
                      neo4j=Depends(get_neo4j)) -> dict:
    _workspace(session, wid)
    return _job_view(jobs.runner.get("design-enrich", wid))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_enrich.py tests/ -k "design or enrich" -v`
Expected: PASS (all three enrich endpoints + design refactor).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/integration/test_controlplane_enrich.py
git commit -m "feat(api): design/enrich + design/enrichment endpoints (+ extract _compute_designs)"
```

### Task 12: Full backend regression

- [ ] **Step 1: Run the whole Python unit + the enrich integration suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/integration/test_controlplane_enrich.py -q`
Expected: PASS (all green; no regressions in the deterministic stages).

- [ ] **Step 2: Commit (only if any fixups were needed)**

```bash
git add -A && git commit -m "test: backend enrichment regression green"
```

---

## Phase 6 — Frontend (merge enrichment into the three screens)

### Task 13: API client helpers + types

**Files:**
- Modify: `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts` (extend)

- [ ] **Step 1: Write the failing test**

Add to `web/src/lib/api.test.ts` (follow the existing test style in that file for how
`api` methods are asserted against MSW handlers):

```ts
import { api } from "@/lib/api";

describe("enrichment api", () => {
  it("builds enrich + enrichment paths per stage", () => {
    // these helpers POST to /{stage}/enrich and GET /{stage}/enrichment
    expect(typeof api.startSeamsEnrich).toBe("function");
    expect(typeof api.getSeamsEnrichment).toBe("function");
    expect(typeof api.startPlanEnrich).toBe("function");
    expect(typeof api.getPlanEnrichment).toBe("function");
    expect(typeof api.startDesignEnrich).toBe("function");
    expect(typeof api.getDesignEnrichment).toBe("function");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL (`api.startSeamsEnrich is not a function`).

- [ ] **Step 3: Implement the helpers + types**

In `web/src/lib/api.ts`, add types near the other result types:

```ts
export interface SeamNarrative { program: string; rationale: string; cited_refs: string[]; grounded: boolean }
export interface StoryNarrative { story_id: string; invest: Record<string, number>; description: string; acceptance_criteria: string[]; groundedness_failures: string[] }
export interface PlanDelivery { edge_rationale: Record<string, string>; wave_narrative: { wave: number; narrative: string }[] }
export interface DesignADRNarrative { number: number; title: string; context: string; decision: string; consequences: string; alternatives: string }
export interface DesignNarrative { slice_id: string; adrs: DesignADRNarrative[]; component_descriptions: string[]; api_surface: string; data_model_notes: string; cited_refs: string[] }
```

The file already exposes a single `json<T>(url, init?)` helper (`api.ts:7-14`) and
`startBlueprint`/`getBlueprintStatus` use it (`api.ts:206-209`). Define a job result
type and follow that exact shape. Add near the other job types:

```ts
// enrichment jobs return {status, result, error}; result shape per stage below
export interface SeamsEnrichResult { repo_slug: string; narratives: Record<string, SeamNarrative>; token_usage?: Record<string, number> }
export interface PlanEnrichResult { repo_slug: string; stories: Record<string, StoryNarrative>; delivery: PlanDelivery; token_usage?: Record<string, number> }
export interface DesignEnrichResult { repo_slug: string; narratives: Record<string, DesignNarrative>; token_usage?: Record<string, number> }
export interface EnrichJob<T> { status: JobStatus; result: T | null; error: string | null }
```

Add methods to the `api` object, mirroring `startBlueprint`/`getBlueprintStatus`
exactly (POST starts the job, bare GET polls it; both via `json<T>`):

```ts
  startSeamsEnrich: (id: string) =>
    json<EnrichJob<SeamsEnrichResult>>(`/api/workspaces/${id}/seams/enrich`, { method: "POST" }),
  getSeamsEnrichment: (id: string) =>
    json<EnrichJob<SeamsEnrichResult>>(`/api/workspaces/${id}/seams/enrichment`),
  startPlanEnrich: (id: string) =>
    json<EnrichJob<PlanEnrichResult>>(`/api/workspaces/${id}/plan/enrich`, { method: "POST" }),
  getPlanEnrichment: (id: string) =>
    json<EnrichJob<PlanEnrichResult>>(`/api/workspaces/${id}/plan/enrichment`),
  startDesignEnrich: (id: string) =>
    json<EnrichJob<DesignEnrichResult>>(`/api/workspaces/${id}/design/enrich`, { method: "POST" }),
  getDesignEnrichment: (id: string) =>
    json<EnrichJob<DesignEnrichResult>>(`/api/workspaces/${id}/design/enrichment`),
```

> `JobStatus` is the same union `useJob`/blueprint already use. The `EnrichJob<T>`
> shape matches what `useJob<T>` expects (`{status, result, error}`), so the screens
> consume these unchanged.

- [ ] **Step 4: Run test + typecheck**

Run: `cd web && npx vitest run src/lib/api.test.ts && npx tsc --noEmit`
Expected: PASS + no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): enrichment api client helpers + types"
```

### Task 14: SeamStudio — "Add detail" + rationale merge

**Files:**
- Modify: `web/src/components/screens/SeamStudio.tsx`
- Test: `web/src/components/screens/SeamStudio.test.tsx` (extend) + MSW handler in `web/src/test/msw/handlers.ts`

- [ ] **Step 1: Add MSW handlers**

In `web/src/test/msw/handlers.ts`, add handlers for the seam enrich endpoints that
return a `done` job with one narrative (follow the existing blueprint handler pattern):

```ts
http.post("*/api/workspaces/:id/seams/enrich", () =>
  HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
http.get("*/api/workspaces/:id/seams/enrichment", () =>
  HttpResponse.json({ status: "done", error: null, result: { narratives: {
    CBACT01M: { program: "CBACT01M", rationale: "reader, low risk", cited_refs: ["CBACT01M"], grounded: true },
  } } })),
```

- [ ] **Step 2: Write the failing test**

Extend `SeamStudio.test.tsx` (mirror BlueprintStudio.test.tsx structure):

```tsx
it("shows rationale after clicking Add detail", async () => {
  render(<SeamStudio workspaceId="w1" />);
  // (assume seams already loaded via the existing test setup)
  fireEvent.click(await screen.findByRole("button", { name: /add detail/i }));
  expect(await screen.findByText(/reader, low risk/i)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/SeamStudio.test.tsx`
Expected: FAIL (no "Add detail" button / rationale not rendered).

- [ ] **Step 4: Implement**

In `SeamStudio.tsx`: add a `useJob` for enrichment driven by `api.startSeamsEnrich` /
`api.getSeamsEnrichment`, an "Add detail" button (disabled while `busy`, label
"Enriching…"), and merge `result.narratives[program]` into each row — render the
`rationale` under the program with a small warning badge when `grounded === false`.

```tsx
const enrich = useJob<{ narratives: Record<string, SeamNarrative> }>(
  () => api.startSeamsEnrich(workspaceId),
  () => api.getSeamsEnrichment(workspaceId),
);
const narr = enrich.result?.narratives ?? {};
// ...button:
<button onClick={enrich.run} disabled={enrich.busy}>
  {enrich.busy ? "Enriching…" : "Add detail"}
</button>
// ...inside each candidate row:
{narr[c.program] && (
  <p className="text-xs text-zinc-400">
    {narr[c.program].rationale}
    {!narr[c.program].grounded && <span className="ml-1 text-amber-500">⚠ ungrounded</span>}
  </p>
)}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/screens/SeamStudio.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/screens/SeamStudio.tsx web/src/components/screens/SeamStudio.test.tsx web/src/test/msw/handlers.ts
git commit -m "feat(web): seam rationale enrichment in SeamStudio"
```

### Task 15: IncrementPlanner — delivery waves + per-story detail

**Files:**
- Modify: `web/src/components/screens/IncrementPlanner.tsx`
- Test: `web/src/components/screens/IncrementPlanner.test.tsx` (extend) + handlers

- [ ] **Step 1: Add MSW handlers** for `plan/enrich` (202) and `plan/enrichment`
  (`done` with `stories` + `delivery`), mirroring Task 14's pattern. Also ensure the
  base `plan` handler returns `delivery_waves` (e.g. `[["S1"],["S2"]]`).

- [ ] **Step 2: Write the failing test**

```tsx
it("renders delivery waves and wave narrative", async () => {
  render(<IncrementPlanner workspaceId="w1" />);
  expect(await screen.findByText(/wave 1/i)).toBeInTheDocument();   // from delivery_waves
  fireEvent.click(await screen.findByRole("button", { name: /add detail/i }));
  expect(await screen.findByText(/ship readers first/i)).toBeInTheDocument();  // wave_narrative
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/IncrementPlanner.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `IncrementPlanner.tsx`:
- Read `delivery_waves` from the plan result; render stories grouped by wave
  ("Wave 1 — parallel: S1, S3", etc.) instead of the flat list, showing each story's
  `depends_on`.
- Add a `useJob` for `api.startPlanEnrich`/`api.getPlanEnrichment` + "Add detail" button.
- Merge `result.stories[id]` (INVEST bars + `description` + `acceptance_criteria`) into
  each story, and `result.delivery.wave_narrative[w]` under each wave header,
  `result.delivery.edge_rationale["S2->S1"]` next to each dependency edge.

```tsx
const enrich = useJob<{ stories: Record<string, StoryNarrative>; delivery: PlanDelivery }>(
  () => api.startPlanEnrich(workspaceId),
  () => api.getPlanEnrichment(workspaceId),
);
const waves: string[][] = planResult?.delivery_waves ?? [];
// render: waves.map((ids, wi) => <section> Wave {wi+1} ... {enrich.result?.delivery.wave_narrative.find(n => n.wave===wi)?.narrative} </section>)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/screens/IncrementPlanner.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/screens/IncrementPlanner.tsx web/src/components/screens/IncrementPlanner.test.tsx web/src/test/msw/handlers.ts
git commit -m "feat(web): delivery-wave plan view + per-story enrichment"
```

### Task 16: DesignStudio — elaborated ADRs / components / API / data model

**Files:**
- Modify: `web/src/components/screens/DesignStudio.tsx`
- Test: `web/src/components/screens/DesignStudio.test.tsx` (extend) + handlers

- [ ] **Step 1: Add MSW handlers** for `design/enrich` (202) and `design/enrichment`
  (`done` with `narratives` keyed by `slice_id`, mirroring Task 14).

- [ ] **Step 2: Write the failing test**

```tsx
it("shows elaborated ADRs and API surface after Add detail", async () => {
  render(<DesignStudio workspaceId="w1" />);
  fireEvent.click(await screen.findByRole("button", { name: /add detail/i }));
  expect(await screen.findByText(/POST \/accounts/i)).toBeInTheDocument();  // api_surface
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/DesignStudio.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `DesignStudio.tsx`: add a `useJob` for `api.startDesignEnrich`/`api.getDesignEnrichment`
+ "Add detail" button; merge `result.narratives[slice_id]` into each design card —
render the elaborated ADR `context`/`consequences`/`alternatives` (currently dropped),
`component_descriptions`, `api_surface`, and `data_model_notes`. Show a warning badge
when an ADR/slice has no grounded `cited_refs`.

```tsx
const enrich = useJob<{ narratives: Record<string, DesignNarrative> }>(
  () => api.startDesignEnrich(workspaceId),
  () => api.getDesignEnrichment(workspaceId),
);
const narr = enrich.result?.narratives ?? {};
// inside each design card keyed by d.design.slice_id, render narr[d.design.slice_id] fields
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/screens/DesignStudio.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/screens/DesignStudio.tsx web/src/components/screens/DesignStudio.test.tsx web/src/test/msw/handlers.ts
git commit -m "feat(web): design ADR/component/API enrichment in DesignStudio"
```

### Task 17: Full frontend regression + typecheck

- [ ] **Step 1: Run the whole web suite + tsc**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS (all suites), no type errors.

- [ ] **Step 2: Commit (only if fixups needed)**

```bash
git add -A && git commit -m "test(web): enrichment frontend regression green"
```

---

## Final verification

- [ ] **Step 1: Full Python suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/integration -q`
Expected: PASS.

- [ ] **Step 2: Full web suite + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx next build`
Expected: PASS / build succeeds.

- [ ] **Step 3 (optional, requires Neo4j + ANTHROPIC_API_KEY): live smoke**

With a parsed repo (e.g. `carddemo-mini`), exercise one enrich end-to-end and confirm
the timing/grounding logs look sane and the stage still returns deterministic output
when `ANTHROPIC_API_KEY` is unset (graceful degradation).

---

## Notes for the implementer

- **Augment, never replace:** the deterministic POST endpoints (`run_seams`, `run_plan`,
  `run_design`) must keep working unchanged. Enrichment is strictly additive; if any
  enrich job fails/times out, the screen shows deterministic-only.
- **Grounding is mandatory:** never merge a cited ref that isn't in `known_refs` into
  displayed evidence; flag ungrounded items with a badge.
- **Defensive parsing:** every enricher must skip malformed rows and never raise —
  mirror `agent/brd_judge.py`'s `_norm_*`/`_parse_*` discipline (already applied above).
- **No new persistence:** enrichment lives in the in-memory `jobs.runner` result, like
  blueprint/build. On restart it's simply re-run.
- **Don't auto-trigger:** enrichment is user-initiated via the "Add detail" button.
```
