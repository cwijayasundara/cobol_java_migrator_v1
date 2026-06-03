"""Story-build stage — the HTTP surface for the story-sliced codegen engine.

This wires Tasks 1-6 behind FastAPI. Three things happen here:

  GET  .../build/story-plan   — deterministic, synchronous, NO LLM/codegen. Loads
        the backlog + domain + technical specs and returns the ordered
        `StoryCodegenPlan` (`build_story_codegen_plan`). This proves the no-LLM
        planning path on large repos.
  POST .../build/stories[/{id}] — kick off a background job (one per workspace,
        via `jobs.runner.start`) that scaffolds the module from the technical
        design, then runs the per-story TDD loop (`run_story_plan`/`run_story`)
        for ALL ready stories (dependency order) or a single story. Returns 202.
  GET  .../build/stories       — the persisted per-story status map
        (`story_storage.get_status_map`) plus the background job view.

The heavy story-run step (scaffold + per-story slice-pack + LLM/Maven loop) is the
module-level INJECTABLE seam `_run_story_build_step`, whose default value is the
real `_real_story_build_step` — exactly the relationship `build.py` has between its
`_generate_slice_graph` seam and the real generator that `run_build` takes via
`generate=`. The integration test monkeypatches the seam with a stub so the
endpoints/prechecks/job-guard/response-shaping run without a live LLM/Maven/Neo4j.

Typed-spec reconstruction: the build.py `*_brief` loaders return DICTS, but the
planner/context-pack want the typed Pydantic models. The persisted Neo4j nodes
hold the canonical JSON (`epics_json`/`stories_json`, `contexts_json`/
`designs_json`, `services_json`), so `_load_specs` rebuilds `Backlog`,
`DomainDesign`, and `TechnicalDesign` straight off the storages' `get_latest`."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.backlog.schema import Backlog
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.codegen.story_plan import ACCEPTED_STORY_STATUSES, \
    StoryCodegenItem, StoryCodegenPlan, build_story_codegen_plan
from cobol_modernizer.codegen.story_storage import get_status_map
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.build import (
    _brd_requirements, _mark_passed, _output_root, _slice_pack, _source_root,
)
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage
from cobol_modernizer.domain.schema import Aggregate, DomainDesign
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.technical_design.schema import TechnicalDesign, TechnicalService
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-build-stories"])
_NEO4J_ERRORS = (Neo4jError, DriverError)


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


# --------------------------------------------------------------------------- #
# Typed-spec reconstruction off the persisted Neo4j nodes                      #
# --------------------------------------------------------------------------- #
def _load_backlog(neo4j, slug: str) -> Backlog | None:
    """Rebuild the typed `Backlog` from the latest persisted :Backlog node
    (epics_json/stories_json carry the canonical model_dump JSON). None when none
    exists."""
    node = BacklogStorage(neo4j).get_latest(slug)
    if not node:
        return None
    return Backlog.model_validate({
        "repo_slug": slug,
        "version": node.get("version") or 0,
        "epics": json.loads(node.get("epics_json") or "[]"),
        "stories": json.loads(node.get("stories_json") or "[]"),
    })


def _load_domain_design(neo4j, slug: str) -> DomainDesign | None:
    """Rebuild the typed `DomainDesign` from the latest :DomainDesign node."""
    node = DomainDesignStorage(neo4j).get_latest(slug)
    if not node:
        return None
    return DomainDesign.model_validate({
        "repo_slug": slug,
        "version": node.get("version") or 0,
        "rating": node.get("rating") or "medium",
        "contexts": json.loads(node.get("contexts_json") or "[]"),
        "designs": json.loads(node.get("designs_json") or "[]"),
    })


def _load_technical_design(neo4j, slug: str) -> TechnicalDesign | None:
    """Rebuild the typed `TechnicalDesign` from the latest :TechnicalDesign node."""
    node = TechnicalDesignStorage(neo4j).get_latest(slug)
    if not node:
        return None
    return TechnicalDesign.model_validate({
        "repo_slug": slug,
        "version": node.get("version") or 0,
        "services": json.loads(node.get("services_json") or "[]"),
    })


class _Specs:
    """The three typed specs the planner + story-run need, loaded together."""

    def __init__(self, backlog: Backlog, domain: DomainDesign,
                 technical: TechnicalDesign) -> None:
        self.backlog = backlog
        self.domain = domain
        self.technical = technical


def _load_specs(neo4j, slug: str) -> _Specs:
    """Load + reconstruct the typed backlog/domain/technical specs, raising a clear
    409 naming the first missing prerequisite (mirrors build._precheck style)."""
    backlog = _load_backlog(neo4j, slug)
    if backlog is None:
        raise HTTPException(status_code=409,
                            detail="no backlog — run the Backlog stage first")
    domain = _load_domain_design(neo4j, slug)
    if domain is None:
        raise HTTPException(status_code=409,
                            detail="no domain design — run the Design stage first")
    technical = _load_technical_design(neo4j, slug)
    if technical is None:
        raise HTTPException(
            status_code=409,
            detail="no technical design — run the Technical Design stage first")
    return _Specs(backlog, domain, technical)


# --------------------------------------------------------------------------- #
# Plan (deterministic) + prechecks                                            #
# --------------------------------------------------------------------------- #
def _plan_for(neo4j, slug: str) -> StoryCodegenPlan:
    """Deterministic story codegen plan: load typed specs + `build_story_codegen_plan`.
    No LLM, no codegen. 409 on a missing spec (via `_load_specs`)."""
    specs = _load_specs(neo4j, slug)
    return build_story_codegen_plan(specs.backlog, specs.domain, specs.technical)


def _precheck(neo4j, workspace: Workspace, source_root: Path) -> _Specs:
    """Fast, synchronous validation before queueing the multi-minute job: repo dir
    present + a BRD exists + the backlog/domain/technical specs all exist. 404/409
    name the missing prerequisite. Returns the loaded typed specs for convenience,
    though the callers here discard it — the specs are cheaply re-loaded inside the
    plan + the real step (Neo4j reads are inexpensive); thread the return through if
    that ever changes."""
    slug = workspace.repo_slug
    if not (source_root / slug).is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{slug}' not found under {source_root}")
    if not BRDStorage(neo4j).get_latest(slug):
        raise HTTPException(status_code=409,
                            detail="no BRD — run the Blueprint stage first")
    return _load_specs(neo4j, slug)


# --------------------------------------------------------------------------- #
# Resolution helpers for the real story-run step                              #
# --------------------------------------------------------------------------- #
def _aggregate_for_context(domain: DomainDesign, context: str) -> Aggregate | None:
    """The first aggregate of the named bounded context's design (the story's
    primary aggregate), or None when the context has no design/aggregate."""
    for design in domain.designs:
        if design.context == context and design.aggregates:
            return design.aggregates[0]
    return None


def _service_for_item(technical: TechnicalDesign,
                      item: StoryCodegenItem) -> TechnicalService | None:
    """The technical service the plan mapped this item to (by name)."""
    for svc in technical.services:
        if svc.name == item.service_name:
            return svc
    return None


def _brd_req_strings(brd_node: dict | None) -> list[str]:
    """The BRD requirement sections rendered as short strings for the story context
    (`title — body_markdown`, matching `BRDSection`). Empty when no structured BRD
    sections are persisted (legacy nodes that predate `sections`)."""
    out: list[str] = []
    for s in _brd_requirements(brd_node or {}):
        title = (s.get("title") or "").strip()
        body = (s.get("body_markdown") or "").strip()
        line = f"{title} — {body}".strip(" —") if (title or body) else ""
        if line:
            out.append(line)
    return out


def _module_file_index(module_dir: Path) -> list[str]:
    """The scaffolded module's relative file paths, shown to the model as the
    `project_index` so it can SEE the scaffolded layout (`_project_index_section`
    renders it). Bounded to the scaffold's own source/config files; deterministic
    (sorted). Empty when the dir does not yet exist (defensive)."""
    root = Path(module_dir)
    if not root.is_dir():
        return []
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.append(str(path.relative_to(root)))
    return out


# --------------------------------------------------------------------------- #
# Injectable heavy step (default = real scaffold + slice-pack + run_story_plan) #
# --------------------------------------------------------------------------- #
def _real_story_build_step(*, session: Session, neo4j, workspace: Workspace,
                           source_root: Path, output_root: Path,
                           plan: StoryCodegenPlan, story_id: str | None) -> dict:
    """The real orchestration: scaffold the module from the technical design, then
    run the per-story TDD loop (`run_story_plan`) — for ALL ready items or the one
    `story_id`. Each item's per-story slice pack is built via `build.py::_slice_pack`
    (scoped to the story's cobol_refs) and wrapped in a `StoryContextPack`. Imported
    lazily so the agent SDK / scaffold deps are only needed for a real run."""
    import asyncio

    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.harness import SdkAgentRunner
    from cobol_modernizer.codegen.scaffold_from_design import scaffold_from_design
    from cobol_modernizer.codegen.story_context import build_story_context
    from cobol_modernizer.codegen.story_runner import run_story_plan

    slug = workspace.repo_slug
    repo_dir = source_root / slug
    specs = _load_specs(neo4j, slug)
    technical, domain, backlog = specs.technical, specs.domain, specs.backlog

    module_dir = scaffold_from_design(output_root, technical)

    brd_node = BRDStorage(neo4j).get_latest(slug)
    brd_reqs = _brd_req_strings(brd_node)
    deps = GraphDeps(client=neo4j, repo_id=slug, repo_path=repo_dir.resolve())
    story_by_id = {s.id: s for s in backlog.stories}

    items = list(plan.items)
    if story_id is not None:
        items = [i for i in items if i.story_id == story_id]

    def _context_pack_for(item: StoryCodegenItem,
                          completed_summaries: list[str]):
        # `completed_summaries` is the running list of already-built stories, threaded
        # in by `run_story_plan` as it iterates (so the "Completed Dependencies" pack
        # section is actually populated — it is NOT part of the story's context_hash,
        # so this does not destabilize resume).
        story = story_by_id[item.story_id]
        service = _service_for_item(technical, item)
        aggregate = _aggregate_for_context(domain, item.bounded_context)
        # Slice pack scoped to THIS story's cobol_refs (so it stays bounded). The
        # synthetic brief shape couples to `build.py::_target_refs`'s contract: it
        # reads `domain_design.designs[].cobol_mapping[].cobol_ref`. If that key path
        # changes, `_slice_pack` finds no targets and degrades to an empty pack
        # (swallowed by its defensive except) — keep this in sync with `_target_refs`.
        pack = _slice_pack(
            deps, {"domain_design": {"designs": [{"cobol_mapping": [
                {"cobol_ref": r} for r in item.cobol_refs]}]}},
            max_units=int(os.environ.get("CODEGEN_PACK_MAX_UNITS", "200")),
            max_chars=int(os.environ.get("CODEGEN_PACK_MAX_CHARS", "60000")))
        return build_story_context(
            item, story=story, service=service, aggregate=aggregate,
            brd_requirements=brd_reqs, completed_summaries=list(completed_summaries),
            source_pack=pack)

    # Dependency-wave parallel fan-out: `run_story_plan` partitions `items` into
    # dependency waves and runs each wave concurrently (bounded by BUILD_MAX_CONCURRENCY).
    # Each concurrent story needs its OWN runner so per-story token/cost telemetry is not
    # crosstalked — pass the SdkAgentRunner class as the per-story factory rather than a
    # single shared instance.
    runner = SdkAgentRunner()
    results = asyncio.run(run_story_plan(
        items, session=session, workspace_id=workspace.id, module_dir=module_dir,
        context_pack_for=_context_pack_for, runner=runner,
        runner_factory=SdkAgentRunner,
        project_index=_module_file_index(module_dir)))
    return {
        "repo_slug": slug, "module_dir": str(module_dir),
        "story_id": story_id, "story_count": len(items),
        "results": [{"story_id": r.story_id, "status": r.status.value,
                     "attempts": r.attempts} for r in results],
    }


#: Statuses that do NOT fail the build. The SINGLE accepted-status set lives in
#: `story_plan.ACCEPTED_STORY_STATUSES` (shared with the resume policy in
#: `budget.should_skip`, so the gate and resume never drift). `passed`/`skipped`
#: are obvious; a toolchain-absent `generated-unverified` is ACCEPTED-but-unverified
#: by design (the degrade contract — mvn missing must not fail the build), exactly as
#: the story runner's GATE treats it. Anything else (notably `failed`/`blocked`) fails
#: the run so the job surfaces as `failed`, mirroring the sibling fail-loud `/build`.
_ACCEPTABLE_STATUSES = ACCEPTED_STORY_STATUSES


def _gate_stage(result: dict) -> None:
    """Decide whether the `build` stage may be marked passed from the step's per-story
    results. Raises RuntimeError (so the job ends `failed`, surfacing via the GET job
    view's `error`) when there are NO results or ANY story ended in a non-acceptable
    status. The per-story status map is persisted by the runner regardless, so the
    operator still sees the full detail under GET .../build/stories."""
    results = result.get("results") or []
    if not results:
        raise RuntimeError("story build produced no results — nothing was built")
    offenders = sorted({r.get("status") for r in results
                        if r.get("status") not in _ACCEPTABLE_STATUSES})
    if offenders:
        raise RuntimeError(
            "story build did not pass — story statuses not acceptable: "
            f"{', '.join(s for s in offenders if s)}")


def run_story_build(*, session: Session, neo4j, workspace: Workspace,
                    source_root: Path, output_root: Path, story_id: str | None = None,
                    build: Callable[..., dict] = None) -> dict[str, Any]:  # type: ignore[assignment]
    """Run the story build for a workspace: precheck -> plan -> heavy story-run step
    -> gate -> mark the `build` stage passed. `build` is the injectable seam: it
    defaults to the module-level `_run_story_build_step` (whose value is the real
    `_real_story_build_step`), resolved at call time so tests can monkeypatch it —
    mirroring how `run_build` resolves `generate=` against `_generate_slice_graph`.

    The stage is marked passed ONLY when every story ended acceptable (passed /
    generated_unverified / skipped) — `run_story_plan` NEVER raises on a per-story
    failure, so an unconditional mark would silently pass a broken build. A
    non-acceptable status raises (RuntimeError), surfacing the job as `failed`."""
    slug = workspace.repo_slug
    _precheck(neo4j, workspace, source_root)
    plan = _plan_for(neo4j, slug)

    logger.info("build-stories: running for repo=%s story_id=%s (%d items)",
                slug, story_id, len(plan.items))
    # `_run_story_build_step` is assigned below this function (module-level seam);
    # it resolves at call time, so tests monkeypatch the module attribute. Do not
    # "fix" the forward reference.
    step = build or _run_story_build_step
    result = step(session=session, neo4j=neo4j, workspace=workspace,
                  source_root=source_root, output_root=output_root,
                  plan=plan, story_id=story_id)

    _gate_stage(result)
    _mark_passed(session, workspace.id, "build")
    session.flush()
    return {"repo_slug": slug, "story_id": story_id,
            "story_count": len(plan.items), "result": result}


#: Module-level seam for the heavy story-run step (scaffold + per-story slice-pack +
#: run_story_plan). Its value is the real default `_real_story_build_step`; tests
#: monkeypatch THIS attribute with a stub. Mirrors `build._generate_slice_graph`.
_run_story_build_step = _real_story_build_step


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #
def _job_view(job: dict) -> dict:
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error"), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at")}


def _require_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Build needs an LLM.")


def _queue_story_build(wid: str, ws: Workspace, neo4j, story_id: str | None) -> dict:
    """Shared body for the two POST endpoints: key check + fast precheck (translating
    a graph hiccup to 503), then queue the one-per-workspace background job."""
    _require_key()
    try:
        _precheck(neo4j, ws, _source_root())
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            result = run_story_build(session=s, neo4j=neo, workspace=ws2,
                                     source_root=_source_root(),
                                     output_root=_output_root(), story_id=story_id)
            s.commit()
            return result
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    logger.info("build-stories: queued job for workspace=%s repo=%s story_id=%s",
                wid, ws.repo_slug, story_id)
    return _job_view(jobs.runner.start("build-stories", wid, _job))


@router.get("/workspaces/{wid}/build/story-plan")
def story_plan(wid: str, session: Session = Depends(get_session),
               neo4j=Depends(get_neo4j)) -> dict:
    """The deterministic, dependency-ordered `StoryCodegenPlan` — NO LLM, NO codegen.
    409 names the first missing spec (backlog/domain/technical). No API key needed."""
    ws = _workspace(session, wid)
    return _plan_for(neo4j, ws.repo_slug).model_dump(mode="json")


@router.post("/workspaces/{wid}/build/stories", status_code=202)
def build_all_stories(wid: str, session: Session = Depends(get_session),
                      neo4j=Depends(get_neo4j)) -> dict:
    """Kick off a background job that builds ALL ready stories in dependency order;
    return 202 + the job view. One job per workspace (the runner enforces it)."""
    ws = _workspace(session, wid)
    return _queue_story_build(wid, ws, neo4j, story_id=None)


@router.post("/workspaces/{wid}/build/stories/{story_id}", status_code=202)
def build_one_story(wid: str, story_id: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    """Kick off a background job that builds ONE story; return 202 + the job view.
    404 when the story id is not in the plan."""
    ws = _workspace(session, wid)
    _require_key()
    try:
        plan = _plan_for(neo4j, ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not any(i.story_id == story_id for i in plan.items):
        raise HTTPException(status_code=404,
                            detail=f"story '{story_id}' not in the plan")
    return _queue_story_build(wid, ws, neo4j, story_id=story_id)


@router.get("/workspaces/{wid}/build/stories")
def story_status(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    """The persisted per-story status map (`story_codegen_status` artifact) plus the
    background job view (idle/running/done/failed)."""
    _workspace(session, wid)
    job = jobs.runner.get("build-stories", wid)
    job_view = _job_view(job) if job else {
        "status": "idle", "result": None, "error": None,
        "started_at": None, "finished_at": None}
    return {"stories": get_status_map(session, wid), "job": job_view}
