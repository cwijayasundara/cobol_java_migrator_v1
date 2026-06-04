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
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.backlog.schema import Backlog
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.codegen.story_plan import ACCEPTED_STORY_STATUSES, \
    StoryCodegenItem, StoryCodegenPlan, StoryCodegenStatus, build_story_codegen_plan
from cobol_modernizer.codegen.story_storage import get_status_map
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.build import (
    _brd_requirements, _mark_passed, _output_root, _slice_pack, _source_root,
)
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage
from cobol_modernizer.domain.schema import Aggregate, DomainDesign
from cobol_modernizer.persistence.repo import PgRepo
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


def _package_lines_for_item(technical: TechnicalDesign,
                            item: StoryCodegenItem) -> list[str]:
    """Service-scoped Spring package paths for the story prompt."""
    needle = item.service_name.replace("-service", "").replace("-", "").lower()
    out: list[str] = []
    for pkg in technical.package_structure:
        compact = pkg.replace(".", "").replace("-", "").lower()
        if needle and needle in compact:
            out.append(pkg)
    if out:
        return out

    # Generic fallback: some technical-design artifacts predate package_structure or
    # use service names that do not appear verbatim in it. The scaffold still derives
    # service packages from repo_slug + service.name, so mirror that convention here.
    from cobol_modernizer.codegen.scaffold_from_design import base_package_for

    base = base_package_for(technical.repo_slug)
    service_leaf = item.service_name[:-8] if item.service_name.endswith("-service") else item.service_name
    service_pkg = re.sub(r"[^a-z0-9]+", "", service_leaf.lower()) or "service"
    root = f"{base}.{service_pkg}"
    return [
        f"{root}.api",
        f"{root}.application",
        f"{root}.domain",
        f"{root}.infrastructure",
    ]


def _database_lines_for_item(technical: TechnicalDesign,
                             item: StoryCodegenItem) -> list[str]:
    """Service-scoped database schema/table/column lines for the story prompt."""
    out: list[str] = []
    for db in technical.database_design:
        if not isinstance(db, dict) or db.get("service") != item.service_name:
            continue
        schema = db.get("schema", "")
        migration = db.get("migration_location", "")
        out.append(f"schema={schema} migration={migration}".strip())
        tables = db.get("tables") if isinstance(db.get("tables"), list) else []
        for table in tables:
            if not isinstance(table, dict):
                continue
            columns = table.get("columns") if isinstance(table.get("columns"), list) else []
            col_text = ", ".join(
                f"{c.get('name')} {c.get('type')}"
                for c in columns if isinstance(c, dict) and c.get("name"))
            out.append(
                f"table={table.get('table')} legacy_resource={table.get('legacy_resource')} "
                f"entity={table.get('entity')} columns=[{col_text}]")
    return out


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
    from cobol_modernizer.codegen.behavior_model import build_behavior_model
    from cobol_modernizer.codegen.budget import build_budget_from_env
    from cobol_modernizer.codegen.scaffold_from_design import scaffold_from_design
    from cobol_modernizer.codegen.story_context import build_story_context
    from cobol_modernizer.codegen.story_runner import run_story_plan_until_done

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
        behavior_model = build_behavior_model(item, pack)
        package_lines = _package_lines_for_item(technical, item)
        database_lines = _database_lines_for_item(technical, item)
        logger.info(
            "build-stories: context pack story=%s refs=%d source_chars=%d "
            "behavior_signals=%d package_lines=%d database_lines=%d",
            item.story_id, len(item.cobol_refs), len(pack or ""),
            sum(len(v) for v in behavior_model.values() if isinstance(v, list)),
            len(package_lines), len(database_lines))
        return build_story_context(
            item, story=story, service=service, aggregate=aggregate,
            brd_requirements=brd_reqs, completed_summaries=list(completed_summaries),
            source_pack=pack,
            behavior_model=behavior_model,
            package_lines=package_lines,
            database_lines=database_lines)

    # Repeat-until-done OUTER loop (Task 6 wrapper): `run_story_plan_until_done` runs the
    # whole plan, then re-runs ONLY the still-`failed` stories until they pass, the pooled
    # budget is exhausted, or the per-story attempt cap is hit — at which point any story
    # still failing is re-stamped TERMINAL `deferred` (pass-with-deferred: one bad story
    # never wedges the build). The build-level POOLED token budget (with the retained
    # per-story cap) is sized from the environment off the plan's story count. Each
    # concurrent story still gets its OWN runner (SdkAgentRunner factory) so per-story
    # token/cost telemetry is not crosstalked.
    runner = SdkAgentRunner()
    ledger = PgRepo(session)
    agent_run = ledger.start_run(
        workspace_id=workspace.id, stage_id=None, role="story-codegen",
        model=os.environ.get("STORY_CODEGEN_MODEL", "sonnet"), started_by="system")
    session.flush()
    results = asyncio.run(run_story_plan_until_done(
        items, session=session, workspace_id=workspace.id, module_dir=module_dir,
        context_pack_for=_context_pack_for, runner=runner,
        runner_factory=SdkAgentRunner,
        build_budget=build_budget_from_env(len(items)),
        project_index=_module_file_index(module_dir), ledger=ledger,
        repo_slug=slug, agent_run_id=agent_run.id,
        model=os.environ.get("STORY_CODEGEN_MODEL", "sonnet")))
    return {
        "repo_slug": slug, "module_dir": str(module_dir),
        "story_id": story_id, "story_count": len(items),
        "results": [{"story_id": r.story_id, "status": r.status.value,
                     "attempts": r.attempts} for r in results],
    }


#: Statuses that count as a story GENUINELY BUILT. The SINGLE accepted-status set lives
#: in `story_plan.ACCEPTED_STORY_STATUSES` (shared with the resume policy in
#: `budget.should_skip`, so the gate and resume never drift). `passed` is obvious; a
#: toolchain-absent `generated-unverified` is ACCEPTED-but-unverified by design (the
#: degrade contract — mvn missing must not fail the build), exactly as the story
#: runner's GATE treats it; `skipped` is an already-accepted earlier outcome.
_ACCEPTABLE_STATUSES = ACCEPTED_STORY_STATUSES

#: The `deferred` status — a story that exhausted its repeat-until-done retry/budget
#: allotment WITHOUT acceptance, but is not a hard `error`/`failed`. The build gate
#: TOLERATES it (pass-with-deferred: one bad story can never wedge the build) even
#: though it is deliberately NOT in `ACCEPTED_STORY_STATUSES`. The operator still sees
#: every deferred story (counts below + the persisted per-story status map).
_DEFERRED_STATUS = StoryCodegenStatus.deferred.value

#: The full set the gate TOLERATES = genuinely-built ∪ {deferred}. A status outside
#: this set (notably `failed`/`error`/`blocked`) STILL fails the gate, surfacing the
#: job as `failed` and leaving the stage un-passed — mirroring the sibling fail-loud
#: `/build`. Deferred passes; error/failed does not.
_GATE_TOLERATED = frozenset(_ACCEPTABLE_STATUSES) | {_DEFERRED_STATUS}


def _gate_stage(result: dict, *, targeted_story: bool = False) -> dict[str, int]:
    """Decide whether the `build` stage may be marked passed from the step's per-story
    results, PASS-WITH-DEFERRED. Returns a small progress-count summary
    (`pass_count`/`deferred_count`/`pending`/`story_count`) the caller surfaces so the
    operator sees real progress.

    Raises RuntimeError (so the job ends `failed`, surfacing via the GET job view's
    `error`) when:
      - there are NO results (nothing was built); OR
      - ANY story ended in a status outside the tolerated set — i.e. a genuine
        `failed`/`error`/`blocked` (DISTINCT from `deferred`, which is tolerated); OR
      - NO story was GENUINELY built (every result is `deferred`/`skipped`) — a build
        that produced zero passed/generated-unverified stories has not really built.

    `deferred` is explicitly tolerated (never wedge the build on one bad story) even
    though it is NOT in `ACCEPTED_STORY_STATUSES`. The per-story status map is persisted
    by the runner regardless, so the operator still sees the full detail under GET
    .../build/stories."""
    results = result.get("results") or []
    if not results:
        raise RuntimeError("story build produced no results — nothing was built")

    statuses = [r.get("status") for r in results]
    offenders = sorted({s for s in statuses if s not in _GATE_TOLERATED})
    if offenders:
        raise RuntimeError(
            "story build did not pass — story statuses not acceptable: "
            f"{', '.join(s for s in offenders if s)}")

    pass_count = sum(1 for s in statuses if s in _ACCEPTABLE_STATUSES
                     and s != StoryCodegenStatus.skipped.value)
    skipped_count = sum(1 for s in statuses
                        if s == StoryCodegenStatus.skipped.value)
    deferred_count = sum(1 for s in statuses if s == _DEFERRED_STATUS)
    # GENUINELY built = passed or generated-unverified (NOT skipped, NOT deferred). At
    # least one is required so an all-deferred / all-skipped run cannot pass the gate.
    if pass_count == 0 and not targeted_story:
        raise RuntimeError(
            "story build produced no genuinely-built stories "
            f"(deferred={deferred_count}, skipped={skipped_count}) — build did not pass")
    return {
        "story_count": len(statuses),
        "pass_count": pass_count,
        "skipped_count": skipped_count,
        "cache_hit_count": skipped_count,
        "rebuilt_count": pass_count + deferred_count,
        "deferred_count": deferred_count,
        # `pending` = anything tolerated-but-not-yet-a-genuine-pass (deferred + skipped):
        # what the operator still has outstanding from a clean rebuild.
        "pending": deferred_count + skipped_count,
    }


#: Re-trigger policy. RESTART-FRESH by default (`BUILD_RESUME=0`): a new POST /build(/
#: stories) regenerates ALL stories, ignoring prior RUNS' persisted accepted state — so
#: a second trigger never silently skips everything as already-done. The within-RUN
#: dedup (the repeat-until-done loop not regenerating a story already accepted IN THIS
#: RUN) is owned by `run_story_plan_until_done`'s in-memory pass bookkeeping and is
#: UNAFFECTED by this reset. A reserved `BUILD_RESUME=1` (resume/force) flag would keep
#: prior accepted state to resume across runs — NOT wired yet (reserved; default fresh).
BUILD_RESUME_ENV = "BUILD_RESUME"


def _build_resume() -> bool:
    """Whether to RESUME across runs (keep prior accepted per-story state). Default
    False (restart-fresh). Only an explicit truthy `BUILD_RESUME` opts in; the resume
    path itself is reserved/unbuilt, so today this only ever returns False unless an
    operator forces it."""
    return os.environ.get(BUILD_RESUME_ENV, "0").strip().lower() in {"1", "true", "yes"}


def _reset_prior_story_status(session: Session, workspace: Workspace,
                              plan: StoryCodegenPlan, story_id: str | None) -> None:
    """RESTART-FRESH: clear the persisted `story_codegen_status` records for the stories
    this run will (re)build, so the cross-run resume policy (`budget.should_skip`, which
    skips an accepted story whose context_hash is unchanged) finds NO prior record and
    every targeted story is regenerated from scratch. Bounded to the stories in scope
    (the one `story_id`, or the whole plan) so a single-story re-trigger never wipes the
    other stories' history. The within-RUN dedup is untouched (it is in-memory in the
    repeat loop, not read from these records)."""
    from cobol_modernizer.codegen.story_storage import (
        get_status_map, record_story_status,
    )
    targets = ({story_id} if story_id is not None
               else {i.story_id for i in plan.items})
    current = get_status_map(session, workspace.id)
    stale = [sid for sid in targets if sid in current]
    for sid in stale:
        # Re-stamp to `pending` (a non-accepted status) so the resume policy re-runs the
        # story. We write rather than hard-delete to preserve the artifact version chain.
        record_story_status(session, workspace_id=workspace.id, story_id=sid,
                            payload={
                                "status": StoryCodegenStatus.pending.value,
                                "phase": "queued",
                                "phase_label": "Queued for rebuild",
                                "resume": {"skip": False, "cache_hit": False,
                                           "reason": "restart-fresh rebuild"},
                            })
    if stale:
        session.commit()
    if stale:
        logger.info("build-stories: restart-fresh reset %d prior story record(s) "
                    "for repo=%s", len(stale), workspace.repo_slug)


def run_story_build(*, session: Session, neo4j, workspace: Workspace,
                    source_root: Path, output_root: Path, story_id: str | None = None,
                    build: Callable[..., dict] = None) -> dict[str, Any]:  # type: ignore[assignment]
    """Run the story build for a workspace: precheck -> plan -> (restart-fresh reset)
    -> heavy story-run step -> gate -> mark the `build` stage passed. `build` is the
    injectable seam: it defaults to the module-level `_run_story_build_step` (whose
    value is the real `_real_story_build_step`), resolved at call time so tests can
    monkeypatch it — mirroring how `run_build` resolves `generate=` against
    `_generate_slice_graph`.

    RE-TRIGGER is RESTART-FRESH (`BUILD_RESUME=0` default): before running, prior runs'
    accepted per-story status is cleared so a second POST regenerates ALL stories rather
    than skipping them as already-done. The within-RUN repeat-until-done dedup is
    untouched.

    PASS-WITH-DEFERRED: the stage is marked passed when every story is tolerated
    (passed / generated-unverified / skipped / deferred) AND at least one was genuinely
    built — `deferred` (a story that exhausted its retry/budget allotment) NEVER wedges
    the build, but a true `failed`/`error` STILL fails the gate (RuntimeError, surfacing
    the job as `failed`). The gate's progress counts (pass/deferred/pending) are folded
    into the returned `result` so the operator sees real progress."""
    slug = workspace.repo_slug
    _precheck(neo4j, workspace, source_root)
    plan = _plan_for(neo4j, slug)

    if not _build_resume():
        _reset_prior_story_status(session, workspace, plan, story_id)

    logger.info("build-stories: running for repo=%s story_id=%s (%d items)",
                slug, story_id, len(plan.items))
    # `_run_story_build_step` is assigned below this function (module-level seam);
    # it resolves at call time, so tests monkeypatch the module attribute. Do not
    # "fix" the forward reference.
    step = build or _run_story_build_step
    result = step(session=session, neo4j=neo4j, workspace=workspace,
                  source_root=source_root, output_root=output_root,
                  plan=plan, story_id=story_id)
    if isinstance(result, dict) and story_id is not None:
        result.setdefault("story_id", story_id)

    counts = _gate_stage(result, targeted_story=story_id is not None)
    # Surface the gate's progress counts (pass/deferred/pending) on the step's result so
    # the operator sees real progress — pass-with-deferred can read as `done` even with
    # deferred stories, so the counts are how the cockpit shows what was deferred.
    if isinstance(result, dict):
        result.update(counts)
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
    stories = get_status_map(session, wid)
    if job_view["status"] != "running":
        stories = {
            sid: (
                {**rec, "status": StoryCodegenStatus.pending.value,
                 "phase": "stale-running",
                 "phase_label": "Previous run stopped before terminal status"}
                if isinstance(rec, dict) and rec.get("status") == "running"
                else rec
            )
            for sid, rec in stories.items()
        }
    return {"stories": stories, "job": job_view}
