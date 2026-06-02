# Thoughtworks-Aligned Modernization — End-to-End Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built Thoughtworks-aligned artifacts (backlog, coverage, technical design, gates) into a running end-to-end chain with cockpit UI, so `graph → BRD → coverage → backlog → domain → technical design → codegen → equivalence` is generated, persisted, consumed, and gated at runtime.

**Architecture:** Add two versioned Neo4j artifacts (`:Backlog`, `:TechnicalDesign`) with storage classes mirroring `DomainDesignStorage`; turn the backlog/technical-design stubs into full generation stages modeled on `blueprint.py` (fast precheck → `JobRunner` background LLM job → persist → upsert gate); feed the persisted backlog into domain decomposition and the codegen brief; add blocking-with-override gates (coverage, story-behavior) using the existing `Gate`/`waived_with_risk` mechanism; surface everything in the Next.js cockpit.

**Tech Stack:** FastAPI control-plane routers, Neo4j (`neo4j` driver), SQLAlchemy `Gate`/`JourneyStage`, Pydantic schemas, `cobol_modernizer.agent.harness.SdkAgentRunner` + `enrichment.base.run_batched`, pytest, Next.js 15 / React 19 / Vitest / MSW.

---

## Design reference

Spec: `docs/superpowers/specs/2026-06-02-thoughtworks-e2e-integration-design.md`.

**Approved decisions:** full e2e incl. UI; gates block with override; new `backlog` journey stage after Blueprint; LLM technical-design generator; technical design **replaces** the `design` stage (legacy writer-slice retired); gates wired Coverage→Blueprint, Coverage→Backlog, Story-behavior→Verify; `BACKLOG_COVERAGE_MIN` default `0.8`.

## Existing pieces this plan reuses (do not recreate)

- `src/cobol_modernizer/backlog/schema.py` — `Epic`, `UserStory`, `AcceptanceCriterion`, `Backlog`.
- `src/cobol_modernizer/backlog/generator.py` — `BACKLOG_SYSTEM`, `parse_backlog_payload(raw, *, repo_slug, known_refs, known_requirement_ids)`.
- `src/cobol_modernizer/backlog/dependency.py` — `derive_story_dependencies(stories, seam_candidates, *, repo_slug) -> BacklogDAG`.
- `src/cobol_modernizer/traceability/coverage.py` — `brd_logic_coverage(neo4j, repo_slug, brd_sections, evidence_map, exclusions=None) -> LogicCoverageReport`.
- `src/cobol_modernizer/technical_design/schema.py` — `TechnicalDesign`, `TechnicalService`, `ApiContract`, `PersistenceDesign`, `IntegrationContract`.
- `src/cobol_modernizer/slice/gates.py` — `story_behavior_gate(*, story_id, acceptance_criteria_ids, generated_test_refs, equivalence_verdict) -> dict`.
- `src/cobol_modernizer/controlplane/jobs.py` — `runner` (`JobRunner`), `make_session()`, `make_neo4j()`.
- `src/cobol_modernizer/controlplane/build.py` — `_backlog_brief`, `_technical_design_brief`, `_codegen_brief` (readers already query `:Backlog`/`:TechnicalDesign`).
- `src/cobol_modernizer/seam/service.py` — `rank_candidates(client, *, repo, limit=20) -> list[dict]` (each dict has `program`, `reads`, `writes`, `score`).
- `src/cobol_modernizer/enrichment/base.py` — `run_batched(*, runner, system, prompt, schema, model, timeout_s, label) -> dict` (never raises; `{}` on error).
- `src/cobol_modernizer/controlplane/domain.py` — `DomainDesignStorage`, `run_domain_design(..., backlog_json="")`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/cobol_modernizer/controlplane/gates_util.py` (create) | `upsert_gate(session, workspace_id, stage_key, gate_key, *, passed, result, threshold)` — one place that creates/updates a `Gate` row + sets status. |
| `src/cobol_modernizer/backlog/storage.py` (create) | `BacklogStorage` — versioned `:Backlog` save/get-latest, mirrors `DomainDesignStorage`. |
| `src/cobol_modernizer/backlog/render.py` (create) | `render_html(backlog, coverage) -> str` — self-contained HTML. |
| `src/cobol_modernizer/backlog/generator.py` (modify) | add `BACKLOG_SCHEMA`, `build_backlog_prompt`, `generate_backlog_payload` (async LLM round-trip). |
| `src/cobol_modernizer/controlplane/backlog.py` (rewrite) | Full backlog stage: POST job, GET status, GET html; runs generator→parser→DAG→coverage→storage; upserts `backlog_coverage` + `brd_logic_coverage` gates. |
| `src/cobol_modernizer/controlplane/analysis.py` (modify) | `_domain_run_and_persist` reads persisted backlog → passes `backlog_json`; remove legacy `/design` writer-slice route. |
| `src/cobol_modernizer/technical_design/generator.py` (create) | `TECHNICAL_DESIGN_SYSTEM`, `TECHNICAL_DESIGN_SCHEMA`, `build_technical_design_prompt`, `parse_technical_design_payload`, `generate_technical_design_payload`. |
| `src/cobol_modernizer/technical_design/storage.py` (create) | `TechnicalDesignStorage` — versioned `:TechnicalDesign` save/get-latest. |
| `src/cobol_modernizer/technical_design/render.py` (create) | `render_html(design) -> str`. |
| `src/cobol_modernizer/controlplane/technical_design.py` (create) | Technical-design stage POST/GET/html; rewires the `design` stage; upserts `design_data_ownership` gate. |
| `src/cobol_modernizer/controlplane/__init__.py` (modify) | include technical-design router. |
| `src/cobol_modernizer/controlplane/stages.py` (modify) | insert `backlog` stage; relabel `design` gate stays. |
| `src/cobol_modernizer/controlplane/build.py` (modify) | record `generated_test_refs` artifact after codegen. |
| `src/cobol_modernizer/controlplane/verify.py` (modify) | compute `story_behavior` gate after equivalence. |
| `web/src/lib/stages.ts` (modify) | mirror new `backlog` stage. |
| `web/src/components/screens/StageScreen.tsx` (modify) | add `case "backlog"`. |
| `web/src/components/screens/BacklogStudio.tsx` (create) | backlog screen. |
| `web/src/components/screens/DesignStudio.tsx` (modify) | render technical design. |
| `web/src/lib/api.ts` (modify) | backlog + technical-design fetchers/types. |
| `web/src/test/handlers.ts` (modify) | MSW mocks. |

---

## Task 1: Insert the `backlog` journey stage

**Files:**
- Modify: `src/cobol_modernizer/controlplane/stages.py`
- Test: `tests/unit/test_stages_backlog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stages_backlog.py
from cobol_modernizer.controlplane.stages import JOURNEY_STAGES, gate_key_for


def test_backlog_stage_exists_between_blueprint_and_seams():
    keys = [s.key for s in JOURNEY_STAGES]
    assert keys.index("backlog") == keys.index("blueprint") + 1
    assert keys.index("backlog") == keys.index("seams") - 1


def test_backlog_stage_has_coverage_gate():
    assert gate_key_for("backlog") == "backlog_coverage"


def test_ordinals_are_contiguous_and_unique():
    ords = [s.ordinal for s in JOURNEY_STAGES]
    assert ords == list(range(len(JOURNEY_STAGES)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stages_backlog.py -q`
Expected: FAIL — no `backlog` stage; ordinals not contiguous after insert.

- [ ] **Step 3: Insert the stage and renumber ordinals**

In `src/cobol_modernizer/controlplane/stages.py`, replace the `JOURNEY_STAGES` list with:

```python
JOURNEY_STAGES: list[StageDef] = [
    StageDef("outcome", "Outcome", 0, None),
    StageDef("intake", "Intake", 1, None),
    StageDef("parse", "Parse", 2, "parse"),
    StageDef("graph", "Graph", 3, "graph"),
    StageDef("explore", "Explore", 4, None),
    StageDef("blueprint", "Blueprint", 5, "brd_groundedness"),
    StageDef("backlog", "Backlog", 6, "backlog_coverage"),
    StageDef("seams", "Seams", 7, None),
    StageDef("plan", "Plan", 8, "stories_dag"),
    StageDef("domain", "Domain Design", 9, None),
    StageDef("design", "Design", 10, "design_data_ownership"),
    StageDef("build", "Build", 11, "code"),
    StageDef("verify", "Verify", 12, "equivalence"),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stages_backlog.py -q`
Expected: PASS.

- [ ] **Step 5: Fix the seed test that asserts stage count**

Run: `uv run pytest tests/ -q -k "seed or stages" 2>&1 | tail -20`
If a test asserts "11 journey stages" or a specific count/ordinal, update the expected count to `13` and any hardcoded ordinals (blueprint stays 5; seams→7, plan→8, domain→9, design→10, build→11, verify→12). Update the docstring comment in `seed.py` line 4 from "11 journey stages" to "13 journey stages".

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/stages.py tests/unit/test_stages_backlog.py src/cobol_modernizer/controlplane/seed.py
git commit -m "feat: add backlog journey stage between blueprint and seams"
```

---

## Task 2: Shared gate upsert helper

**Files:**
- Create: `src/cobol_modernizer/controlplane/gates_util.py`
- Test: `tests/unit/test_gates_util.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gates_util.py
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Workspace(id="ws-1", name="m", repo_slug="r", created_by="t"))
    s.add(JourneyStage(workspace_id="ws-1", stage_key="backlog", ordinal=6, status="running"))
    s.commit()
    return s


def test_upsert_gate_creates_then_updates_same_row():
    s = _session()
    g1 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage",
                     passed=False, result={"coverage_ratio": 0.5}, threshold={"min": 0.8})
    s.flush()
    assert g1.status == "open"
    g2 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage",
                     passed=True, result={"coverage_ratio": 0.9}, threshold={"min": 0.8})
    s.flush()
    assert g2.id == g1.id  # same row, not a duplicate
    assert g2.status == "passed"
    rows = s.execute(select(Gate).where(Gate.gate_key == "backlog_coverage")).scalars().all()
    assert len(rows) == 1


def test_upsert_gate_preserves_waived_status():
    s = _session()
    g = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=False, result={}, threshold={})
    g.status = "waived"
    s.flush()
    g2 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=False, result={"x": 1}, threshold={})
    s.flush()
    assert g2.status == "waived"  # an explicit human waiver is never silently reverted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_gates_util.py -q`
Expected: FAIL — `ModuleNotFoundError: cobol_modernizer.controlplane.gates_util`.

- [ ] **Step 3: Implement the helper**

```python
# src/cobol_modernizer/controlplane/gates_util.py
"""Create-or-update a Gate row keyed by (workspace_id, gate_key), used by the
generation stages to publish a deterministic gate verdict. A gate the user has
explicitly resolved (passed/failed/waived via the approval route) is never silently
flipped back to open by a re-run — only its `result` payload refreshes."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import Gate, JourneyStage

_HUMAN_RESOLVED = {"passed", "failed", "waived"}


def _stage_id(session: Session, workspace_id: str, stage_key: str) -> str | None:
    row = session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == workspace_id,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().first()
    return row.id if row else None


def upsert_gate(session: Session, workspace_id: str, stage_key: str, gate_key: str,
                *, passed: bool, result: dict[str, Any], threshold: dict[str, Any]) -> Gate:
    gate = session.execute(
        select(Gate).where(Gate.workspace_id == workspace_id, Gate.gate_key == gate_key)
    ).scalars().first()
    computed = "passed" if passed else "open"
    if gate is None:
        gate = Gate(workspace_id=workspace_id, stage_id=_stage_id(session, workspace_id, stage_key),
                    gate_key=gate_key, status=computed, threshold=threshold, result=result)
        session.add(gate)
        return gate
    gate.result = result
    gate.threshold = threshold
    if gate.status not in _HUMAN_RESOLVED:
        gate.status = computed
    return gate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_gates_util.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/gates_util.py tests/unit/test_gates_util.py
git commit -m "feat: shared gate upsert helper"
```

---

## Task 3: Backlog storage (`:Backlog` Neo4j node)

**Files:**
- Create: `src/cobol_modernizer/backlog/storage.py`
- Test: `tests/unit/test_backlog_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_backlog_storage.py
from cobol_modernizer.backlog.schema import AcceptanceCriterion, Backlog, Epic, UserStory
from cobol_modernizer.backlog.storage import BacklogStorage


class FakeNeo4j:
    def __init__(self):
        self.saved = {}
        self.version = 0

    def run(self, query, **params):
        if "CREATE (b:Backlog" in query:
            self.version += 1
            self.saved = dict(params, version=self.version)
            return [{"version": self.version}]
        if "RETURN b ORDER BY b.version DESC" in query:
            if not self.saved:
                return []
            return [{"b": self.saved}]
        return []


def _backlog():
    return Backlog(
        repo_slug="carddemo-mini",
        epics=[Epic(id="EPIC-1", title="Posting", outcome="apply", story_ids=["US-1"])],
        stories=[UserStory(id="US-1", epic_id="EPIC-1", title="Post", actor="batch",
                           narrative="n",
                           acceptance_criteria=[AcceptanceCriterion(id="AC-1", statement="s")],
                           evidence_refs=["CBPOST1M"])],
        evidence_map={"US-1": ["CBPOST1M"]})


def test_save_increments_version_and_serializes_json():
    neo = FakeNeo4j()
    out = BacklogStorage(neo).save(_backlog(), coverage={"coverage_ratio": 0.9},
                                   html="<h1>backlog</h1>", model="m")
    assert out.version == 1
    assert "US-1" in neo.saved["stories_json"]
    assert neo.saved["coverage_json"] == '{"coverage_ratio": 0.9}'


def test_get_latest_returns_node_or_none():
    neo = FakeNeo4j()
    assert BacklogStorage(neo).get_latest("carddemo-mini") is None
    BacklogStorage(neo).save(_backlog(), coverage={}, html="", model="")
    node = BacklogStorage(neo).get_latest("carddemo-mini")
    assert node["version"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_storage.py -q`
Expected: FAIL — `ModuleNotFoundError: cobol_modernizer.backlog.storage`.

- [ ] **Step 3: Implement storage**

```python
# src/cobol_modernizer/backlog/storage.py
"""Persist Backlogs to Neo4j as versioned :Backlog nodes off :Repository{slug},
mirroring DomainDesignStorage. Property names (epics_json/stories_json/version) match
controlplane.build._backlog_brief so the codegen brief reads them with no change."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.backlog.schema import Backlog

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_BACKLOG]->(prev:Backlog)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (b:Backlog {
    id: $id, repo_slug: $repo_slug, version: version,
    epics_json: $epics_json, stories_json: $stories_json,
    evidence_map: $evidence_map, coverage_json: $coverage_json,
    html: $html, model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_BACKLOG]->(b)
RETURN b.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_BACKLOG]->(b:Backlog)
RETURN b ORDER BY b.version DESC LIMIT 1
"""


class BacklogStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, backlog: Backlog, *, coverage: dict, html: str, model: str = "",
             token_usage: dict[str, int] | None = None) -> Backlog:
        bid = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=bid, repo_slug=backlog.repo_slug,
            epics_json=json.dumps([e.model_dump(mode="json") for e in backlog.epics]),
            stories_json=json.dumps([s.model_dump(mode="json") for s in backlog.stories]),
            evidence_map=json.dumps(backlog.evidence_map),
            coverage_json=json.dumps(coverage or {}), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created)
        if not rows:
            raise ValueError(f"Repository not found: {backlog.repo_slug}")
        backlog.version = rows[0]["version"]
        return backlog

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["b"] if rows else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_storage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/backlog/storage.py tests/unit/test_backlog_storage.py
git commit -m "feat: persist backlog as versioned neo4j node"
```

---

## Task 4: Backlog HTML renderer

**Files:**
- Create: `src/cobol_modernizer/backlog/render.py`
- Test: `tests/unit/test_backlog_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_backlog_render.py
from cobol_modernizer.backlog.render import render_html
from cobol_modernizer.backlog.schema import AcceptanceCriterion, Backlog, Epic, UserStory


def test_render_html_includes_epics_stories_and_coverage():
    backlog = Backlog(
        repo_slug="carddemo-mini",
        epics=[Epic(id="EPIC-1", title="Transaction Posting", outcome="apply tx", story_ids=["US-1"])],
        stories=[UserStory(id="US-1", epic_id="EPIC-1", title="Post valid transaction",
                           actor="batch", narrative="As a batch I post.",
                           acceptance_criteria=[AcceptanceCriterion(id="AC-1", statement="balance updates")],
                           depends_on=[], evidence_refs=["CBPOST1M"])])
    html = render_html(backlog, {"coverage_ratio": 0.83})

    assert "<html" in html.lower()
    assert "Transaction Posting" in html
    assert "US-1" in html
    assert "Post valid transaction" in html
    assert "AC-1" in html
    assert "balance updates" in html
    assert "83" in html  # coverage percent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_render.py -q`
Expected: FAIL — `ModuleNotFoundError: cobol_modernizer.backlog.render`.

- [ ] **Step 3: Implement renderer**

```python
# src/cobol_modernizer/backlog/render.py
"""Self-contained HTML view of a Backlog (epics → stories → acceptance criteria →
dependencies) plus the BRD logic-coverage summary, for inline cockpit display."""
from __future__ import annotations

from html import escape

from cobol_modernizer.backlog.schema import Backlog


def render_html(backlog: Backlog, coverage: dict) -> str:
    ratio = float(coverage.get("coverage_ratio", 0.0)) if coverage else 0.0
    pct = round(ratio * 100)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18181b}"
        "h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.5rem}"
        ".story{border:1px solid #e4e4e7;border-radius:8px;padding:.75rem;margin:.5rem 0}"
        ".ac{color:#3f3f46;font-size:.9rem;margin-left:1rem}"
        ".cov{font-weight:600}</style></head><body>",
        f"<h1>Business Backlog — {escape(backlog.repo_slug)} (v{backlog.version})</h1>",
        f"<p class='cov'>BRD logic coverage: {pct}%</p>",
    ]
    for epic in backlog.epics:
        parts.append(f"<h2>{escape(epic.id)} · {escape(epic.title)}</h2>")
        parts.append(f"<p>{escape(epic.outcome)}</p>")
        for story in [s for s in backlog.stories if s.epic_id == epic.id]:
            parts.append("<div class='story'>")
            parts.append(f"<strong>{escape(story.id)} — {escape(story.title)}</strong>")
            parts.append(f"<p>{escape(story.narrative)}</p>")
            if story.depends_on:
                parts.append(f"<p>depends on: {escape(', '.join(story.depends_on))}</p>")
            for ac in story.acceptance_criteria:
                parts.append(f"<div class='ac'>{escape(ac.id)}: {escape(ac.statement)}</div>")
            parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_render.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/backlog/render.py tests/unit/test_backlog_render.py
git commit -m "feat: backlog html renderer"
```

---

## Task 5: Backlog LLM generation helper

**Files:**
- Modify: `src/cobol_modernizer/backlog/generator.py`
- Test: `tests/unit/test_backlog_generate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_backlog_generate.py
import asyncio

from cobol_modernizer.backlog.generator import (
    BACKLOG_SCHEMA,
    build_backlog_prompt,
    generate_backlog_payload,
)


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, *, system, prompt, server, allowed_tools, model,
                             max_turns, schema, label):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        return self.payload


def test_build_backlog_prompt_includes_brd_and_refs():
    prompt = build_backlog_prompt(
        brd_sections=[{"title": "Functional", "requirements": [{"id": "FR-1", "text": "Post tx"}]}],
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1"])
    assert "FR-1" in prompt
    assert "CBPOST1M" in prompt


def test_generate_backlog_payload_returns_raw_dict():
    runner = FakeRunner({"epics": [], "stories": []})
    raw = asyncio.run(generate_backlog_payload(
        runner=runner, model="m", timeout_s=5.0,
        brd_sections=[{"title": "t", "requirements": [{"id": "FR-1", "text": "x"}]}],
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert raw == {"epics": [], "stories": []}
    assert "FR-1" in runner.calls[0]["prompt"]
    assert runner.calls[0]["schema"] is BACKLOG_SCHEMA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_generate.py -q`
Expected: FAIL — `ImportError: cannot import name 'BACKLOG_SCHEMA'`.

- [ ] **Step 3: Add schema, prompt builder, and async generator to `generator.py`**

Append to `src/cobol_modernizer/backlog/generator.py`:

```python
import json

from cobol_modernizer.enrichment.base import run_batched

BACKLOG_SCHEMA = {
    "type": "object",
    "properties": {
        "epics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "title": {"type": "string"},
                    "outcome": {"type": "string"},
                    "brd_requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "story_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "outcome"],
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "epic_id": {"type": "string"},
                    "title": {"type": "string"}, "actor": {"type": "string"},
                    "narrative": {"type": "string"},
                    "brd_requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"}, "statement": {"type": "string"},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["id", "statement"],
                        },
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "epic_id", "title", "actor", "narrative", "acceptance_criteria"],
            },
        },
    },
    "required": ["epics", "stories"],
}


def build_backlog_prompt(*, brd_sections: list[dict], known_refs: list[str],
                         known_requirement_ids: list[str]) -> str:
    return (
        "## BRD requirement sections\n```json\n" + json.dumps(brd_sections) + "\n```\n"
        "## Known BRD requirement ids (cite only these)\n" + ", ".join(known_requirement_ids) + "\n"
        "## Known graph evidence refs (cite only these)\n```json\n"
        + json.dumps(known_refs) + "\n```\n"
        "Produce epics and user stories. Every story MUST cite at least one BRD "
        "requirement id and at least one graph evidence ref, and MUST include "
        "acceptance criteria phrased as testable Given/When/Then statements."
    )


async def generate_backlog_payload(*, runner, model: str, timeout_s: float,
                                   brd_sections: list[dict], known_refs: list[str],
                                   known_requirement_ids: list[str]) -> dict:
    prompt = build_backlog_prompt(brd_sections=brd_sections, known_refs=known_refs,
                                  known_requirement_ids=known_requirement_ids)
    return await run_batched(runner=runner, system=BACKLOG_SYSTEM, prompt=prompt,
                             schema=BACKLOG_SCHEMA, model=model, timeout_s=timeout_s,
                             label="backlog-generate")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_generate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/backlog/generator.py tests/unit/test_backlog_generate.py
git commit -m "feat: backlog llm generation helper"
```

---

## Task 6: Backlog stage endpoint (generate → persist → gates)

**Files:**
- Rewrite: `src/cobol_modernizer/controlplane/backlog.py`
- Test: `tests/integration/test_controlplane_backlog_api.py` (extend existing)

- [ ] **Step 1: Write the failing integration test**

Replace `tests/integration/test_controlplane_backlog_api.py` with:

```python
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


class FakeNeo4j:
    def __init__(self):
        self.backlog = None

    def run(self, query, **params):
        if "MERGE (r:Repository" in query:
            return []
        if "HAS_BRD" in query or "(b:BRD)" in query:
            return [{"b": {"version": 1,
                           "sections": json.dumps([{"title": "Functional",
                               "requirements": [{"id": "FR-1", "text": "Post tx"}]}]),
                           "evidence_map": "{}"}}]
        if "RETURN n.qualified_name AS q" in query or "RETURN n.qualified_name AS ref" in query:
            key = "q" if " AS q" in query else "ref"
            return [{key: "CBPOST1M", "kind": "Program"},
                    {key: "CBPOST1M.2100-POST", "kind": "Paragraph"}]
        if "_ALL_PROGRAMS" in query or "RETURN p.name AS program" in query or "AS program" in query:
            return [{"program": "CBPOST1M"}]
        if "CREATE (b:Backlog" in query:
            self.backlog = dict(params, version=1)
            return [{"version": 1}]
        if "RETURN b ORDER BY b.version DESC" in query:
            return [{"b": self.backlog}] if self.backlog else []
        return []


def _fake_payload(**_kw):
    return {
        "epics": [{"id": "EPIC-1", "title": "Posting", "outcome": "apply",
                   "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
                   "evidence_refs": ["CBPOST1M"]}],
        "stories": [{"id": "US-1", "epic_id": "EPIC-1", "title": "Post valid tx",
                     "actor": "batch", "narrative": "As a batch I post.",
                     "brd_requirement_ids": ["FR-1"],
                     "acceptance_criteria": [{"id": "AC-1", "statement": "balance updates",
                                              "evidence_refs": ["CBPOST1M.2100-POST"]}],
                     "evidence_refs": ["CBPOST1M", "CBPOST1M.2100-POST"]}],
    }


def _client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="t"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="backlog", ordinal=6, status="running"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="blueprint", ordinal=5, status="passed"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    jobs.runner.inline = True
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: FakeNeo4j())
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    return TestClient(app), eng


def test_backlog_status_idle_before_generation(monkeypatch):
    client, _ = _client(monkeypatch)
    try:
        r = client.get("/api/workspaces/ws-1/backlog")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()


def test_backlog_post_generates_persists_and_creates_gate(monkeypatch):
    from cobol_modernizer.controlplane import backlog as bl
    monkeypatch.setattr(bl, "generate_backlog_payload",
                        lambda **kw: __import__("asyncio").sleep(0, result=_fake_payload()))
    client, eng = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        done = client.get("/api/workspaces/ws-1/backlog").json()
        assert done["status"] == "done"
        assert done["result"]["stories"] == 1
        with Session(eng) as s:
            gates = {g.gate_key: g for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "backlog_coverage" in gates
            assert "brd_logic_coverage" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_backlog_api.py -q`
Expected: FAIL — POST route missing / no gates created.

- [ ] **Step 3: Rewrite the backlog router**

```python
# src/cobol_modernizer/controlplane/backlog.py
"""Backlog stage — graph-grounded BRD → business epics/user stories with acceptance
criteria, a seam/data dependency DAG, and a BRD logic-coverage report. Mirrors
blueprint.py: fast precheck, multi-minute LLM run on the JobRunner, persist a
versioned :Backlog node, upsert the backlog_coverage + brd_logic_coverage gates."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.backlog.generator import generate_backlog_payload, parse_backlog_payload
from cobol_modernizer.backlog.render import render_html
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.traceability.coverage import brd_logic_coverage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-backlog"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"


def _coverage_min() -> float:
    try:
        return float(os.environ.get("BACKLOG_COVERAGE_MIN", "0.8"))
    except ValueError:
        return 0.8


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None}
    return {"status": job["status"], "result": job.get("result"), "error": job.get("error")}


def _requirement_ids(sections: list[dict]) -> set[str]:
    ids: set[str] = set()
    for sec in sections:
        for req in sec.get("requirements", []) if isinstance(sec, dict) else []:
            rid = req.get("id") if isinstance(req, dict) else None
            if rid:
                ids.add(str(rid))
    return ids


def run_backlog(*, session: Session, neo4j, workspace: Workspace,
                generate: Callable[..., Any] | None = None) -> dict:
    """Generate + persist a backlog and publish its gates. `generate` defaults to the
    real LLM call (injected by tests)."""
    slug = workspace.repo_slug
    brd = BRDStorage(neo4j).get_latest(slug)
    if not brd:
        raise HTTPException(status_code=409, detail=f"no BRD for '{slug}' — run Blueprint first")
    sections = json.loads(brd.get("sections") or "[]") if isinstance(brd.get("sections"), str) \
        else (brd.get("sections") or [])
    known_refs = [r["q"] for r in neo4j.run(_GRAPH_REFS_Q, repo=slug) if r.get("q")]
    known_req_ids = _requirement_ids(sections)

    gen = generate or generate_backlog_payload
    raw = asyncio.run(gen(runner=SdkAgentRunner(), model=os.environ.get("BACKLOG_MODEL", "claude-sonnet-4-6"),
                          timeout_s=float(os.environ.get("BACKLOG_TIMEOUT_S", "300")),
                          brd_sections=sections, known_refs=known_refs,
                          known_requirement_ids=sorted(known_req_ids)))
    backlog = parse_backlog_payload(raw, repo_slug=slug, known_refs=set(known_refs),
                                    known_requirement_ids=known_req_ids)
    seam_candidates = rank_candidates(neo4j, repo=slug)
    dag = derive_story_dependencies(backlog.stories, seam_candidates, repo_slug=slug)
    backlog.stories = dag.stories
    backlog.evidence_map = {s.id: s.evidence_refs for s in backlog.stories}

    report = brd_logic_coverage(neo4j, slug, sections, backlog.evidence_map)
    coverage = report.model_dump(mode="json")
    BacklogStorage(neo4j).save(backlog, coverage=coverage,
                               html=render_html(backlog, coverage))

    passed = report.coverage_ratio >= _coverage_min()
    threshold = {"min_coverage": _coverage_min()}
    result = {"coverage_ratio": report.coverage_ratio, "uncovered": report.uncovered_refs[:50]}
    upsert_gate(session, workspace.id, "backlog", "backlog_coverage",
                passed=passed, result=result, threshold=threshold)
    upsert_gate(session, workspace.id, "blueprint", "brd_logic_coverage",
                passed=passed, result=result, threshold=threshold)
    session.flush()
    return {"repo_slug": slug, "epics": len(backlog.epics), "stories": len(backlog.stories),
            "coverage_ratio": report.coverage_ratio, "version": backlog.version}


@router.post("/workspaces/{wid}/backlog", status_code=202)
def backlog_generate(wid: str, session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY") and not jobs.runner.inline:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set — Backlog needs an LLM.")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            out = run_backlog(session=s, neo4j=neo, workspace=ws2)
            s.commit()
            return out
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("backlog", wid, _job))


@router.get("/workspaces/{wid}/backlog")
def backlog_status(wid: str, session: Session = Depends(get_session),
                   neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("backlog", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = BacklogStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        cov = json.loads(latest.get("coverage_json") or "{}")
        return {"status": "done", "error": None,
                "result": {"repo_slug": ws.repo_slug, "version": latest.get("version"),
                           "epics": len(json.loads(latest.get("epics_json") or "[]")),
                           "stories": len(json.loads(latest.get("stories_json") or "[]")),
                           "coverage_ratio": cov.get("coverage_ratio")}}
    return {"status": "idle", "result": None, "error": None}


@router.get("/workspaces/{wid}/backlog/html", response_class=HTMLResponse)
def backlog_html(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = BacklogStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no backlog yet — run the Backlog stage first")
    return HTMLResponse(content=latest["html"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_controlplane_backlog_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/backlog.py tests/integration/test_controlplane_backlog_api.py
git commit -m "feat: backlog generation stage with coverage gates"
```

---

## Task 7: Domain design consumes the persisted backlog

**Files:**
- Modify: `src/cobol_modernizer/controlplane/analysis.py`
- Test: `tests/integration/test_domain_uses_real_backlog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_domain_uses_real_backlog.py
import json

from cobol_modernizer.controlplane import analysis


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_BACKLOG" in query or "(b:Backlog)" in query:
            return [{"b": {"version": 1,
                           "stories_json": json.dumps([{"id": "US-1", "title": "Post valid tx"}]),
                           "epics_json": "[]"}}]
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return []
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        return []


def test_backlog_json_for_domain_reads_persisted_stories():
    payload = analysis._backlog_json_for_domain(FakeNeo4j(), "carddemo-mini")
    assert "US-1" in payload
    assert "Post valid tx" in payload


def test_backlog_json_for_domain_empty_when_none():
    class Empty:
        def run(self, q, **k):
            return []
    assert analysis._backlog_json_for_domain(Empty(), "carddemo-mini") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_domain_uses_real_backlog.py -q`
Expected: FAIL — `_backlog_json_for_domain` missing.

- [ ] **Step 3: Add the reader and pass it into `run_domain_design`**

In `src/cobol_modernizer/controlplane/analysis.py`, add near the other domain helpers:

```python
def _backlog_json_for_domain(neo, slug: str) -> str:
    """The persisted backlog's stories as a compact JSON string for the decomposition
    prompt, or '' when no backlog exists (domain then grounds on the BRD alone). Never
    raises — story injection is best-effort context, not a hard dependency."""
    try:
        from cobol_modernizer.backlog.storage import BacklogStorage
        latest = BacklogStorage(neo).get_latest(slug)
        if not latest:
            return ""
        return json.dumps({"stories": json.loads(latest.get("stories_json") or "[]")})
    except Exception:  # noqa: BLE001
        return ""
```

Then in `_domain_run_and_persist`, change the `run_domain_design(...)` call to pass the backlog:

```python
        dd = run_domain_design(neo, slug, brd_text=brd, runner=runner,
                               model=enrich_model("domain"),
                               timeout_s=enrich_timeout_s("domain", default=300.0),
                               backlog_json=_backlog_json_for_domain(neo, slug))
```

Confirm `json` is imported at the top of `analysis.py` (it is, used elsewhere).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_domain_uses_real_backlog.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/analysis.py tests/integration/test_domain_uses_real_backlog.py
git commit -m "feat: domain decomposition consumes persisted backlog"
```

---

## Task 8: Technical design generator (prompt + parser + LLM helper)

**Files:**
- Create: `src/cobol_modernizer/technical_design/generator.py`
- Test: `tests/unit/test_technical_design_generator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_technical_design_generator.py
import asyncio

from cobol_modernizer.technical_design.generator import (
    TECHNICAL_DESIGN_SCHEMA,
    build_technical_design_prompt,
    generate_technical_design_payload,
    parse_technical_design_payload,
)


def test_prompt_includes_ddd_backlog_and_seams():
    prompt = build_technical_design_prompt(
        ddd_json='{"contexts":[{"name":"Posting"}]}',
        backlog_json='{"stories":[{"id":"US-1"}]}',
        seam_waves_json='[["CBPOST1M"]]',
        graph_summary={"programs": ["CBPOST1M"]})
    assert "Posting" in prompt
    assert "US-1" in prompt
    assert "CBPOST1M" in prompt


def test_parse_drops_ungrounded_story_ids_contexts_and_refs():
    raw = {"services": [{
        "name": "posting-service", "bounded_context": "Posting", "deployment": "module",
        "story_ids": ["US-1", "GHOST"],
        "api_contracts": [{"name": "post", "method": "POST", "path": "/p"}],
        "persistence": [{"resource": "ACCTFILE", "access_pattern": "legacy-mimic"}],
        "evidence_refs": ["CBPOST1M", "GHOST"],
    }, {
        "name": "ghost-service", "bounded_context": "Unknown", "deployment": "module",
        "story_ids": [], "evidence_refs": [],
    }]}
    design = parse_technical_design_payload(
        raw, repo_slug="carddemo-mini", known_refs={"CBPOST1M"},
        known_story_ids={"US-1"}, known_contexts={"Posting"})
    assert len(design.services) == 1  # ghost-service dropped (unknown context)
    svc = design.services[0]
    assert svc.story_ids == ["US-1"]
    assert svc.evidence_refs == ["CBPOST1M"]
    assert svc.persistence[0].resource == "ACCTFILE"


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        return self.payload


def test_generate_returns_raw_payload():
    runner = FakeRunner({"services": []})
    raw = asyncio.run(generate_technical_design_payload(
        runner=runner, model="m", timeout_s=5.0, ddd_json="{}", backlog_json="{}",
        seam_waves_json="[]", graph_summary={}))
    assert raw == {"services": []}
    assert runner.calls[0]["schema"] is TECHNICAL_DESIGN_SCHEMA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_technical_design_generator.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the generator**

```python
# src/cobol_modernizer/technical_design/generator.py
"""DDD contexts + backlog stories + seam waves → target technical architecture
(services with API/persistence/integration contracts), grounded on graph refs, known
story ids, and known DDD context names. Parser drops anything ungrounded."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import run_batched
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    IntegrationContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)

TECHNICAL_DESIGN_SYSTEM = (
    "You transform a DDD bounded-context model, a business backlog, and seam delivery "
    "waves into a target technical architecture for a Spring Boot system. Define one "
    "service per bounded context. Each service cites the story ids it delivers and the "
    "graph evidence refs it derives from. Specify API contracts, persistence access "
    "patterns, and integration contracts. Do not invent story ids, context names, or "
    "graph refs — use only the ones provided."
)

_ACCESS_PATTERNS = {"legacy-mimic", "repository", "event-sourced", "read-replica"}
_STYLES = {"sync", "async", "batch"}
_DEPLOYMENTS = {"module", "microservice"}

TECHNICAL_DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "services": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "bounded_context": {"type": "string"},
                    "deployment": {"type": "string", "enum": ["module", "microservice"]},
                    "story_ids": {"type": "array", "items": {"type": "string"}},
                    "api_contracts": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "method": {"type": "string"},
                                       "path": {"type": "string"},
                                       "request_model": {"type": "string"},
                                       "response_model": {"type": "string"}},
                        "required": ["name", "method", "path"]}},
                    "persistence": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"resource": {"type": "string"},
                                       "access_pattern": {"type": "string"},
                                       "owner_service": {"type": "string"}},
                        "required": ["resource", "access_pattern"]}},
                    "integrations": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "style": {"type": "string"},
                                       "target": {"type": "string"}, "payload": {"type": "string"}},
                        "required": ["name", "style", "target"]}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "bounded_context", "deployment"],
            },
        },
    },
    "required": ["services"],
}


def build_technical_design_prompt(*, ddd_json: str, backlog_json: str,
                                  seam_waves_json: str, graph_summary: dict) -> str:
    return (
        "## DDD bounded contexts\n```json\n" + ddd_json + "\n```\n"
        "## Business backlog (stories)\n```json\n" + backlog_json + "\n```\n"
        "## Seam delivery waves (cutover order)\n```json\n" + seam_waves_json + "\n```\n"
        "## Graph coupling summary\n```json\n" + json.dumps(graph_summary) + "\n```\n"
        "Produce one technical service per bounded context with API, persistence, and "
        "integration contracts. Every writer resource must be owned by exactly one service."
    )


def _ground(values: Any, allowed: set[str]) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if isinstance(v, str) and v in allowed and v not in out:
            out.append(v)
    return out


def parse_technical_design_payload(raw: dict, *, repo_slug: str, known_refs: set[str],
                                   known_story_ids: set[str],
                                   known_contexts: set[str]) -> TechnicalDesign:
    services: list[TechnicalService] = []
    for item in raw.get("services", []):
        if not isinstance(item, dict):
            continue
        ctx = str(item.get("bounded_context", ""))
        if known_contexts and ctx not in known_contexts:
            continue  # drop services not tied to a known DDD context
        deployment = item.get("deployment")
        if deployment not in _DEPLOYMENTS:
            deployment = "module"
        apis = [ApiContract(name=str(a.get("name", "")), method=str(a.get("method", "")),
                            path=str(a.get("path", "")),
                            request_model=str(a.get("request_model", "")),
                            response_model=str(a.get("response_model", "")))
                for a in item.get("api_contracts", []) if isinstance(a, dict)]
        persistence = [PersistenceDesign(resource=str(p.get("resource", "")),
                                         access_pattern=p.get("access_pattern")
                                         if p.get("access_pattern") in _ACCESS_PATTERNS else "legacy-mimic",
                                         owner_service=str(p.get("owner_service", "")))
                       for p in item.get("persistence", []) if isinstance(p, dict)]
        integrations = [IntegrationContract(name=str(i.get("name", "")),
                                            style=i.get("style") if i.get("style") in _STYLES else "sync",
                                            target=str(i.get("target", "")),
                                            payload=str(i.get("payload", "")))
                        for i in item.get("integrations", []) if isinstance(i, dict)]
        services.append(TechnicalService(
            name=str(item.get("name", "")), bounded_context=ctx, deployment=deployment,
            story_ids=_ground(item.get("story_ids"), known_story_ids),
            api_contracts=apis, persistence=persistence, integrations=integrations,
            evidence_refs=_ground(item.get("evidence_refs"), known_refs)))
    evidence_map = {s.name: s.evidence_refs for s in services}
    return TechnicalDesign(repo_slug=repo_slug, services=services, evidence_map=evidence_map)


async def generate_technical_design_payload(*, runner, model: str, timeout_s: float,
                                            ddd_json: str, backlog_json: str,
                                            seam_waves_json: str, graph_summary: dict) -> dict:
    prompt = build_technical_design_prompt(ddd_json=ddd_json, backlog_json=backlog_json,
                                           seam_waves_json=seam_waves_json,
                                           graph_summary=graph_summary)
    return await run_batched(runner=runner, system=TECHNICAL_DESIGN_SYSTEM, prompt=prompt,
                             schema=TECHNICAL_DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                             label="technical-design-generate")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_technical_design_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/technical_design/generator.py tests/unit/test_technical_design_generator.py
git commit -m "feat: technical design llm generator and grounded parser"
```

---

## Task 9: Technical design storage + renderer

**Files:**
- Create: `src/cobol_modernizer/technical_design/storage.py`
- Create: `src/cobol_modernizer/technical_design/render.py`
- Test: `tests/unit/test_technical_design_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_technical_design_storage.py
from cobol_modernizer.technical_design.render import render_html
from cobol_modernizer.technical_design.schema import (
    ApiContract, PersistenceDesign, TechnicalDesign, TechnicalService,
)
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage


class FakeNeo4j:
    def __init__(self):
        self.saved = None

    def run(self, query, **params):
        if "CREATE (t:TechnicalDesign" in query:
            self.saved = dict(params, version=1)
            return [{"version": 1}]
        if "RETURN t ORDER BY t.version DESC" in query:
            return [{"t": self.saved}] if self.saved else []
        return []


def _design():
    return TechnicalDesign(repo_slug="carddemo-mini", services=[
        TechnicalService(name="posting-service", bounded_context="Posting", deployment="module",
                         story_ids=["US-1"],
                         api_contracts=[ApiContract(name="post", method="POST", path="/p")],
                         persistence=[PersistenceDesign(resource="ACCTFILE", access_pattern="legacy-mimic")],
                         evidence_refs=["CBPOST1M"])])


def test_save_and_get_latest_roundtrip():
    neo = FakeNeo4j()
    out = TechnicalDesignStorage(neo).save(_design(), html="<h1>td</h1>", model="m")
    assert out.version == 1
    assert "posting-service" in neo.saved["services_json"]
    assert TechnicalDesignStorage(neo).get_latest("carddemo-mini")["version"] == 1


def test_render_html_lists_services_and_contracts():
    html = render_html(_design())
    assert "posting-service" in html
    assert "Posting" in html
    assert "/p" in html
    assert "ACCTFILE" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_technical_design_storage.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement storage**

```python
# src/cobol_modernizer/technical_design/storage.py
"""Persist TechnicalDesigns as versioned :TechnicalDesign nodes off :Repository{slug}.
Property names (services_json/version) match controlplane.build._technical_design_brief."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.technical_design.schema import TechnicalDesign

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_TECHNICAL_DESIGN]->(prev:TechnicalDesign)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (t:TechnicalDesign {
    id: $id, repo_slug: $repo_slug, version: version,
    services_json: $services_json, evidence_map: $evidence_map,
    html: $html, model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_TECHNICAL_DESIGN]->(t)
RETURN t.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_TECHNICAL_DESIGN]->(t:TechnicalDesign)
RETURN t ORDER BY t.version DESC LIMIT 1
"""


class TechnicalDesignStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, design: TechnicalDesign, *, html: str, model: str = "",
             token_usage: dict[str, int] | None = None) -> TechnicalDesign:
        tid = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=tid, repo_slug=design.repo_slug,
            services_json=json.dumps([s.model_dump(mode="json") for s in design.services]),
            evidence_map=json.dumps(design.evidence_map), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created)
        if not rows:
            raise ValueError(f"Repository not found: {design.repo_slug}")
        design.version = rows[0]["version"]
        return design

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["t"] if rows else None
```

- [ ] **Step 4: Implement renderer**

```python
# src/cobol_modernizer/technical_design/render.py
"""Self-contained HTML view of a TechnicalDesign: services with their bounded context,
deployment unit, delivered stories, and API/persistence/integration contracts."""
from __future__ import annotations

from html import escape

from cobol_modernizer.technical_design.schema import TechnicalDesign


def render_html(design: TechnicalDesign) -> str:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18181b}"
        "h1{font-size:1.4rem}.svc{border:1px solid #e4e4e7;border-radius:8px;padding:1rem;margin:.75rem 0}"
        "table{border-collapse:collapse;margin:.5rem 0}td,th{border:1px solid #e4e4e7;padding:.25rem .5rem;font-size:.85rem}"
        "</style></head><body>",
        f"<h1>Technical Design — {escape(design.repo_slug)} (v{design.version})</h1>",
    ]
    for svc in design.services:
        parts.append("<div class='svc'>")
        parts.append(f"<h2>{escape(svc.name)} <small>[{escape(svc.bounded_context)} · {escape(svc.deployment)}]</small></h2>")
        if svc.story_ids:
            parts.append(f"<p>stories: {escape(', '.join(svc.story_ids))}</p>")
        if svc.api_contracts:
            parts.append("<table><tr><th>API</th><th>Method</th><th>Path</th></tr>")
            for a in svc.api_contracts:
                parts.append(f"<tr><td>{escape(a.name)}</td><td>{escape(a.method)}</td><td>{escape(a.path)}</td></tr>")
            parts.append("</table>")
        if svc.persistence:
            parts.append("<table><tr><th>Resource</th><th>Access pattern</th></tr>")
            for p in svc.persistence:
                parts.append(f"<tr><td>{escape(p.resource)}</td><td>{escape(p.access_pattern)}</td></tr>")
            parts.append("</table>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_technical_design_storage.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/technical_design/storage.py src/cobol_modernizer/technical_design/render.py tests/unit/test_technical_design_storage.py
git commit -m "feat: technical design storage and html renderer"
```

---

## Task 10: Technical design stage endpoint + rewire `design` + retire legacy

**Files:**
- Create: `src/cobol_modernizer/controlplane/technical_design.py`
- Modify: `src/cobol_modernizer/controlplane/__init__.py`
- Modify: `src/cobol_modernizer/controlplane/analysis.py` (remove legacy `/design` route)
- Test: `tests/integration/test_controlplane_technical_design_api.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_controlplane_technical_design_api.py
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane import technical_design as td
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


class FakeNeo4j:
    def __init__(self):
        self.saved = None

    def run(self, query, **params):
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return [{"d": {"version": 1, "contexts_json": json.dumps([{"name": "Posting"}]),
                           "designs_json": "[]"}}]
        if "(b:Backlog)" in query or "HAS_BACKLOG" in query:
            return [{"b": {"version": 1, "stories_json": json.dumps([{"id": "US-1"}]),
                           "epics_json": "[]"}}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        if "CREATE (t:TechnicalDesign" in query:
            self.saved = dict(params, version=1)
            return [{"version": 1}]
        if "RETURN t ORDER BY t.version DESC" in query:
            return [{"t": self.saved}] if self.saved else []
        return []


def _payload(**_kw):
    import asyncio
    return asyncio.sleep(0, result={"services": [
        {"name": "posting-service", "bounded_context": "Posting", "deployment": "module",
         "story_ids": ["US-1"], "evidence_refs": ["CBPOST1M"],
         "persistence": [{"resource": "ACCTFILE", "access_pattern": "legacy-mimic"}]}]})


def _client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="t"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="design", ordinal=10, status="running"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    jobs.runner.inline = True
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: FakeNeo4j())
    monkeypatch.setattr(td, "generate_technical_design_payload", _payload)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    return TestClient(app), eng


def test_technical_design_post_persists_and_gates(monkeypatch):
    client, eng = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/technical-design")
        assert r.status_code in (200, 202)
        done = client.get("/api/workspaces/ws-1/technical-design").json()
        assert done["status"] == "done"
        assert done["result"]["services"] == 1
        with Session(eng) as s:
            gates = {g.gate_key for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "design_data_ownership" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_technical_design_api.py -q`
Expected: FAIL — module/route missing.

- [ ] **Step 3: Implement the technical-design router**

```python
# src/cobol_modernizer/controlplane/technical_design.py
"""Technical Design stage (the cockpit's 'design' stage) — DDD contexts + backlog +
seam waves → target service architecture. Mirrors blueprint.py. Replaces the legacy
deterministic writer-slice design. Upserts the design_data_ownership gate (every
writer resource owned by exactly one service)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.technical_design.generator import (
    generate_technical_design_payload,
    parse_technical_design_payload,
)
from cobol_modernizer.technical_design.render import render_html
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-technical-design"])
_NEO4J_ERRORS = (Neo4jError, DriverError)
_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None}
    return {"status": job["status"], "result": job.get("result"), "error": job.get("error")}


def _data_ownership_ok(design) -> tuple[bool, list[str]]:
    """Every writer resource owned by exactly one service. Returns (ok, conflicts)."""
    owners: dict[str, list[str]] = {}
    for svc in design.services:
        for p in svc.persistence:
            owners.setdefault(p.resource, []).append(svc.name)
    conflicts = [res for res, svcs in owners.items() if len(svcs) > 1]
    return (not conflicts), conflicts


def run_technical_design(*, session: Session, neo4j, workspace: Workspace,
                         generate: Callable[..., Any] | None = None) -> dict:
    slug = workspace.repo_slug
    dd = DomainDesignStorage(neo4j).get_latest(slug)
    if not dd:
        raise HTTPException(status_code=409, detail=f"no domain design for '{slug}' — run Domain Design first")
    contexts = json.loads(dd.get("contexts_json") or "[]")
    known_contexts = {c.get("name") for c in contexts if isinstance(c, dict) and c.get("name")}
    backlog = BacklogStorage(neo4j).get_latest(slug)
    stories = json.loads(backlog.get("stories_json") or "[]") if backlog else []
    known_story_ids = {s.get("id") for s in stories if isinstance(s, dict) and s.get("id")}
    known_refs = {r["q"] for r in neo4j.run(_GRAPH_REFS_Q, repo=slug) if r.get("q")}
    seam_waves = [[c.get("program")] for c in rank_candidates(neo4j, repo=slug)]

    gen = generate or generate_technical_design_payload
    raw = asyncio.run(gen(runner=SdkAgentRunner(),
                          model=os.environ.get("TECHNICAL_DESIGN_MODEL", "claude-sonnet-4-6"),
                          timeout_s=float(os.environ.get("TECHNICAL_DESIGN_TIMEOUT_S", "300")),
                          ddd_json=json.dumps({"contexts": contexts}),
                          backlog_json=json.dumps({"stories": stories}),
                          seam_waves_json=json.dumps(seam_waves),
                          graph_summary={"refs": sorted(known_refs)[:200]}))
    design = parse_technical_design_payload(raw, repo_slug=slug, known_refs=known_refs,
                                            known_story_ids=known_story_ids,
                                            known_contexts=known_contexts)
    TechnicalDesignStorage(neo4j).save(design, html=render_html(design))

    ok, conflicts = _data_ownership_ok(design)
    upsert_gate(session, workspace.id, "design", "design_data_ownership",
                passed=ok, result={"conflicts": conflicts},
                threshold={"unique_writer_ownership": True})
    session.flush()
    return {"repo_slug": slug, "services": len(design.services),
            "data_ownership_ok": ok, "version": design.version}


@router.post("/workspaces/{wid}/technical-design", status_code=202)
def technical_design_generate(wid: str, session: Session = Depends(get_session),
                              neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY") and not jobs.runner.inline:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set — Technical Design needs an LLM.")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            out = run_technical_design(session=s, neo4j=neo, workspace=ws2)
            s.commit()
            return out
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("technical_design", wid, _job))


@router.get("/workspaces/{wid}/technical-design")
def technical_design_status(wid: str, session: Session = Depends(get_session),
                            neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("technical_design", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = TechnicalDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        return {"status": "done", "error": None,
                "result": {"repo_slug": ws.repo_slug, "version": latest.get("version"),
                           "services": len(json.loads(latest.get("services_json") or "[]"))}}
    return {"status": "idle", "result": None, "error": None}


@router.get("/workspaces/{wid}/technical-design/html", response_class=HTMLResponse)
def technical_design_html(wid: str, session: Session = Depends(get_session),
                          neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = TechnicalDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no technical design yet — run the Design stage first")
    return HTMLResponse(content=latest["html"])
```

- [ ] **Step 4: Wire the router and retire the legacy `/design` route**

In `src/cobol_modernizer/controlplane/__init__.py`, add next to the backlog import/include:

```python
from cobol_modernizer.controlplane.technical_design import router as _technical_design_router
...
controlplane_router.include_router(_technical_design_router)
```

In `src/cobol_modernizer/controlplane/analysis.py`, delete the legacy `@router.post("/workspaces/{wid}/design")` handler `run_design` (the deterministic writer-slice design at lines ~322-336). Keep `_compute_designs` only if `design_enrich` still uses it; otherwise delete that too. Update the module docstring line that says "POST /api/workspaces/{id}/design — per-writer-slice bounded-context design".

- [ ] **Step 5: Run tests to verify pass + no legacy route**

Run: `uv run pytest tests/integration/test_controlplane_technical_design_api.py -q`
Expected: PASS.
Run: `uv run pytest tests/ -q -k "design" 2>&1 | tail -20`
Fix any test that POSTed the old `/design` route to instead POST `/technical-design` (or delete legacy-only tests).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/technical_design.py src/cobol_modernizer/controlplane/__init__.py src/cobol_modernizer/controlplane/analysis.py tests/integration/test_controlplane_technical_design_api.py
git commit -m "feat: technical design stage replaces legacy writer-slice design"
```

---

## Task 11: Build records generated test refs; brief proven e2e

**Files:**
- Modify: `src/cobol_modernizer/controlplane/build.py`
- Test: `tests/unit/test_build_generated_test_refs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_build_generated_test_refs.py
from pathlib import Path

from cobol_modernizer.controlplane.build import scan_generated_test_refs


def test_scan_finds_acceptance_criterion_ids_cited_in_tests(tmp_path: Path):
    tdir = tmp_path / "src" / "test" / "java"
    tdir.mkdir(parents=True)
    (tdir / "PostingTest.java").write_text(
        "// Covers AC-1 and AC-2\n@Test void postValid(){ /* US-1 */ }\n")
    (tdir / "Other.java").write_text("class Other {}\n")

    refs = scan_generated_test_refs(tmp_path, ["AC-1", "AC-2", "AC-3"])

    assert set(refs) == {"AC-1", "AC-2"}


def test_scan_returns_empty_when_no_dir(tmp_path: Path):
    assert scan_generated_test_refs(tmp_path / "missing", ["AC-1"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_build_generated_test_refs.py -q`
Expected: FAIL — `scan_generated_test_refs` missing.

- [ ] **Step 3: Implement the scanner and record an artifact after codegen**

Add to `src/cobol_modernizer/controlplane/build.py`:

```python
def scan_generated_test_refs(project_dir, acceptance_criteria_ids: list[str]) -> list[str]:
    """Which acceptance-criterion ids the generated test sources actually cite. Codegen
    is instructed to cite story/AC ids in test comments/names; we grep the generated
    *Test.java files for each id. Returns the subset found (deterministic, sorted)."""
    from pathlib import Path
    root = Path(project_dir)
    if not root.is_dir():
        return []
    blobs: list[str] = []
    for path in root.rglob("*.java"):
        name = path.name.lower()
        if "test" in name:
            try:
                blobs.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    haystack = "\n".join(blobs)
    return sorted({ac for ac in acceptance_criteria_ids if ac and ac in haystack})
```

Then, in the build job (after `generate_slice` produces the project), record the refs as an
`Artifact` so the verify stage can read them. Locate where the build job has the generated
project dir and the session, and add:

```python
from cobol_modernizer.persistence.tables import Artifact

def _record_generated_test_refs(session, *, workspace_id: str, project_dir,
                                 acceptance_criteria_ids: list[str]) -> None:
    refs = scan_generated_test_refs(project_dir, acceptance_criteria_ids)
    prev = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == "generated_test_refs")
    ).scalars().all()
    version = (max((a.version for a in prev), default=0)) + 1
    session.add(Artifact(workspace_id=workspace_id, kind="generated_test_refs",
                         version=version, object_uri="inline://generated_test_refs",
                         content_hash="sha256:refs",
                         evidence_map={"acceptance_criteria": refs}))
    session.flush()
```

Add `from sqlalchemy import select` to the build.py imports if not present. Call
`_record_generated_test_refs(...)` from the build job after codegen, passing the AC ids
gathered from the persisted backlog stories (`_backlog_brief(neo4j, slug)` → each story's
`acceptance_criteria[].id`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_build_generated_test_refs.py -q`
Expected: PASS.

- [ ] **Step 5: Add the e2e brief test (backlog + technical design actually reach the brief)**

```python
# tests/unit/test_build_brief_e2e.py
import json

from cobol_modernizer.controlplane import build as bd


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_DOMAIN_DESIGN" in query or "(d:DomainDesign)" in query:
            return [{"d": {"version": 1, "rating": "high", "contexts_json": "[]", "designs_json": "[]"}}]
        if "HAS_TECHNICAL_DESIGN" in query or "(t:TechnicalDesign)" in query:
            return [{"t": {"version": 1, "services_json": json.dumps([{"name": "posting-service"}])}}]
        if "HAS_BACKLOG" in query or "(b:Backlog)" in query:
            return [{"b": {"version": 1, "epics_json": "[]",
                           "stories_json": json.dumps([{"id": "US-1", "title": "Post"}])}}]
        return []


def test_codegen_brief_contains_backlog_and_technical_design():
    brd_node = {"version": 1, "rating": "high",
                "sections": json.dumps([{"title": "Functional",
                    "requirements": [{"id": "FR-1", "text": "Post tx"}]}])}
    brief = json.loads(bd._codegen_brief(FakeNeo4j(), "carddemo-mini", brd_node))
    assert brief["backlog"]["stories"][0]["id"] == "US-1"
    assert brief["technical_design"]["services"][0]["name"] == "posting-service"
```

- [ ] **Step 6: Run it (verifies the existing readers now have writers)**

Run: `uv run pytest tests/unit/test_build_brief_e2e.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cobol_modernizer/controlplane/build.py tests/unit/test_build_generated_test_refs.py tests/unit/test_build_brief_e2e.py
git commit -m "feat: record generated test refs and prove backlog+tech-design reach codegen brief"
```

---

## Task 12: Story-behavior gate in the Verify stage

**Files:**
- Modify: `src/cobol_modernizer/controlplane/verify.py`
- Test: `tests/integration/test_verify_story_behavior_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_verify_story_behavior_gate.py
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.controlplane.verify import evaluate_story_behavior
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Workspace(id="ws-1", name="m", repo_slug="r", created_by="t"))
    s.add(JourneyStage(workspace_id="ws-1", stage_key="verify", ordinal=12, status="running"))
    s.commit()
    return s


def test_gate_passes_when_all_stories_have_tests_and_equivalence():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "passed"


def test_gate_blocks_when_equivalence_failed():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="fail")
    s.flush()
    assert gate.status == "open"
    assert "US-1" in str(gate.result)


def test_gate_blocks_when_acceptance_test_missing():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=[], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "open"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_verify_story_behavior_gate.py -q`
Expected: FAIL — `evaluate_story_behavior` missing.

- [ ] **Step 3: Implement `evaluate_story_behavior` and call it from `run_verify`**

Add to `src/cobol_modernizer/controlplane/verify.py`:

```python
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.slice.gates import story_behavior_gate


def evaluate_story_behavior(session, workspace_id: str, *, stories: list[dict],
                            generated_test_refs: list[str], equivalence_verdict: str):
    """Aggregate per-story behavior gates into one verify-stage story_behavior gate.
    A normalized equivalence verdict of 'pass' maps to story_behavior_gate's 'passed'."""
    verdict = "passed" if equivalence_verdict == "pass" else equivalence_verdict
    failures: list[dict] = []
    for story in stories:
        ac_ids = [c.get("id") for c in story.get("acceptance_criteria", []) if c.get("id")]
        res = story_behavior_gate(story_id=story.get("id", "?"),
                                  acceptance_criteria_ids=ac_ids,
                                  generated_test_refs=generated_test_refs,
                                  equivalence_verdict=verdict)
        if not res["passed"]:
            failures.append(res)
    passed = not failures
    return upsert_gate(session, workspace_id, "verify", "story_behavior",
                       passed=passed, result={"failures": failures},
                       threshold={"all_stories_verified": True})
```

In `run_verify`, after equivalence completes (where `result.report.verdict` is known), read the
persisted backlog stories and the recorded `generated_test_refs` artifact, then call it:

```python
    backlog_node = BacklogStorage(neo4j).get_latest(workspace.repo_slug)
    stories = json.loads(backlog_node.get("stories_json") or "[]") if backlog_node else []
    refs_art = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace.id,
                               Artifact.kind == "generated_test_refs")
        .order_by(Artifact.version.desc())
    ).scalars().first()
    test_refs = (refs_art.evidence_map or {}).get("acceptance_criteria", []) if refs_art else []
    if stories:
        evaluate_story_behavior(session, workspace.id, stories=stories,
                                generated_test_refs=test_refs,
                                equivalence_verdict=result.report.verdict)
```

Add imports to `verify.py`: `import json`, `from sqlalchemy import select`,
`from cobol_modernizer.backlog.storage import BacklogStorage`,
`from cobol_modernizer.persistence.tables import Artifact`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_verify_story_behavior_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Run the verify integration suite to confirm no regression**

Run: `uv run pytest tests/integration/test_controlplane_verify_api.py tests/integration/test_verify_story_behavior_gate.py -q`
Expected: PASS (if a verify API test exists; otherwise just the new one).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/verify.py tests/integration/test_verify_story_behavior_gate.py
git commit -m "feat: story-behavior gate on verify stage"
```

---

## Task 13: Backend full-suite green checkpoint

**Files:** none (verification only)

- [ ] **Step 1: Run the whole Python suite**

Run: `uv run pytest -q 2>&1 | tail -30`
Expected: all pass. If failures trace to the stage renumber (Task 1) or the retired `/design`
route (Task 10), fix the asserted ordinals/routes in those tests. Do not weaken assertions about
new behavior.

- [ ] **Step 2: Commit any test fixups**

```bash
git add -A
git commit -m "test: align suite with new backlog stage and technical-design route"
```

---

## Task 14: Web — mirror the backlog stage and add API client

**Files:**
- Modify: `web/src/lib/stages.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/components/screens/StageScreen.tsx`
- Test: `web/src/components/screens/stageDispatch.test.tsx` (extend)

- [ ] **Step 1: Write the failing dispatch test addition**

In `web/src/components/screens/stageDispatch.test.tsx`, add a case asserting the `backlog`
stage renders the `BacklogStudio` (follow the existing pattern in that file for how screens are
asserted — e.g. render `<StageScreen stageKey="backlog" .../>` and assert a backlog-specific
testid/text like `"Business Backlog"`).

```tsx
it("dispatches the backlog stage to BacklogStudio", () => {
  render(<StageScreen workspaceId="ws-1" stageKey="backlog" repoSlug="carddemo-mini" />);
  expect(screen.getByText(/Business Backlog/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/stageDispatch.test.tsx`
Expected: FAIL — backlog falls through to the default `Stage: backlog` div.

- [ ] **Step 3: Add the stage to `stages.ts`**

In `web/src/lib/stages.ts`, insert into `STAGES` after the `blueprint` entry:

```ts
  { key: "backlog", label: "Backlog", gateKey: "backlog_coverage" },
```

In `PHASES`, add `"backlog"` to the `"design"` band's `stageKeys` (right after `"blueprint"`):

```ts
  { key: "design", label: "Design", stageKeys: ["blueprint", "backlog", "seams", "plan", "domain", "design"] },
```

Add `"backlog"` to `ADVANCEABLE_STAGES`.

- [ ] **Step 4: Add API client functions in `web/src/lib/api.ts`**

Follow the existing fetcher pattern in that file (match the helper used by blueprint — same base
URL + JSON handling). Add:

```ts
export interface BacklogStatus {
  status: "idle" | "running" | "done" | "error";
  result: { repo_slug: string; version: number; epics: number; stories: number; coverage_ratio: number | null } | null;
  error: string | null;
}

export async function getBacklog(workspaceId: string): Promise<BacklogStatus> {
  return apiGet(`/api/workspaces/${workspaceId}/backlog`);
}
export async function generateBacklog(workspaceId: string): Promise<BacklogStatus> {
  return apiPost(`/api/workspaces/${workspaceId}/backlog`);
}

export interface TechnicalDesignStatus {
  status: "idle" | "running" | "done" | "error";
  result: { repo_slug: string; version: number; services: number } | null;
  error: string | null;
}
export async function getTechnicalDesign(workspaceId: string): Promise<TechnicalDesignStatus> {
  return apiGet(`/api/workspaces/${workspaceId}/technical-design`);
}
export async function generateTechnicalDesign(workspaceId: string): Promise<TechnicalDesignStatus> {
  return apiPost(`/api/workspaces/${workspaceId}/technical-design`);
}
```

Use whatever the existing `apiGet`/`apiPost` (or equivalent) helpers are named in `api.ts`; match
the file's current convention. The backlog HTML view uses `/api/workspaces/{id}/backlog/html` and
the technical-design HTML uses `/api/workspaces/{id}/technical-design/html` (loaded in an iframe,
like the blueprint HTML view).

- [ ] **Step 5: Register the screen in `StageScreen.tsx`**

Add the import and case (the component is created in Task 15; this will not compile until then —
that's fine for a single commit boundary, so do Step 5 and Task 15 together before running tsc):

```tsx
import { BacklogStudio } from "@/components/screens/BacklogStudio";
...
    case "backlog": return <BacklogStudio workspaceId={workspaceId} />;
```

- [ ] **Step 6: Commit (with Task 15 — they compile together)**

Deferred to Task 15's commit.

---

## Task 15: Web — BacklogStudio screen

**Files:**
- Create: `web/src/components/screens/BacklogStudio.tsx`
- Create: `web/src/components/screens/BacklogStudio.test.tsx`
- Modify: `web/src/test/handlers.ts` (MSW)

- [ ] **Step 1: Write the failing screen test**

```tsx
// web/src/components/screens/BacklogStudio.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BacklogStudio } from "@/components/screens/BacklogStudio";

describe("BacklogStudio", () => {
  it("renders backlog status with story count and coverage", async () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    expect(screen.getByText(/Business Backlog/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/stories/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Add an MSW handler**

In `web/src/test/handlers.ts`, add (matching the existing handler style in that file):

```ts
http.get("*/api/workspaces/:wid/backlog", () =>
  HttpResponse.json({
    status: "done",
    result: { repo_slug: "carddemo-mini", version: 1, epics: 2, stories: 5, coverage_ratio: 0.86 },
    error: null,
  })),
http.post("*/api/workspaces/:wid/backlog", () =>
  HttpResponse.json({ status: "running", result: null, error: null })),
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/BacklogStudio.test.tsx`
Expected: FAIL — `BacklogStudio` module missing.

- [ ] **Step 4: Implement `BacklogStudio.tsx`**

Model it on `BlueprintStudio.tsx` (poll status; Generate button; coverage banner; iframe to the
`/backlog/html` view). Minimum viable implementation:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { type BacklogStatus, generateBacklog, getBacklog } from "@/lib/api";

export function BacklogStudio({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<BacklogStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setState(await getBacklog(workspaceId));
  }, [workspaceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (state?.status !== "running") return;
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [state?.status, refresh]);

  const onGenerate = async () => {
    setBusy(true);
    try {
      setState(await generateBacklog(workspaceId));
    } finally {
      setBusy(false);
    }
  };

  const r = state?.result;
  const pct = r?.coverage_ratio != null ? Math.round(r.coverage_ratio * 100) : null;

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Business Backlog</h2>
        <button
          onClick={onGenerate}
          disabled={busy || state?.status === "running"}
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {state?.status === "running" ? "Generating…" : "Generate backlog"}
        </button>
      </div>
      {r && (
        <div className="text-sm text-zinc-600">
          {r.epics} epics · {r.stories} stories
          {pct != null && <> · BRD logic coverage {pct}%</>}
        </div>
      )}
      {state?.error && <div className="text-sm text-red-600">{state.error}</div>}
      {state?.status === "done" && (
        <iframe
          title="backlog"
          src={`/api/workspaces/${workspaceId}/backlog/html`}
          className="h-[60vh] w-full rounded border border-zinc-200"
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npx vitest run src/components/screens/BacklogStudio.test.tsx src/components/screens/stageDispatch.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit (Tasks 14 + 15 together)**

```bash
git add web/src/lib/stages.ts web/src/lib/api.ts web/src/components/screens/StageScreen.tsx web/src/components/screens/BacklogStudio.tsx web/src/components/screens/BacklogStudio.test.tsx web/src/components/screens/stageDispatch.test.tsx web/src/test/handlers.ts
git commit -m "feat: backlog cockpit screen wired to backend"
```

---

## Task 16: Web — DesignStudio renders the technical design

**Files:**
- Modify: `web/src/components/screens/DesignStudio.tsx`
- Modify: `web/src/components/screens/DesignStudio.test.tsx`
- Modify: `web/src/test/handlers.ts`

- [ ] **Step 1: Update the screen test**

Replace the body assertions in `DesignStudio.test.tsx` to expect technical-design content (a
Generate button + service count + html iframe), mirroring the BacklogStudio test:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DesignStudio } from "@/components/screens/DesignStudio";

describe("DesignStudio", () => {
  it("renders technical design status with service count", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    expect(screen.getByText(/Technical Design/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/services/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Add MSW handlers**

In `web/src/test/handlers.ts`:

```ts
http.get("*/api/workspaces/:wid/technical-design", () =>
  HttpResponse.json({
    status: "done",
    result: { repo_slug: "carddemo-mini", version: 1, services: 3 },
    error: null,
  })),
http.post("*/api/workspaces/:wid/technical-design", () =>
  HttpResponse.json({ status: "running", result: null, error: null })),
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/DesignStudio.test.tsx`
Expected: FAIL — old DesignStudio renders legacy writer-slice content.

- [ ] **Step 4: Rewrite `DesignStudio.tsx`**

Mirror `BacklogStudio.tsx`, swapping the API calls and labels:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { type TechnicalDesignStatus, generateTechnicalDesign, getTechnicalDesign } from "@/lib/api";

export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<TechnicalDesignStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setState(await getTechnicalDesign(workspaceId));
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (state?.status !== "running") return;
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [state?.status, refresh]);

  const onGenerate = async () => {
    setBusy(true);
    try { setState(await generateTechnicalDesign(workspaceId)); }
    finally { setBusy(false); }
  };

  const r = state?.result;
  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Technical Design</h2>
        <button onClick={onGenerate} disabled={busy || state?.status === "running"}
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {state?.status === "running" ? "Generating…" : "Generate technical design"}
        </button>
      </div>
      {r && <div className="text-sm text-zinc-600">{r.services} services</div>}
      {state?.error && <div className="text-sm text-red-600">{state.error}</div>}
      {state?.status === "done" && (
        <iframe title="technical-design"
          src={`/api/workspaces/${workspaceId}/technical-design/html`}
          className="h-[60vh] w-full rounded border border-zinc-200" />
      )}
    </div>
  );
}
```

If `DesignStudio` was previously imported with extra props in `StageScreen.tsx`, reduce its call
to `<DesignStudio workspaceId={workspaceId} />`.

- [ ] **Step 5: Run tests + typecheck + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx next build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/screens/DesignStudio.tsx web/src/components/screens/DesignStudio.test.tsx web/src/test/handlers.ts
git commit -m "feat: design stage screen renders technical design"
```

---

## Task 17: Final end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full Python suite**

Run: `uv run pytest -q 2>&1 | tail -20`
Expected: all pass.

- [ ] **Step 2: Full web suite + typecheck + build**

Run: `cd web && npm test && npx tsc --noEmit && npx next build`
Expected: all green.

- [ ] **Step 3: Verify the 25 original plan tests still pass**

Run: `uv run pytest tests/unit/test_traceability_coverage.py tests/unit/test_backlog_schema.py tests/unit/test_backlog_generator.py tests/unit/test_backlog_dependency.py tests/unit/test_domain_uses_backlog.py tests/unit/test_technical_design_schema.py tests/unit/test_build_uses_story_and_technical_design.py tests/unit/test_codegen_generator.py tests/unit/test_story_behavior_gate.py -q`
Expected: PASS.

- [ ] **Step 4: Commit any final fixups and summarize**

```bash
git add -A
git commit -m "test: full e2e green for thoughtworks-aligned chain" || echo "nothing to commit"
```

---

## Execution Order

1. Task 1 — backlog journey stage (unblocks gate stage-id resolution and UI mirror).
2. Task 2 — gate upsert helper (used by Tasks 6, 10, 12).
3. Task 3 — backlog storage.
4. Task 4 — backlog renderer.
5. Task 5 — backlog generation helper.
6. Task 6 — backlog stage endpoint (first runtime use of generator/parser/DAG/coverage).
7. Task 7 — domain consumes backlog.
8. Task 8 — technical design generator.
9. Task 9 — technical design storage + renderer.
10. Task 10 — technical design endpoint + retire legacy design.
11. Task 11 — build records test refs + brief e2e proof.
12. Task 12 — verify story-behavior gate.
13. Task 13 — backend full-suite checkpoint.
14. Task 14 — web stage mirror + API client.
15. Task 15 — BacklogStudio screen.
16. Task 16 — DesignStudio technical design.
17. Task 17 — final e2e verification.

Each task leaves the suite green and the chain a little more connected.

## Validation Commands

After each backend task:
```bash
uv run pytest -q 2>&1 | tail -20
```

After each web task (Tasks 14-16):
```bash
cd web && npx vitest run && npx tsc --noEmit
```

Final:
```bash
uv run pytest -q && (cd web && npm test && npx tsc --noEmit && npx next build)
```

## Self-Review

**Spec coverage:**
- Dead generators wired → Tasks 6 (backlog generator/parser/DAG/coverage), 7 (domain backlog), 12 (story_behavior_gate).
- Read-without-write persistence fixed → Tasks 3 (`:Backlog`), 9 (`:TechnicalDesign`), proven by Task 11 e2e brief test.
- Domain backlog no-op fixed → Task 7.
- Technical Design completed (generator + endpoint) → Tasks 8, 9, 10.
- Backlog API placeholder replaced → Task 6.
- UI surface → Tasks 14, 15, 16.
- Gates block-with-override → Task 2 (helper preserves `waived`/`passed`/`failed`), wired in Tasks 6 (backlog_coverage + brd_logic_coverage), 10 (design_data_ownership), 12 (story_behavior); override uses the existing `POST /gates/{gate_id}/approval` `waived_with_risk` route (unchanged).
- New backlog stage + technical design replaces design → Tasks 1, 10, 14.
- `BACKLOG_COVERAGE_MIN` default 0.8 → Task 6 `_coverage_min()`.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only "match the existing
convention" notes (Task 14 `apiGet`/`apiPost`, Task 15/16 styling) are because those helpers already
exist in the repo and must not be re-invented — the engineer reads `api.ts`/`BlueprintStudio.tsx` to
match them.

**Type consistency:**
- `upsert_gate(session, workspace_id, stage_key, gate_key, *, passed, result, threshold)` — same signature in Tasks 2, 6, 10, 12.
- `BacklogStorage.save(backlog, *, coverage, html, model, token_usage=None)` / `.get_latest(repo_slug)` — Tasks 3, 6, 7, 10, 12.
- `TechnicalDesignStorage.save(design, *, html, model, token_usage=None)` / `.get_latest(repo_slug)` — Tasks 9, 10.
- `parse_technical_design_payload(raw, *, repo_slug, known_refs, known_story_ids, known_contexts)` — Tasks 8, 10.
- `generate_backlog_payload(*, runner, model, timeout_s, brd_sections, known_refs, known_requirement_ids)` and `generate_technical_design_payload(*, runner, model, timeout_s, ddd_json, backlog_json, seam_waves_json, graph_summary)` — async, returned dict, injected in tests.
- `scan_generated_test_refs(project_dir, acceptance_criteria_ids)` — Tasks 11, 12 (refs flow build→artifact→verify).
- Node property names (`epics_json`, `stories_json`, `services_json`, `coverage_json`, `version`) match `build.py` readers and the storage `_SAVE`/`_LATEST` Cypher.
- Stage keys (`backlog`, `design`) and gate keys (`backlog_coverage`, `brd_logic_coverage`, `design_data_ownership`, `story_behavior`) consistent across backend + `stages.ts`.
