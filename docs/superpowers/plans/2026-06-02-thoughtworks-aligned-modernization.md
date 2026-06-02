# Thoughtworks-Aligned Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the COBOL-to-Spring-Boot migration engine with the Thoughtworks/Mechanical Orchard style: graph-grounded understanding, business-backlog decomposition, seam-led incremental planning, DDD plus technical design, and deterministic behavioral verification before code is trusted.

**Architecture:** Keep the existing cockpit stages but make the artifact chain explicit and enforceable: `COBOL graph -> BRD -> logic coverage -> epics/stories -> story DAG -> seams -> migration waves -> DDD -> technical design -> codegen -> equivalence`. Add small, versioned artifacts and gates instead of one large rewrite. The graph remains the deterministic source of truth; LLMs produce bounded artifacts that must cite graph/BRD/story evidence and pass coverage gates.

**Tech Stack:** FastAPI control-plane routers, Neo4j graph store, SQLAlchemy/Alembic persistence, Pydantic artifact schemas, pytest, existing `SdkAgentRunner`, existing BRD/domain/codegen modules, generated Spring Boot/Maven projects.

---

## Gap Summary

The current app has the right skeleton but is not yet a Thoughtworks-style modernization engine.

1. **BRD has no hard logic coverage proof.** The Blueprint stage produces graph-grounded BRD sections, but no deterministic matrix proves every discovered program, paragraph, data item, file access, SQL/CICS operation, and business rule was either represented or intentionally excluded.

2. **No BRD-to-epic/story decomposition.** Existing `planner.Story` objects are seam-centric (`Migrate PROGRAM`) rather than business-centric. There is no `Epic`, no acceptance criteria, and no requirement/story traceability.

3. **Plan is seam-derived, not business-backlog-derived.** Current migration planning builds a DAG from read/write resource dependencies. That is useful, but it does not combine BRD user stories, acceptance criteria, seam risk, and data-flow priority.

4. **DDD does not consume stories.** Domain design uses latest BRD text and graph coupling summary. It does not ingest the story DAG or acceptance criteria, so it cannot prove that all BRD/user-story behavior survived into aggregates, invariants, APIs, and repositories.

5. **Technical design is not derived from DDD.** The current `/design` endpoint is a legacy deterministic writer-slice design. It is not a technical/microservice design that transforms DDD contexts into module/service topology, APIs, persistence, integration contracts, event contracts, ACLs, deployment units, and test strategy.

6. **Codegen lacks story and technical-design inputs.** Build now uses BRD + DDD + prefetched source, which is an improvement, but it does not select a migration wave/story and generate tests from acceptance criteria plus captured legacy behavior.

7. **Behavioral verification is not first-class enough.** Thoughtworks/Mechanical Orchard emphasize treating the running legacy system and data flows as the specification. The app has equivalence components, but the migration chain does not require golden inputs/outputs per story before generated code is considered acceptable.

8. **Cost/performance controls are stage-local.** BRD and codegen have some size-aware behavior, but the whole workflow lacks a budgeted artifact strategy that prevents large repos from repeatedly sending full BRDs/designs/source packs to LLMs.

## Alignment Principles

1. **Do not build a direct converter.** Avoid a COBOL-shaped Java output. Generate Spring Boot from business stories, DDD, technical design, and acceptance tests.

2. **Make traceability the core data model.** Every artifact should point backward and forward:
   `graph_ref -> brd_requirement_id -> epic_id -> story_id -> domain_ref -> technical_ref -> generated_file -> test/equivalence_result`.

3. **Use seams to plan increments, not to define product scope.** Business stories come from BRD requirements. Seams constrain delivery order and cutover risk.

4. **Use LLMs only on bounded, pre-materialized context.** The graph is queried deterministically before prompts. Graph tools are fallback, not the normal path.

5. **Verification precedes trust.** Generated code is not accepted until story acceptance tests and equivalence/golden-master checks pass or a human explicitly records a risk decision.

## References

- Thoughtworks Technology Podcast, “Accelerating mainframe modernization using generative AI”, May 15, 2025: https://www.thoughtworks.com/en-gb/insights/podcasts/technology-podcasts/accelerating-mainframe-modernization-generative-ai
- Thoughtworks, “Claude Code and COBOL modernization: What’s the reality?”: https://www.thoughtworks.com/en-gb/insights/articles/claude-code-cobol-modernization-reality
- AWS Blu Insights/Blu Age lifecycle reference: https://aws.amazon.com/blogs/mt/aws-mainframe-modernization-refactor-legacy-code-base-to-java-using-aws-blu-insights/
- IBM watsonx Code Assistant for Z lifecycle reference: https://www.ibm.com/products/watsonx-code-assistant-z

---

## File Structure

Create focused modules instead of expanding the existing large routers.

- Create `src/cobol_modernizer/traceability/schema.py`
  - Pydantic models for trace links and coverage reports.
- Create `src/cobol_modernizer/traceability/coverage.py`
  - Deterministic graph-vs-artifact coverage calculations.
- Create `src/cobol_modernizer/backlog/schema.py`
  - `Epic`, `UserStory`, `AcceptanceCriterion`, and `StoryDAG` models.
- Create `src/cobol_modernizer/backlog/generator.py`
  - BRD-to-backlog LLM prompt and parser, bounded to persisted BRD requirements.
- Create `src/cobol_modernizer/backlog/dependency.py`
  - Story dependency derivation from acceptance criteria, data resources, and seams.
- Create `src/cobol_modernizer/controlplane/backlog.py`
  - FastAPI endpoints for backlog generation/status/html or JSON retrieval.
- Modify `src/cobol_modernizer/controlplane/__init__.py`
  - Include the backlog router.
- Modify `src/cobol_modernizer/controlplane/stages.py`
  - Keep the existing UI journey stage names stable; expose backlog through `/api/workspaces/{wid}/backlog` and surface backlog status inside the existing `plan` stage.
- Modify `src/cobol_modernizer/controlplane/domain.py`
  - Feed structured BRD requirements and backlog stories into domain design.
- Create `src/cobol_modernizer/technical_design/schema.py`
  - Target service/module/API/persistence/event/ACL/deployment design models.
- Create `src/cobol_modernizer/technical_design/generator.py`
  - DDD + story + seam-wave to technical design prompt and parser.
- Create `src/cobol_modernizer/controlplane/technical_design.py`
  - Endpoints for technical design generation/status/retrieval.
- Modify `src/cobol_modernizer/controlplane/build.py`
  - Use selected story/wave + technical design + acceptance criteria as codegen brief inputs.
- Modify `src/cobol_modernizer/codegen/generator.py`
  - Generate tests from story acceptance criteria and golden-master/equivalence expectations.
- Create tests under:
  - `tests/unit/test_traceability_coverage.py`
  - `tests/unit/test_backlog_schema.py`
  - `tests/unit/test_backlog_dependency.py`
  - `tests/unit/test_domain_uses_backlog.py`
  - `tests/unit/test_technical_design_schema.py`
  - `tests/unit/test_build_uses_story_and_technical_design.py`
  - Integration tests under `tests/integration/test_controlplane_backlog_api.py` and `tests/integration/test_controlplane_technical_design_api.py`.

---

## Task 1: Traceability and BRD Logic Coverage Gate

**Files:**
- Create: `src/cobol_modernizer/traceability/schema.py`
- Create: `src/cobol_modernizer/traceability/coverage.py`
- Test: `tests/unit/test_traceability_coverage.py`

- [ ] **Step 1: Write the failing coverage tests**

```python
from cobol_modernizer.traceability.coverage import brd_logic_coverage


class FakeNeo4j:
    def run(self, query, **params):
        if "RETURN n.qualified_name AS ref" in query:
            return [
                {"ref": "CBPOST1M", "kind": "Program"},
                {"ref": "CBPOST1M.2100-POST-TRAN", "kind": "Paragraph"},
                {"ref": "CBPOST1M.DT-AMOUNT", "kind": "DataItem"},
            ]
        return []


def test_brd_logic_coverage_reports_uncovered_graph_refs():
    brd_sections = [
        {
            "title": "Functional Requirements",
            "requirements": [{"id": "FR-1", "text": "Post a transaction amount."}],
        }
    ]
    evidence_map = {"FR-1": ["CBPOST1M", "CBPOST1M.2100-POST-TRAN"]}

    report = brd_logic_coverage(FakeNeo4j(), "carddemo-mini", brd_sections, evidence_map)

    assert report.repo_slug == "carddemo-mini"
    assert report.covered_refs == ["CBPOST1M", "CBPOST1M.2100-POST-TRAN"]
    assert report.uncovered_refs == ["CBPOST1M.DT-AMOUNT"]
    assert report.coverage_ratio == 2 / 3


def test_brd_logic_coverage_accepts_intentional_exclusions():
    report = brd_logic_coverage(
        FakeNeo4j(),
        "carddemo-mini",
        brd_sections=[],
        evidence_map={"FR-1": ["CBPOST1M"]},
        exclusions={"CBPOST1M.2100-POST-TRAN": "technical flow covered by program"},
    )

    assert "CBPOST1M.2100-POST-TRAN" not in report.uncovered_refs
    assert report.exclusions["CBPOST1M.2100-POST-TRAN"] == "technical flow covered by program"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_traceability_coverage.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'cobol_modernizer.traceability'`.

- [ ] **Step 3: Implement traceability schema**

```python
# src/cobol_modernizer/traceability/schema.py
from __future__ import annotations

from pydantic import BaseModel, Field


class TraceLink(BaseModel):
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    reason: str = ""


class LogicCoverageReport(BaseModel):
    repo_slug: str
    total_refs: int
    covered_refs: list[str] = Field(default_factory=list)
    uncovered_refs: list[str] = Field(default_factory=list)
    exclusions: dict[str, str] = Field(default_factory=dict)
    coverage_ratio: float = 0.0
```

- [ ] **Step 4: Implement coverage calculation**

```python
# src/cobol_modernizer/traceability/coverage.py
from __future__ import annotations

from collections.abc import Mapping, Sequence

from cobol_modernizer.traceability.schema import LogicCoverageReport


_GRAPH_REFS_Q = """
MATCH (n:CodeEntity {repo:$repo})
WHERE n.kind IN ['Program', 'Paragraph', 'DataItem', 'Copybook', 'External']
RETURN n.qualified_name AS ref, n.kind AS kind
ORDER BY n.qualified_name
"""


def _all_graph_refs(neo4j, repo_slug: str) -> list[str]:
    rows = neo4j.run(_GRAPH_REFS_Q, repo=repo_slug)
    return [r["ref"] for r in rows if r.get("ref")]


def _covered_refs(evidence_map: Mapping[str, Sequence[str]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for values in evidence_map.values():
        for ref in values:
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def brd_logic_coverage(
    neo4j,
    repo_slug: str,
    brd_sections: list[dict],
    evidence_map: Mapping[str, Sequence[str]],
    exclusions: Mapping[str, str] | None = None,
) -> LogicCoverageReport:
    all_refs = _all_graph_refs(neo4j, repo_slug)
    excluded = dict(exclusions or {})
    covered = [r for r in _covered_refs(evidence_map) if r in all_refs]
    covered_set = set(covered)
    uncovered = [r for r in all_refs if r not in covered_set and r not in excluded]
    effective_total = max(0, len(all_refs) - len([r for r in excluded if r in all_refs]))
    ratio = (len(covered) / effective_total) if effective_total else 1.0
    return LogicCoverageReport(
        repo_slug=repo_slug,
        total_refs=effective_total,
        covered_refs=covered,
        uncovered_refs=uncovered,
        exclusions=excluded,
        coverage_ratio=ratio,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_traceability_coverage.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/traceability tests/unit/test_traceability_coverage.py
git commit -m "feat: add BRD logic coverage report"
```

---

## Task 2: BRD Backlog Schema for Epics, Stories, Acceptance Criteria

**Files:**
- Create: `src/cobol_modernizer/backlog/schema.py`
- Test: `tests/unit/test_backlog_schema.py`

- [ ] **Step 1: Write the failing schema tests**

```python
from cobol_modernizer.backlog.schema import AcceptanceCriterion, Epic, UserStory


def test_user_story_carries_brd_and_graph_lineage():
    story = UserStory(
        id="US-1",
        epic_id="EPIC-1",
        title="Post approved transaction",
        actor="batch posting operator",
        narrative="As a posting process I want approved transactions applied to accounts.",
        brd_requirement_ids=["FR-1"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC-1",
                statement="Given a valid transaction, the account balance is updated.",
                evidence_refs=["CBPOST1M.2100-POST-TRAN"],
            )
        ],
        evidence_refs=["CBPOST1M", "CBPOST1M.2100-POST-TRAN"],
    )

    assert story.brd_requirement_ids == ["FR-1"]
    assert story.acceptance_criteria[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]


def test_epic_groups_business_stories():
    epic = Epic(
        id="EPIC-1",
        title="Transaction Posting",
        outcome="Accurately apply daily transactions to account records.",
        brd_requirement_ids=["FR-1", "FR-2"],
        story_ids=["US-1", "US-2"],
        evidence_refs=["CBPOST1M"],
    )

    assert epic.story_ids == ["US-1", "US-2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_schema.py -q`

Expected: FAIL with missing `cobol_modernizer.backlog`.

- [ ] **Step 3: Implement backlog schema**

```python
# src/cobol_modernizer/backlog/schema.py
from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    id: str
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)
    golden_fixture_ids: list[str] = Field(default_factory=list)


class Epic(BaseModel):
    id: str
    title: str
    outcome: str
    brd_requirement_ids: list[str] = Field(default_factory=list)
    story_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class UserStory(BaseModel):
    id: str
    epic_id: str
    title: str
    actor: str
    narrative: str
    brd_requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    seam_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    context: str | None = None
    topology: str | None = None


class Backlog(BaseModel):
    repo_slug: str
    version: int = 0
    epics: list[Epic] = Field(default_factory=list)
    stories: list[UserStory] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
```

- [ ] **Step 4: Add package init**

```python
# src/cobol_modernizer/backlog/__init__.py
"""Business backlog artifacts derived from graph-grounded BRDs."""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_schema.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/backlog tests/unit/test_backlog_schema.py
git commit -m "feat: add BRD backlog schema"
```

---

## Task 3: BRD-to-Backlog Generator and Grounding Parser

**Files:**
- Create: `src/cobol_modernizer/backlog/generator.py`
- Test: `tests/unit/test_backlog_generator.py`

- [ ] **Step 1: Write the failing generator parser test**

```python
import pytest

from cobol_modernizer.backlog.generator import parse_backlog_payload


def test_parse_backlog_payload_drops_ungrounded_refs():
    raw = {
        "epics": [
            {
                "id": "EPIC-1",
                "title": "Posting",
                "outcome": "Apply transactions",
                "brd_requirement_ids": ["FR-1"],
                "story_ids": ["US-1"],
                "evidence_refs": ["CBPOST1M", "GHOST"],
            }
        ],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "Post valid transaction",
                "actor": "posting batch",
                "narrative": "As a posting batch I apply valid transactions.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "statement": "Valid amount updates account balance.",
                        "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
                    }
                ],
                "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
            }
        ],
    }

    backlog = parse_backlog_payload(
        raw,
        repo_slug="carddemo-mini",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1"},
    )

    assert backlog.epics[0].evidence_refs == ["CBPOST1M"]
    assert backlog.stories[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]
    assert backlog.stories[0].acceptance_criteria[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]


def test_parse_backlog_rejects_story_without_acceptance_criteria():
    raw = {
        "epics": [],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "No criteria",
                "actor": "user",
                "narrative": "As a user I need behavior.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [],
                "evidence_refs": ["CBPOST1M"],
            }
        ],
    }

    with pytest.raises(ValueError, match="acceptance criteria"):
        parse_backlog_payload(
            raw,
            repo_slug="carddemo-mini",
            known_refs={"CBPOST1M"},
            known_requirement_ids={"FR-1"},
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_generator.py -q`

Expected: FAIL with missing `parse_backlog_payload`.

- [ ] **Step 3: Implement generator parser and prompt constants**

```python
# src/cobol_modernizer/backlog/generator.py
from __future__ import annotations

from typing import Any

from cobol_modernizer.backlog.schema import (
    AcceptanceCriterion,
    Backlog,
    Epic,
    UserStory,
)


BACKLOG_SYSTEM = (
    "You convert a graph-grounded BRD into an implementation backlog. "
    "Create business epics and user stories, not technical migration tasks. "
    "Every story must cite BRD requirement ids and graph evidence refs. "
    "Every story must include acceptance criteria that can become tests. "
    "Do not invent requirement ids or graph refs."
)


def _ground(values: list[str] | None, allowed: set[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if value in allowed and value not in out:
            out.append(value)
    return out


def parse_backlog_payload(
    raw: dict[str, Any],
    *,
    repo_slug: str,
    known_refs: set[str],
    known_requirement_ids: set[str],
) -> Backlog:
    epics: list[Epic] = []
    for item in raw.get("epics", []):
        if not isinstance(item, dict):
            continue
        epics.append(Epic(
            id=str(item.get("id", "")),
            title=str(item.get("title", "")),
            outcome=str(item.get("outcome", "")),
            brd_requirement_ids=_ground(item.get("brd_requirement_ids"), known_requirement_ids),
            story_ids=[str(s) for s in item.get("story_ids", []) if s],
            evidence_refs=_ground(item.get("evidence_refs"), known_refs),
        ))

    stories: list[UserStory] = []
    for item in raw.get("stories", []):
        if not isinstance(item, dict):
            continue
        criteria = [
            AcceptanceCriterion(
                id=str(c.get("id", "")),
                statement=str(c.get("statement", "")),
                evidence_refs=_ground(c.get("evidence_refs"), known_refs),
                golden_fixture_ids=[str(g) for g in c.get("golden_fixture_ids", []) if g],
            )
            for c in item.get("acceptance_criteria", [])
            if isinstance(c, dict)
        ]
        if not criteria:
            raise ValueError(f"story {item.get('id', '?')} has no acceptance criteria")
        stories.append(UserStory(
            id=str(item.get("id", "")),
            epic_id=str(item.get("epic_id", "")),
            title=str(item.get("title", "")),
            actor=str(item.get("actor", "")),
            narrative=str(item.get("narrative", "")),
            brd_requirement_ids=_ground(item.get("brd_requirement_ids"), known_requirement_ids),
            acceptance_criteria=criteria,
            depends_on=[str(s) for s in item.get("depends_on", []) if s],
            seam_refs=_ground(item.get("seam_refs"), known_refs),
            evidence_refs=_ground(item.get("evidence_refs"), known_refs),
        ))

    evidence_map = {s.id: s.evidence_refs for s in stories}
    return Backlog(repo_slug=repo_slug, epics=epics, stories=stories, evidence_map=evidence_map)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_generator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/backlog/generator.py tests/unit/test_backlog_generator.py
git commit -m "feat: parse graph-grounded BRD backlog"
```

---

## Task 4: Story Dependency DAG Uses BRD Stories Plus Seam/Data Dependencies

**Files:**
- Create: `src/cobol_modernizer/backlog/dependency.py`
- Test: `tests/unit/test_backlog_dependency.py`

- [ ] **Step 1: Write the failing story DAG tests**

```python
from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.backlog.schema import AcceptanceCriterion, UserStory


def _story(story_id, refs):
    return UserStory(
        id=story_id,
        epic_id="EPIC-1",
        title=story_id,
        actor="operator",
        narrative=f"As an operator I need {story_id}.",
        brd_requirement_ids=["FR-1"],
        acceptance_criteria=[AcceptanceCriterion(id=f"AC-{story_id}", statement="works")],
        evidence_refs=refs,
    )


def test_writer_story_depends_on_reader_story_for_same_resource():
    stories = [_story("US-READ", ["CBACT01M"]), _story("US-WRITE", ["CBPOST1M"])]
    seam_candidates = [
        {"program": "CBACT01M", "reads": ["ACCTFILE"], "writes": [], "score": {"weighted": 0.9}},
        {"program": "CBPOST1M", "reads": ["ACCTFILE"], "writes": ["ACCTFILE"], "score": {"weighted": 0.4}},
    ]

    dag = derive_story_dependencies(stories, seam_candidates, repo_slug="carddemo-mini")

    by_id = {s.id: s for s in dag.stories}
    assert by_id["US-WRITE"].depends_on == ["US-READ"]
    assert dag.repo_slug == "carddemo-mini"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_backlog_dependency.py -q`

Expected: FAIL with missing `derive_story_dependencies`.

- [ ] **Step 3: Implement dependency derivation**

```python
# src/cobol_modernizer/backlog/dependency.py
from __future__ import annotations

from pydantic import BaseModel, Field

from cobol_modernizer.backlog.schema import UserStory


class BacklogDAG(BaseModel):
    repo_slug: str
    stories: list[UserStory] = Field(default_factory=list)


def _program_for_story(story: UserStory, programs: set[str]) -> str | None:
    for ref in story.evidence_refs:
        program = ref.split(".")[0]
        if program in programs:
            return program
    return None


def derive_story_dependencies(
    stories: list[UserStory],
    seam_candidates: list[dict],
    *,
    repo_slug: str,
) -> BacklogDAG:
    by_program = {c["program"]: c for c in seam_candidates}
    programs = set(by_program)
    story_program = {s.id: _program_for_story(s, programs) for s in stories}
    story_for_program = {p: sid for sid, p in story_program.items() if p}

    for story in stories:
        program = story_program.get(story.id)
        if not program:
            continue
        cand = by_program[program]
        deps: set[str] = set(story.depends_on)
        for written in cand.get("writes", []):
            for other in seam_candidates:
                other_program = other["program"]
                if other_program == program:
                    continue
                if written in other.get("reads", []):
                    dep_story = story_for_program.get(other_program)
                    if dep_story:
                        deps.add(dep_story)
        story.depends_on = sorted(deps)
    return BacklogDAG(repo_slug=repo_slug, stories=stories)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_backlog_dependency.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/backlog/dependency.py tests/unit/test_backlog_dependency.py
git commit -m "feat: derive backlog story dependencies from seams"
```

---

## Task 5: Backlog Control-Plane API

**Files:**
- Create: `src/cobol_modernizer/controlplane/backlog.py`
- Modify: `src/cobol_modernizer/controlplane/__init__.py`
- Test: `tests/integration/test_controlplane_backlog_api.py`

- [ ] **Step 1: Write the failing API test**

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_BRD" in query:
            return [{"b": {"version": 1, "sections": "[]", "evidence_map": "{}"}}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        return []


def test_backlog_status_idle_before_generation():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="mini", repo_slug="carddemo-mini", created_by="tester"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    try:
        client = TestClient(app)
        response = client.get("/api/workspaces/ws-1/backlog")
        assert response.status_code == 200
        assert response.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_backlog_api.py -q`

Expected: FAIL with `404 Not Found`.

- [ ] **Step 3: Implement minimal backlog router**

```python
# src/cobol_modernizer/controlplane/backlog.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Workspace


router = APIRouter(prefix="/api", tags=["controlplane-backlog"])


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


@router.get("/workspaces/{wid}/backlog")
def backlog_status(wid: str, session: Session = Depends(get_session), neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    return {"status": "idle", "result": None, "error": None, "repo_slug": ws.repo_slug}
```

- [ ] **Step 4: Wire router**

```python
# src/cobol_modernizer/controlplane/__init__.py
from cobol_modernizer.controlplane.backlog import router as _backlog_router

controlplane_router.include_router(_backlog_router)
```

Place the import next to the other router imports and include it after the blueprint router.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_controlplane_backlog_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/backlog.py src/cobol_modernizer/controlplane/__init__.py tests/integration/test_controlplane_backlog_api.py
git commit -m "feat: expose backlog control-plane endpoint"
```

---

## Task 6: Feed Backlog Stories into Domain Design

**Files:**
- Modify: `src/cobol_modernizer/controlplane/domain.py`
- Modify: `src/cobol_modernizer/domain/decompose.py`
- Modify: `src/cobol_modernizer/domain/tactical.py`
- Test: `tests/unit/test_domain_uses_backlog.py`

- [ ] **Step 1: Write the failing domain prompt test**

```python
from cobol_modernizer.domain.decompose import build_decomposition_prompt


def test_decomposition_prompt_includes_backlog_stories():
    prompt = build_decomposition_prompt(
        brd_text="FR-1: Post valid transactions",
        graph_summary={"programs": ["CBPOST1M"]},
        backlog_json='{"stories":[{"id":"US-1","title":"Post valid transaction"}]}',
    )

    assert "FR-1: Post valid transactions" in prompt
    assert "US-1" in prompt
    assert "Post valid transaction" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_domain_uses_backlog.py -q`

Expected: FAIL with missing `build_decomposition_prompt`.

- [ ] **Step 3: Extract decomposition prompt builder**

```python
# src/cobol_modernizer/domain/decompose.py
def build_decomposition_prompt(*, brd_text: str, graph_summary: dict, backlog_json: str = "") -> str:
    prompt = (
        "## BRD\n"
        + brd_text
        + "\n\n## Graph coupling summary\n```json\n"
        + json.dumps(graph_summary)
        + "\n```\n"
    )
    if backlog_json.strip():
        prompt += "\n## Business backlog\n```json\n" + backlog_json + "\n```\n"
    prompt += "Decompose into business-capability bounded contexts. Every writer program must be assigned exactly once."
    return prompt
```

Then replace the current inline `base_prompt = ...` expression in `decompose()` with:

```python
base_prompt = build_decomposition_prompt(
    brd_text=brd_text,
    graph_summary=summary,
    backlog_json="",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_domain_uses_backlog.py -q`

Expected: PASS.

- [ ] **Step 5: Extend `decompose()` signature to accept backlog JSON**

```python
async def decompose(client: Any, repo: str, *, brd_text: str, runner: Any, model: str,
                    timeout_s: float, signals_fn: SignalsFn = raw_signals_for_program,
                    max_repairs: int = 2, backlog_json: str = "") -> DecompositionMap:
```

Use:

```python
base_prompt = build_decomposition_prompt(
    brd_text=brd_text,
    graph_summary=summary,
    backlog_json=backlog_json,
)
```

- [ ] **Step 6: Thread backlog JSON through `run_domain_design()`**

```python
def run_domain_design(client: Any, repo_slug: str, *, brd_text: str, runner: Any,
                      model: str, timeout_s: float, signals_fn=raw_signals_for_program,
                      version: int = 0, backlog_json: str = "") -> DomainDesign:
```

Inside `_go()`:

```python
dm = await decompose(
    client,
    repo_slug,
    brd_text=brd_text,
    runner=runner,
    model=model,
    timeout_s=timeout_s,
    signals_fn=signals_fn,
    backlog_json=backlog_json,
)
```

- [ ] **Step 7: Commit**

```bash
git add src/cobol_modernizer/controlplane/domain.py src/cobol_modernizer/domain/decompose.py src/cobol_modernizer/domain/tactical.py tests/unit/test_domain_uses_backlog.py
git commit -m "feat: feed backlog stories into domain design"
```

---

## Task 7: Technical Design Artifact Derived from DDD, Stories, and Seams

**Files:**
- Create: `src/cobol_modernizer/technical_design/schema.py`
- Create: `src/cobol_modernizer/technical_design/generator.py`
- Test: `tests/unit/test_technical_design_schema.py`

- [ ] **Step 1: Write the failing technical design schema test**

```python
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)


def test_technical_design_links_service_to_context_and_stories():
    design = TechnicalDesign(
        repo_slug="carddemo-mini",
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="module",
                story_ids=["US-1"],
                api_contracts=[ApiContract(name="postTransaction", method="POST", path="/accounts/{id}/transactions")],
                persistence=[PersistenceDesign(resource="ACCTFILE", access_pattern="legacy-mimic")],
                evidence_refs=["CBPOST1M"],
            )
        ],
    )

    assert design.services[0].story_ids == ["US-1"]
    assert design.services[0].persistence[0].resource == "ACCTFILE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_technical_design_schema.py -q`

Expected: FAIL with missing `technical_design`.

- [ ] **Step 3: Implement technical design schema**

```python
# src/cobol_modernizer/technical_design/schema.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ApiContract(BaseModel):
    name: str
    method: str
    path: str
    request_model: str = ""
    response_model: str = ""


class PersistenceDesign(BaseModel):
    resource: str
    access_pattern: Literal["legacy-mimic", "repository", "event-sourced", "read-replica"]
    owner_service: str = ""


class IntegrationContract(BaseModel):
    name: str
    style: Literal["sync", "async", "batch"]
    target: str
    payload: str = ""


class TechnicalService(BaseModel):
    name: str
    bounded_context: str
    deployment: Literal["module", "microservice"]
    story_ids: list[str] = Field(default_factory=list)
    api_contracts: list[ApiContract] = Field(default_factory=list)
    persistence: list[PersistenceDesign] = Field(default_factory=list)
    integrations: list[IntegrationContract] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class TechnicalDesign(BaseModel):
    repo_slug: str
    version: int = 0
    services: list[TechnicalService] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
```

- [ ] **Step 4: Add package init**

```python
# src/cobol_modernizer/technical_design/__init__.py
"""Technical target architecture derived from DDD, stories, seams, and BRD evidence."""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_technical_design_schema.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/technical_design tests/unit/test_technical_design_schema.py
git commit -m "feat: add technical design artifact schema"
```

---

## Task 8: Build Brief Uses Story, DDD, Technical Design, and Source Pack

**Files:**
- Modify: `src/cobol_modernizer/controlplane/build.py`
- Modify: `src/cobol_modernizer/codegen/generator.py`
- Test: `tests/unit/test_build_uses_story_and_technical_design.py`

- [ ] **Step 1: Write the failing build brief test**

```python
import json

from cobol_modernizer.controlplane import build as bd


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_DOMAIN_DESIGN" in query:
            return [{"d": {"version": 1, "rating": "high", "contexts_json": "[]", "designs_json": "[]"}}]
        if "HAS_TECHNICAL_DESIGN" in query:
            return [{"t": {"version": 1, "services_json": '[{"name":"posting-service","story_ids":["US-1"]}]'}}]
        if "HAS_BACKLOG" in query:
            return [{"b": {"version": 1, "stories_json": '[{"id":"US-1","title":"Post valid transaction"}]'}}]
        return []


def test_codegen_brief_includes_backlog_and_technical_design():
    brd_node = {
        "version": 1,
        "rating": "high",
        "sections": '[{"title":"Functional Requirements","requirements":[{"id":"FR-1","text":"Post transaction"}]}]',
    }

    brief = json.loads(bd._codegen_brief(FakeNeo4j(), "carddemo-mini", brd_node))

    assert "domain_design" in brief
    assert brief["backlog"]["stories"][0]["id"] == "US-1"
    assert brief["technical_design"]["services"][0]["name"] == "posting-service"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_build_uses_story_and_technical_design.py -q`

Expected: FAIL because `_codegen_brief` does not include `backlog` or `technical_design`.

- [ ] **Step 3: Add brief readers**

Add to `src/cobol_modernizer/controlplane/build.py`:

```python
def _backlog_brief(neo4j, slug: str) -> dict | None:
    rows = neo4j.run(
        """
        MATCH (r:Repository {slug: $repo_slug})-[:HAS_BACKLOG]->(b:Backlog)
        RETURN b ORDER BY b.version DESC LIMIT 1
        """,
        repo_slug=slug,
    )
    if not rows:
        return None
    node = rows[0]["b"]
    return {
        "version": node.get("version"),
        "epics": json.loads(node.get("epics_json") or "[]"),
        "stories": json.loads(node.get("stories_json") or "[]"),
    }


def _technical_design_brief(neo4j, slug: str) -> dict | None:
    rows = neo4j.run(
        """
        MATCH (r:Repository {slug: $repo_slug})-[:HAS_TECHNICAL_DESIGN]->(t:TechnicalDesign)
        RETURN t ORDER BY t.version DESC LIMIT 1
        """,
        repo_slug=slug,
    )
    if not rows:
        return None
    node = rows[0]["t"]
    return {
        "version": node.get("version"),
        "services": json.loads(node.get("services_json") or "[]"),
    }
```

- [ ] **Step 4: Include new artifacts in `_codegen_brief()`**

```python
backlog = _backlog_brief(neo4j, slug)
if backlog:
    brief["backlog"] = backlog
technical = _technical_design_brief(neo4j, slug)
if technical:
    brief["technical_design"] = technical
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_build_uses_story_and_technical_design.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/build.py tests/unit/test_build_uses_story_and_technical_design.py
git commit -m "feat: include backlog and technical design in codegen brief"
```

---

## Task 9: Codegen Generates Tests from Acceptance Criteria

**Files:**
- Modify: `src/cobol_modernizer/codegen/generator.py`
- Test: `tests/unit/test_codegen_generator.py`

- [ ] **Step 1: Add failing prompt test**

```python
async def test_generator_directs_agent_to_turn_acceptance_criteria_into_tests():
    runner = FakeRunner(PAYLOAD)
    await generate_slice(
        runner=runner,
        server=None,
        model="m",
        brd_json='{"backlog":{"stories":[{"id":"US-1","acceptance_criteria":[{"id":"AC-1","statement":"valid transaction updates balance"}]}]}}',
        golden_summary="",
        allowed_tools=[],
    )
    sent = (runner.calls[0]["system"] + runner.calls[0]["prompt"]).lower()
    assert "acceptance criteria" in sent
    assert "ac-1" in sent
    assert "valid transaction updates balance" in sent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_codegen_generator.py::test_generator_directs_agent_to_turn_acceptance_criteria_into_tests -q`

Expected: FAIL because the system prompt does not mention acceptance criteria.

- [ ] **Step 3: Update codegen system prompt**

Add this sentence to `CODEGEN_SYSTEM` after the BRD/design test instruction:

```python
"If backlog stories are present, every acceptance criterion MUST become at least one JUnit assertion and the generated test evidence MUST cite the story id and acceptance criterion id. "
```

Add this sentence to the final user prompt in `generate_slice()`:

```python
"If the brief includes backlog stories, convert their acceptance criteria into tests before writing production code. "
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_codegen_generator.py::test_generator_directs_agent_to_turn_acceptance_criteria_into_tests -q`

Expected: PASS.

- [ ] **Step 5: Run full focused codegen tests**

Run: `uv run pytest tests/unit/test_codegen_generator.py tests/unit/test_build_uses_story_and_technical_design.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/codegen/generator.py tests/unit/test_codegen_generator.py
git commit -m "feat: generate codegen tests from story acceptance criteria"
```

---

## Task 10: Behavioral Verification Becomes a Required Story Gate

**Files:**
- Modify: `src/cobol_modernizer/slice/gates.py`
- Modify: `src/cobol_modernizer/equivalence/report.py`
- Test: `tests/unit/test_story_behavior_gate.py`

- [ ] **Step 1: Write the failing behavior gate test**

```python
from cobol_modernizer.slice.gates import story_behavior_gate


def test_story_behavior_gate_requires_acceptance_and_equivalence():
    result = story_behavior_gate(
        story_id="US-1",
        acceptance_criteria_ids=["AC-1"],
        generated_test_refs=["AC-1"],
        equivalence_verdict="passed",
    )

    assert result["passed"] is True


def test_story_behavior_gate_fails_without_equivalence():
    result = story_behavior_gate(
        story_id="US-1",
        acceptance_criteria_ids=["AC-1"],
        generated_test_refs=["AC-1"],
        equivalence_verdict="not_run",
    )

    assert result["passed"] is False
    assert "equivalence" in result["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_story_behavior_gate.py -q`

Expected: FAIL with missing `story_behavior_gate`.

- [ ] **Step 3: Implement story behavior gate**

```python
# src/cobol_modernizer/slice/gates.py
def story_behavior_gate(
    *,
    story_id: str,
    acceptance_criteria_ids: list[str],
    generated_test_refs: list[str],
    equivalence_verdict: str,
) -> dict:
    missing = [ac for ac in acceptance_criteria_ids if ac not in generated_test_refs]
    if missing:
        return {
            "story_id": story_id,
            "passed": False,
            "reason": "missing generated tests for acceptance criteria: " + ", ".join(missing),
        }
    if equivalence_verdict != "passed":
        return {
            "story_id": story_id,
            "passed": False,
            "reason": f"equivalence verdict is {equivalence_verdict}",
        }
    return {"story_id": story_id, "passed": True, "reason": "acceptance and equivalence passed"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_story_behavior_gate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/slice/gates.py tests/unit/test_story_behavior_gate.py
git commit -m "feat: require story behavior verification"
```

---

## Execution Order

1. Task 1: Traceability and BRD logic coverage.
2. Task 2: Backlog schema.
3. Task 3: Backlog generator/parser.
4. Task 4: Backlog story dependencies.
5. Task 5: Backlog API.
6. Task 6: Domain design consumes backlog.
7. Task 7: Technical design artifact.
8. Task 8: Build brief consumes backlog and technical design.
9. Task 9: Codegen tests from acceptance criteria.
10. Task 10: Story behavior gate.

This order gives a working, testable chain after each commit. It also improves performance because downstream LLM calls consume bounded structured artifacts instead of repeatedly exploring the graph.

## Validation Commands

Run after each task:

```bash
uv run pytest tests/unit/test_traceability_coverage.py tests/unit/test_backlog_schema.py tests/unit/test_backlog_generator.py tests/unit/test_backlog_dependency.py -q
```

Run after Task 6:

```bash
uv run pytest tests/unit/test_domain_uses_backlog.py tests/unit/test_domain_run.py tests/unit/test_domain_tactical.py -q
```

Run after Task 9:

```bash
uv run pytest tests/unit/test_codegen_generator.py tests/unit/test_build_uses_story_and_technical_design.py tests/unit/test_build_slice_pack.py tests/unit/test_build_run_plan.py -q
```

Run after Task 10:

```bash
uv run pytest tests/unit/test_story_behavior_gate.py tests/integration/test_controlplane_build_api.py -q
```

## Self-Review

Spec coverage:
- BRD coverage gap is covered by Task 1.
- Epics/stories gap is covered by Tasks 2-5.
- Story dependency planning gap is covered by Task 4.
- DDD story input gap is covered by Task 6.
- Technical design gap is covered by Task 7.
- Codegen input gap is covered by Tasks 8-9.
- Behavioral verification gap is covered by Task 10.

Placeholder scan:
- This plan intentionally contains no forbidden placeholder markers and no open-ended “add tests” steps.

Type consistency:
- `Epic`, `UserStory`, `AcceptanceCriterion`, `Backlog`, `TechnicalDesign`, and `TechnicalService` are defined before downstream tasks reference them.
- `repo_slug`, `evidence_refs`, `brd_requirement_ids`, and `acceptance_criteria` names are stable across schema, parser, prompt, and build-brief tasks.
