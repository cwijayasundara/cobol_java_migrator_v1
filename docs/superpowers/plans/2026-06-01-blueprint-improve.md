# Blueprint Improve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-directed, graph-grounded "Improve" action that refines the current BRD per a free-text instruction and saves it as a new version.

**Architecture:** A new single-agent improve path reuses the BRD graph tools/harness/judge/storage. `POST /blueprint/improve {instruction}` runs a background job that loads the latest BRD, runs a graph-navigating agent seeded with the current BRD + instruction, re-judges (Haiku), and saves a new version. The frontend adds an instruction box + "Improve" button driven by `useJob`.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, Neo4j, `claude-agent-sdk` via the existing `SdkAgentRunner`, the in-process `jobs.runner`; Next.js 15 / React 19 / Vitest / MSW.

**Spec:** `docs/superpowers/specs/2026-06-01-blueprint-improve-design.md`

**Conventions:**
- TDD: failing test → see it fail → minimal impl → see it pass → commit.
- Python tests: `PYTHONPATH=src .venv/bin/python -m pytest <path> -v`. Web: `cd web && npx vitest run <path>`.
- Reuse, don't duplicate: the improve agent reuses `build_graph_server`, `GRAPH_TOOL_NAMES`, `brd_draft_schema`, `ajudge`, `render_html`, `BRDStorage`.
- The improve agent must NEVER return an empty draft to save — raise instead, so a failed run leaves the prior version intact.
- There is unrelated uncommitted WIP in the tree (graph.py, queries.py, web cockpit files). Do NOT stage it; commit only the explicit paths in each task.
- If git reports an `index.lock` error, run `rm -f .git/index.lock` once and retry.

---

## Phase 1 — Storage: persist structured BRD + reconstruct (no LLM)

### Task 1: Persist `sections`/`evidence_map` and add `reconstruct_draft`

**Files:**
- Modify: `src/cobol_modernizer/brd/storage.py`
- Test: `tests/unit/test_brd_storage_structured.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_brd_storage_structured.py
import json

from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.agent.brd_schema import BRDDraft


def test_reconstruct_draft_from_structured_node():
    node = {
        "sections": json.dumps([{"title": "Executive Summary",
                                 "body_markdown": "hello", "requirements": []}]),
        "evidence_map": json.dumps({"FR-1": ["CBACT01M"]}),
        "html": "<html>ignored</html>",
    }
    draft = BRDStorage.reconstruct_draft(node)
    assert isinstance(draft, BRDDraft)
    assert draft.sections[0].title == "Executive Summary"
    assert draft.evidence_map == {"FR-1": ["CBACT01M"]}


def test_reconstruct_draft_returns_none_for_legacy_html_only_node():
    # legacy BRD nodes (pre-feature) have no structured fields -> None (HTML fallback)
    assert BRDStorage.reconstruct_draft({"html": "<html>old</html>"}) is None
    assert BRDStorage.reconstruct_draft({"sections": None, "evidence_map": None}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_storage_structured.py -v`
Expected: FAIL (`AttributeError: type object 'BRDStorage' has no attribute 'reconstruct_draft'`).

- [ ] **Step 3: Add the staticmethod + persist the fields**

In `src/cobol_modernizer/brd/storage.py`, add the import at the top (next to existing imports):

```python
from cobol_modernizer.agent.brd_schema import BRDDraft
```

Add this staticmethod to the `BRDStorage` class (place it near `get_latest`):

```python
    @staticmethod
    def reconstruct_draft(node: dict) -> BRDDraft | None:
        """Rebuild the structured BRDDraft from a stored :BRD node. Returns None for
        legacy nodes that predate structured persistence (caller falls back to html)."""
        sections = node.get("sections")
        evidence = node.get("evidence_map")
        if not sections:
            return None
        try:
            return BRDDraft.model_validate({
                "sections": json.loads(sections),
                "evidence_map": json.loads(evidence) if evidence else {},
            })
        except Exception:  # noqa: BLE001 — malformed legacy data -> fall back to html
            return None
```

Modify `save(...)` to accept and persist the structured form. Change the signature to add two optional params (keep them optional so existing callers/tests are unaffected):

```python
    def save(
        self,
        *,
        repo_id: str,
        html: str,
        judge_report: JudgeReport,
        attempt_history: list[AttemptRecord],
        model: str,
        strategy: Strategy,
        token_usage: dict[str, int],
        sections: list[dict] | None = None,
        evidence_map: dict[str, list[str]] | None = None,
    ) -> BRDResult:
```

In the `CREATE (b:BRD {...})` map, add two properties after `token_usage: $token_usage,`:

```python
                sections: $sections,
                evidence_map: $evidence_map,
```

And in the `self.client.run(...)` kwargs, add (next to `token_usage=...`):

```python
            sections=json.dumps(sections) if sections is not None else None,
            evidence_map=json.dumps(evidence_map) if evidence_map is not None else None,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_storage_structured.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Regression — existing BRD storage/grounded tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -k "brd or storage" -q`
Expected: PASS (the new save params are optional; existing callers unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/brd/storage.py tests/unit/test_brd_storage_structured.py
git commit -m "feat(brd): persist structured sections/evidence_map + reconstruct_draft (html fallback)"
```
End the commit body with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

### Task 2: Generate path persists the structured BRD

**Files:**
- Modify: `src/cobol_modernizer/brd/pipeline.py` (the `storage.save(...)` call in `generate_brd_graph_sync`, ~line 182)
- Test: `tests/unit/test_brd_storage_structured.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_brd_storage_structured.py`:

```python
def test_save_passes_sections_to_client(monkeypatch):
    captured = {}

    class _FakeClient:
        def run(self, query, **params):
            captured.update(params)
            return [{"version": 2}]

    from cobol_modernizer.brd.schema import (
        BRD, Strategy, JudgeReport, Rating, Dimension, DimensionScore,
    )
    from cobol_modernizer.brd.schema import BRDSection
    st = BRDStorage(_FakeClient())
    report = JudgeReport(
        dimensions={d: DimensionScore(score=4, rationale="") for d in Dimension},
        weighted_score=4.0, rating=Rating.high, feedback=[], groundedness_failures=[])
    # monkeypatch the html writer so no disk IO
    monkeypatch.setattr(BRDStorage, "_write_html", lambda self, r, v, h: __import__("pathlib").Path("/tmp/x.html"))
    st.save(repo_id="demo", html="<html/>", judge_report=report, attempt_history=[],
            model="m", strategy=Strategy.single_shot, token_usage={},
            sections=[{"title": "Scope", "body_markdown": "s", "requirements": []}],
            evidence_map={"FR-1": ["P1"]})
    import json as _json
    assert _json.loads(captured["sections"])[0]["title"] == "Scope"
    assert _json.loads(captured["evidence_map"]) == {"FR-1": ["P1"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_storage_structured.py::test_save_passes_sections_to_client -v`
Expected: This should already PASS if Task 1 added the params (the test exercises Task 1's storage change directly). If it FAILS, fix Task 1's `save`. Then continue — Task 2's production change is wiring the generate path.

- [ ] **Step 3: Wire the generate path to pass the structured BRD**

In `src/cobol_modernizer/brd/pipeline.py`, find the final `return storage.save(...)` in `generate_brd_graph_sync` and add the two structured args from `result.brd`:

```python
    return storage.save(
        repo_id=repo_id, html=html, judge_report=result.report,
        attempt_history=result.attempt_history, model=model,
        strategy=result.strategy,
        token_usage=dict(runner.token_usage),
        sections=[s.model_dump(mode="json") for s in result.brd.sections],
        evidence_map=result.brd.evidence_map,
    )
```

(Read the existing call first to match its exact keyword args; only ADD the two new lines.)

- [ ] **Step 4: Regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -k "brd or pipeline or blueprint" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/brd/pipeline.py tests/unit/test_brd_storage_structured.py
git commit -m "feat(brd): generate path persists structured sections/evidence_map"
```
End body with the Co-Authored-By line.

---

## Phase 2 — The improve agent

### Task 3: `agenerate_brd_improvement`

**Files:**
- Create: `src/cobol_modernizer/agent/brd_improve.py`
- Test: `tests/unit/test_brd_improve_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_brd_improve_agent.py
import pytest

from cobol_modernizer.agent.brd_improve import agenerate_brd_improvement
from cobol_modernizer.agent.brd_schema import BRDDraft
from cobol_modernizer.brd.schema import Strategy


class _Runner:
    def __init__(self):
        self.seen = {}

    async def run_structured(self, **kw):
        self.seen = kw
        return {"sections": [{"title": "Non-functional Requirements",
                              "body_markdown": "added detail", "requirements": []}],
                "evidence_map": {"NFR-1": ["CBACT01M"]}}


class _EmptyRunner:
    async def run_structured(self, **kw):
        return {}


def _deps():
    # build_graph_server only needs deps for tool binding; the FakeRunner never calls
    # the tools, so a minimal object is fine. Use a real GraphDeps with a stub client.
    from cobol_modernizer.agent.deps import GraphDeps
    from pathlib import Path

    class _C:
        def run(self, *a, **k):
            return []
    return GraphDeps(client=_C(), repo_id="demo", repo_path=Path("/tmp"))


async def test_improve_passes_current_brd_and_instruction_and_returns_draft():
    r = _Runner()
    draft, strategy = await agenerate_brd_improvement(
        _deps(), current_brd="## Current BRD\n(old content)",
        instruction="expand the non-functional requirements",
        runner=r, model="m", max_turns=20, timeout_s=10)
    assert isinstance(draft, BRDDraft)
    assert strategy == Strategy.single_shot
    assert draft.sections[0].title == "Non-functional Requirements"
    # the prompt must carry both the current BRD and the instruction
    assert "(old content)" in r.seen["prompt"]
    assert "expand the non-functional requirements" in r.seen["prompt"]
    assert r.seen["label"] == "brd-improve"


async def test_improve_raises_on_empty_output():
    with pytest.raises(ValueError):
        await agenerate_brd_improvement(
            _deps(), current_brd="x", instruction="y",
            runner=_EmptyRunner(), model="m", max_turns=20, timeout_s=10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_improve_agent.py -v`
Expected: FAIL (ImportError). (Async tests run under the repo's asyncio auto-mode; if reported skipped, STOP and report NEEDS_CONTEXT.)

- [ ] **Step 3: Implement**

```python
# src/cobol_modernizer/agent/brd_improve.py
"""Instruction-directed, graph-grounded BRD refinement: ONE agent seeded with the
current BRD + a user instruction, using the same graph tools as the draft agent, with
a hard timeout. Raises on empty output so a failed improve never overwrites the prior
version (the pipeline only saves a valid draft)."""
from __future__ import annotations

import asyncio

from cobol_modernizer.agent.advisor import ADVISOR_TOOL_NAME
from cobol_modernizer.agent.brd_schema import BRDDraft, brd_draft_schema
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.brd.schema import Strategy

IMPROVE_SYSTEM = """You are refining an EXISTING Business Requirements Document for a
codebase. Apply the user's improvement instruction. You have graph-navigation tools —
use them to add ONLY grounded detail (real entity ids / file paths you actually inspect:
get_source_slice, neighbors, find_entities, integration_points, ...). PRESERVE correct
existing content and every still-valid evidence pointer; do not invent identifiers.
Keep the same 11 sections. Emit the full improved BRDDraft JSON (sections + evidence_map:
requirement_id -> [entity_or_path])."""


def _improve_prompt(current_brd: str, instruction: str) -> str:
    return ("## Current BRD\n" + current_brd
            + "\n\n## Improvement instruction\n" + instruction
            + "\n\nApply the instruction and emit the full improved BRDDraft.")


async def agenerate_brd_improvement(deps: GraphDeps, *, current_brd: str,
                                    instruction: str, runner: AgentRunner, model: str,
                                    max_turns: int, timeout_s: float,
                                    advisor=None, advisor_max_uses: int = 3
                                    ) -> tuple[BRDDraft, Strategy]:
    server = build_graph_server(deps, advisor=advisor, advisor_max_uses=advisor_max_uses)
    tools = list(GRAPH_TOOL_NAMES) + ([ADVISOR_TOOL_NAME] if advisor is not None else [])
    raw = await asyncio.wait_for(
        runner.run_structured(
            system=IMPROVE_SYSTEM, prompt=_improve_prompt(current_brd, instruction),
            server=server, allowed_tools=tools, model=model, max_turns=max_turns,
            schema=brd_draft_schema(), label="brd-improve"),
        timeout=timeout_s)
    if not raw or not raw.get("sections"):
        raise ValueError("improve agent produced no usable BRD draft")
    return BRDDraft.model_validate(raw), Strategy.single_shot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_improve_agent.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/agent/brd_improve.py tests/unit/test_brd_improve_agent.py
git commit -m "feat(brd): graph-grounded improve agent (instruction-seeded, timeout, raise-on-empty)"
```
End body with the Co-Authored-By line.

---

## Phase 3 — Pipeline entry point

### Task 4: `improve_brd_graph_sync`

**Files:**
- Modify: `src/cobol_modernizer/brd/pipeline.py`
- Test: `tests/unit/test_brd_improve_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_brd_improve_pipeline.py
import json

import pytest

import cobol_modernizer.brd.pipeline as pipe
from cobol_modernizer.brd.schema import (
    BRDResult, Rating, Strategy, JudgeReport, Dimension, DimensionScore,
)


class _Storage:
    def __init__(self):
        self.saved = None

    def get_latest(self, repo_id):
        return {"sections": json.dumps([{"title": "Scope", "body_markdown": "old",
                                         "requirements": []}]),
                "evidence_map": json.dumps({"FR-1": ["CBACT01M"]}),
                "html": "<html>old</html>"}

    def save(self, **kw):
        self.saved = kw
        from datetime import datetime, timezone
        return BRDResult(brd_id="b2", repo_id=kw["repo_id"], version=2,
                         rating=kw["judge_report"].rating,
                         weighted_score=kw["judge_report"].weighted_score,
                         attempts=1, attempt_history=[], model=kw["model"],
                         strategy=kw["strategy"], html_path="/tmp/v2.html",
                         created_at=datetime.now(timezone.utc), token_usage={})


async def _fake_improve(deps, *, current_brd, instruction, runner, model, max_turns,
                        timeout_s, **kw):
    from cobol_modernizer.agent.brd_schema import BRDDraft
    assert "old" in current_brd and instruction == "expand NFRs"
    return BRDDraft.model_validate(
        {"sections": [{"title": "Non-functional Requirements",
                       "body_markdown": "more", "requirements": []}],
         "evidence_map": {"NFR-1": ["CBACT01M"]}}), Strategy.single_shot


async def _fake_judge(brd, deps, *, runner, model):
    return JudgeReport(
        dimensions={d: DimensionScore(score=4, rationale="") for d in Dimension},
        weighted_score=4.0, rating=Rating.high, feedback=[], groundedness_failures=[])


def test_improve_pipeline_loads_latest_runs_agent_saves_new_version(monkeypatch):
    storage = _Storage()
    monkeypatch.setattr(pipe, "render_html", lambda brd: "<html>new</html>")
    monkeypatch.setattr("cobol_modernizer.agent.brd_improve.agenerate_brd_improvement",
                        _fake_improve)
    monkeypatch.setattr("cobol_modernizer.agent.brd_judge.ajudge", _fake_judge)

    class _Client:
        def run(self, *a, **k):
            return []
    result = pipe.improve_brd_graph_sync(
        "demo", "expand NFRs", client=_Client(), repo_path="/tmp", storage=storage)
    assert result.version == 2
    # saved the improved structured BRD as a new version
    assert storage.saved["sections"][0]["title"] == "Non-functional Requirements"


def test_improve_pipeline_raises_when_no_brd(monkeypatch):
    class _NoStorage:
        def get_latest(self, repo_id):
            return None

    class _Client:
        def run(self, *a, **k):
            return []
    with pytest.raises(ValueError):
        pipe.improve_brd_graph_sync("demo", "x", client=_Client(), repo_path="/tmp",
                                    storage=_NoStorage())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_improve_pipeline.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'improve_brd_graph_sync'`).

- [ ] **Step 3: Implement `improve_brd_graph_sync` in `pipeline.py`**

Add near `generate_brd_graph_sync` (reuse the existing module imports: `asyncio`, `os`, `Path`, `render_html`, `BRDStorage`, `resolve_model`, `HAIKU`, `SONNET`, `GLOBAL_ENV`, `BRD`, `AttemptRecord`, `Strategy`, `_log_timing`, `_draft_to_brd`):

```python
def improve_brd_graph_sync(repo_id: str, instruction: str, *, client=None,
                           repo_path=None, model: str | None = None,
                           max_turns: int | None = None,
                           storage: "BRDStorage | None" = None) -> BRDResult:
    """Refine the latest BRD per `instruction` (graph-grounded), re-judge, save a NEW
    version. Raises ValueError if no BRD exists yet (endpoint maps this to 409)."""
    import time
    from cobol_modernizer.agent.brd_improve import agenerate_brd_improvement
    from cobol_modernizer.agent.brd_judge import ajudge
    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.harness import SdkAgentRunner

    if client is None:
        from cobol_modernizer.neo4j_client import Neo4jClient
        client = Neo4jClient()
    if repo_path is None:
        from cobol_modernizer.repo_manager import RepoManager
        repo = RepoManager(client).get(repo_id)
        if repo is None or not repo.get("local_path"):
            raise ValueError(f"Repo {repo_id} not registered or missing local_path")
        repo_path = repo["local_path"]
    if storage is None:
        storage = BRDStorage(client)

    latest = storage.get_latest(repo_id)
    if not latest:
        raise ValueError(f"no BRD to improve for {repo_id} — generate a blueprint first")
    draft = storage.reconstruct_draft(latest)
    current_brd = (draft.model_dump_json() if draft is not None
                   else (latest.get("html") or ""))

    model = model or resolve_model("brd")
    judge_pin = os.getenv("BRD_JUDGE_MODEL") or os.getenv(GLOBAL_ENV)
    judge_model = judge_pin or HAIKU
    max_turns = int(os.getenv("BRD_AGENT_MAX_TURNS", "45")) if max_turns is None else max_turns
    timeout_s = float(os.getenv("BLUEPRINT_IMPROVE_TIMEOUT_S", "600"))

    deps = GraphDeps(client=client, repo_id=repo_id, repo_path=Path(repo_path))
    runner = SdkAgentRunner()
    wall_start = time.monotonic()
    improved, strategy = asyncio.run(agenerate_brd_improvement(
        deps, current_brd=current_brd, instruction=instruction, runner=runner,
        model=model, max_turns=max_turns, timeout_s=timeout_s))
    brd = _draft_to_brd(improved, repo_id, model, strategy)
    report = asyncio.run(ajudge(brd, deps, runner=runner, model=judge_model))
    _log_timing(repo_id, 0, False, model, runner, time.monotonic() - wall_start)

    html = render_html(brd)
    return storage.save(
        repo_id=repo_id, html=html, judge_report=report,
        attempt_history=[AttemptRecord(attempt=1, rating=report.rating,
                                       weighted_score=report.weighted_score,
                                       feedback=report.feedback)],
        model=model, strategy=strategy, token_usage=dict(runner.token_usage),
        sections=[s.model_dump(mode="json") for s in brd.sections],
        evidence_map=brd.evidence_map)
```

NOTE: the test monkeypatches `agenerate_brd_improvement` and `ajudge` at their module paths; the function imports them locally (inside the function), so the monkeypatch must target those module attributes — keep the local imports as written so `monkeypatch.setattr("cobol_modernizer.agent.brd_improve.agenerate_brd_improvement", …)` takes effect. (Both `asyncio.run` calls are fine because each awaits a single coroutine.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_brd_improve_pipeline.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -k "brd or pipeline" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/brd/pipeline.py tests/unit/test_brd_improve_pipeline.py
git commit -m "feat(brd): improve_brd_graph_sync — load latest, refine, re-judge, save new version"
```
End body with the Co-Authored-By line.

---

## Phase 4 — Endpoints

### Task 5: `POST/GET /blueprint/improve`

**Files:**
- Modify: `src/cobol_modernizer/controlplane/blueprint.py`
- Test: `tests/integration/test_controlplane_blueprint_improve.py` (create)

- [ ] **Step 1: Write the failing test** (mirror `tests/integration/test_controlplane_blueprint_api.py`'s fixture)

```python
# tests/integration/test_controlplane_blueprint_improve.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.brd.schema import BRDResult, Rating, Strategy
from cobol_modernizer.controlplane import blueprint as bp, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class _FakeNeo4j:
    def __init__(self, has_brd=True):
        self.has_brd = has_brd

    def run(self, query, **params):
        if "ORDER BY b.version DESC" in query:   # get_latest
            return [{"b": {"version": 1, "html": "<html>v1</html>"}}] if self.has_brd else []
        return []

    def close(self):
        pass


def _improved(slug, instruction, **kw):
    return BRDResult(brd_id="b2", repo_id=slug, version=2, rating=Rating.high,
                     weighted_score=4.4, attempts=1, attempt_history=[],
                     model="claude-sonnet-4-6", strategy=Strategy.single_shot,
                     html_path="/tmp/v2.html", created_at=datetime.now(timezone.utc),
                     token_usage={})


def _setup(monkeypatch, has_brd=True):
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
            yield ss; ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j(has_brd=has_brd)
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    monkeypatch.setattr(bp, "improve_brd_graph_sync", _improved)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app)


def test_improve_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/blueprint/improve",
                   json={"instruction": "expand NFRs"})
        assert r.status_code == 202
        body = c.get("/api/workspaces/ws-1/blueprint/improve").json()
        assert body["status"] == "done"
        assert body["result"]["version"] == 2
    finally:
        app.dependency_overrides.clear()


def test_improve_400_on_empty_instruction(monkeypatch):
    c = _setup(monkeypatch)
    try:
        assert c.post("/api/workspaces/ws-1/blueprint/improve",
                      json={"instruction": "  "}).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_improve_409_when_no_brd(monkeypatch):
    c = _setup(monkeypatch, has_brd=False)
    try:
        assert c.post("/api/workspaces/ws-1/blueprint/improve",
                      json={"instruction": "expand NFRs"}).status_code == 409
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_blueprint_improve.py -v`
Expected: FAIL (404 — routes not registered).

- [ ] **Step 3: Implement the endpoints in `blueprint.py`**

Add imports near the top:

```python
from pydantic import BaseModel

from cobol_modernizer.brd.pipeline import improve_brd_graph_sync
```

Add a request model (module level):

```python
class _ImproveBody(BaseModel):
    instruction: str
```

Add the endpoints (after the existing blueprint routes; reuse `_workspace`, `_source_root`, `_precheck`, `jobs`, `_job_view`, the `_NEO4J_ERRORS` tuple already in this file):

```python
@router.post("/workspaces/{wid}/blueprint/improve", status_code=202)
def blueprint_improve(wid: str, body: _ImproveBody,
                      session: Session = Depends(get_session),
                      neo4j=Depends(get_neo4j)) -> dict:
    """Refine the latest BRD per a free-text instruction (graph-grounded) as a
    background job, saving a new version. Validates fast: needs the key, a non-empty
    instruction, and an existing BRD."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Improve needs an LLM.")
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction must be non-empty")
    try:
        if BRDStorage(neo4j).get_latest(ws.repo_slug) is None:
            raise HTTPException(status_code=409,
                                detail="no BRD yet — generate a blueprint first")
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    slug = ws.repo_slug
    repo_dir = _source_root() / slug

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            result = improve_brd_graph_sync(slug, instruction, client=neo,
                                             repo_path=str(repo_dir.resolve()))
            return {"repo_slug": slug, "brd_id": result.brd_id,
                    "version": result.version,
                    "rating": result.rating.value if hasattr(result.rating, "value") else result.rating,
                    "weighted_score": result.weighted_score, "model": result.model,
                    "token_usage": dict(result.token_usage)}
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("blueprint-improve", wid, _job))


@router.get("/workspaces/{wid}/blueprint/improve")
def blueprint_improve_status(wid: str, session: Session = Depends(get_session),
                             neo4j=Depends(get_neo4j)) -> dict:
    _workspace(session, wid)
    return _job_view(jobs.runner.get("blueprint-improve", wid))
```

NOTE: confirm `_job_view` exists in `blueprint.py` (it does — used by the existing blueprint routes). `BRDStorage` is already imported there. `os`, `HTTPException`, `Depends`, `Session`, `get_session`, `get_neo4j` are already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_blueprint_improve.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_controlplane_blueprint_api.py tests/integration/test_controlplane_router_wiring.py -q`
Expected: PASS (existing blueprint routes unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/blueprint.py tests/integration/test_controlplane_blueprint_improve.py
git commit -m "feat(api): blueprint/improve POST+GET (background job; 400 empty / 409 no-BRD)"
```
End body with the Co-Authored-By line.

---

## Phase 5 — Frontend

### Task 6: API client helpers

**Files:**
- Modify: `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts`

> IMPORTANT — unrelated WIP: `web/src/lib/api.ts` and several cockpit files carry the user's uncommitted WIP (a `getNeighbors` helper, `stages.ts`, etc.) that MUST NOT be committed into this feature branch (it would ride into the eventual merge to main). BEFORE starting the frontend phase (Tasks 6–7), stash that WIP and restore it after Task 7:
> ```bash
> git stash push -u -m "WIP — set aside for blueprint-improve frontend" -- \
>   src/cobol_modernizer/controlplane/graph.py src/cobol_modernizer/queries.py \
>   tests/integration/test_controlplane_graph_neo4j.py \
>   "web/src/app/workspaces/[id]/journey/[stage]/page.tsx" \
>   web/src/components/GraphView.tsx web/src/components/cockpit/JourneyRail.test.tsx \
>   web/src/components/cockpit/JourneyRail.tsx web/src/components/cockpit/StageHeader.tsx \
>   web/src/lib/api.ts web/src/lib/stages.ts \
>   web/src/components/cockpit/NextStageButton.tsx web/src/components/cockpit/NextStageButton.test.tsx
> ```
> Then `api.ts` is clean and you can `git add web/src/lib/api.ts` safely. After Task 7's commit, `git stash pop` to restore the WIP (it re-applies cleanly — your additions are in a different region than `getNeighbors`). Follow the existing `json<T>` + `EnrichJob<T>` patterns.

- [ ] **Step 1: Write the failing test**

Append to `web/src/lib/api.test.ts`:

```ts
describe("blueprint improve api", () => {
  it("exposes improve helpers", () => {
    expect(typeof api.startBlueprintImprove).toBe("function");
    expect(typeof api.getBlueprintImproveStatus).toBe("function");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** — add a result type + two methods to `api` (mirror `startBlueprint`/`getBlueprintStatus` + the `EnrichJob<T>` envelope already in the file):

```ts
export interface BlueprintImproveResult { repo_slug: string; brd_id: string; version: number; rating: string; weighted_score: number; model: string; token_usage?: Record<string, number> }
```
```ts
  startBlueprintImprove: (workspaceId: string, instruction: string) =>
    json<EnrichJob<BlueprintImproveResult>>(`/api/workspaces/${workspaceId}/blueprint/improve`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }) }),
  getBlueprintImproveStatus: (workspaceId: string) =>
    json<EnrichJob<BlueprintImproveResult>>(`/api/workspaces/${workspaceId}/blueprint/improve`),
```

- [ ] **Step 4: Run test + typecheck**

Run: `cd web && npx vitest run src/lib/api.test.ts && npx tsc --noEmit`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): blueprint improve api client helpers"
```
End body with the Co-Authored-By line.

### Task 7: BlueprintStudio — instruction box + Improve button

**Files:**
- Modify: `web/src/components/screens/BlueprintStudio.tsx`
- Test: `web/src/components/screens/BlueprintStudio.test.tsx` + `web/src/test/msw/handlers.ts`

- [ ] **Step 1: Add MSW handlers** in `web/src/test/msw/handlers.ts` (match existing style):

```ts
http.post("*/api/workspaces/:id/blueprint/improve", () =>
  HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
http.get("*/api/workspaces/:id/blueprint/improve", () =>
  HttpResponse.json({ status: "done", error: null,
    result: { repo_slug: "demo", brd_id: "b2", version: 2, rating: "high",
              weighted_score: 4.4, model: "claude-sonnet-4-6" } })),
```
(Ensure the existing blueprint status handler returns a generated BRD `result` so the BlueprintStudio shows a BRD — the Improve UI is gated on a BRD existing.)

- [ ] **Step 2: Write the failing test** in `BlueprintStudio.test.tsx` (mirror its existing test):

```tsx
it("improves the BRD: types an instruction, clicks Improve, gets a new version", async () => {
  render(<BlueprintStudio workspaceId="w1" />);
  // generate first so a BRD exists (reuse the existing test's flow to get result shown)
  fireEvent.click(await screen.findByRole("button", { name: /generate blueprint/i }));
  const box = await screen.findByPlaceholderText(/how should we improve/i);
  fireEvent.change(box, { target: { value: "expand NFRs" } });
  fireEvent.click(screen.getByRole("button", { name: /^improve$/i }));
  expect(await screen.findByText(/v2/i)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/screens/BlueprintStudio.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Implement** in `BlueprintStudio.tsx`:
   - Add a second `useJob<BlueprintImproveResult>(() => api.startBlueprintImprove(workspaceId, instruction), () => api.getBlueprintImproveStatus(workspaceId))`.
   - Add `const [instruction, setInstruction] = useState("")`.
   - When the (generate) `result` exists, render a `<textarea placeholder="How should we improve the BRD? (e.g. expand non-functional requirements)">` bound to `instruction`, and an "Improve" button (disabled when `improve.busy || !instruction.trim()`, label "Improving…" while busy).
   - On `improve.result` change, force the iframe to reload the new version: keep a `version` state initialized from the generate `result.version`; set it to `improve.result.version` when the improve job completes; render the iframe `src={`${api.blueprintHtmlUrl(workspaceId)}?v=${version}`}` and show `BRD v{version}` + the improve rating.
   - Read the existing component first; integrate without removing the generate flow.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/screens/BlueprintStudio.test.tsx`
Expected: PASS.

- [ ] **Step 6: Regression + typecheck**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS / clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/screens/BlueprintStudio.tsx web/src/components/screens/BlueprintStudio.test.tsx web/src/test/msw/handlers.ts
git commit -m "feat(web): Blueprint Improve — instruction box + button + iframe refresh"
```
End body with the Co-Authored-By line.

---

## Phase 6 — Final verification

### Task 8: Full regression + final review

- [ ] **Step 1: Backend**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/integration/test_controlplane_blueprint_improve.py tests/integration/test_controlplane_blueprint_api.py -q`
Expected: PASS.

- [ ] **Step 2: Frontend**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS / clean.

- [ ] **Step 3: Final whole-implementation review** — dispatch a reviewer over `git diff <branch-base> HEAD` checking: generate path unchanged/works; improve never overwrites on failure (raises, prior version intact); grounding via the reused judge; endpoint validations (400/409/503); frontend gated on a BRD existing; no unrelated WIP files committed except the noted api.ts.

- [ ] **Step 4: Commit any fixups**, then this feature branch is ready to finish (PR/merge) via superpowers:finishing-a-development-branch.

---

## Notes for the implementer
- **Never overwrite on failure:** `agenerate_brd_improvement` raises on empty output and `improve_brd_graph_sync` only `save()`s a valid improved draft — a failed/timed-out improve must leave the prior latest version intact.
- **Grounding is mandatory:** the reused `ajudge` floors accuracy on hallucinated refs; the improve agent's prompt forbids inventing identifiers.
- **Reuse, don't fork:** the improve agent uses the same `build_graph_server`/`GRAPH_TOOL_NAMES`/`brd_draft_schema` as the draft agent; the pipeline reuses `_draft_to_brd`/`render_html`/`_log_timing`/`BRDStorage`.
- **Seeding:** prefer the structured `reconstruct_draft`; fall back to the stored HTML for legacy BRD nodes.
