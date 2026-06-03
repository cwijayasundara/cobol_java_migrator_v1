"""Build stage — TDD codegen for a writer slice, grounded in the parsed graph.

POST /api/workspaces/{id}/build asks the codegen agent to emit a Java slice
(JUnit tests FIRST, then minimal Spring Boot code) navigating the repo's Neo4j
graph, scaffolds a Maven module (Spring Boot + the four quality gates: ArchUnit,
SpotBugs/FindSecBugs, Error Prone, Checkstyle), writes the generated files into
it, and marks the `build` stage passed. Needs ANTHROPIC_API_KEY and a parsed
graph; run Blueprint first (the BRD is the codegen brief).

Routing is governed by `CODEGEN_MODE` (default `story`): `POST /build` runs the
story-sliced engine via `build_stories.run_story_build` (scaffold-from-design +
per-story TDD loop), mapping its result to a `BuildResult`-compatible summary;
`legacy_slice` keeps the original one-shot writer-slice path described above as a
debug/fallback escape hatch.

Compiling + running the quality gates (`mvn verify`) is a separate, slower,
host-dependent step (needs Maven + a JDK and a reconciled Spring Boot/Java pair),
so the endpoint produces the source artifact + scaffold, not a compiled jar. The
QualityReport parser (codegen.quality_gate) is the seam for a later CI step."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.codegen.scaffold import scaffold_module
from cobol_modernizer.codegen.scaffold_from_design import module_name_for
from cobol_modernizer.codegen.schema import GeneratedProject
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Artifact, JourneyStage, Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-build"])
_NEO4J_ERRORS = (Neo4jError, DriverError)
_PKG_SAFE = re.compile(r"[^a-z0-9]+")


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


def _output_root() -> Path:
    return Path(os.environ.get("CODEGEN_OUTPUT_DIR", "codegen_output"))


def _base_package(slug: str) -> str:
    leaf = _PKG_SAFE.sub("", slug.split("/")[-1].lower()) or "app"
    return f"com.cobolmodernizer.{leaf}"


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _mark_passed(session: Session, wid: str, stage_key: str) -> None:
    for st in session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == wid,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().all():
        st.status = "passed"


def scan_generated_test_refs(project_dir, acceptance_criteria_ids: list[str]) -> list[str]:
    """Which acceptance-criterion ids the generated test sources actually cite. Codegen
    is instructed to cite story/AC ids in test comments/names; we grep the generated
    *Test.java files for each id. Returns the subset found (deterministic, sorted)."""
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
    return sorted({ac for ac in acceptance_criteria_ids
                   if ac and re.search(r"\b" + re.escape(ac) + r"\b", haystack)})


def _record_generated_test_refs(session: Session, *, workspace_id: str, project_dir,
                                acceptance_criteria_ids: list[str]) -> None:
    """Persist which acceptance-criterion ids the generated tests cite, as a
    versioned Artifact the Verify stage's story-behavior gate reads.

    The new version is CUMULATIVE: the newly-scanned refs are UNIONed with the prior
    latest version's `acceptance_criteria`, so the latest row is always the accumulated
    set across every story built so far. The story path calls this ONCE PER STORY
    (`story_runner._persist`) scoped to that story's AC ids; without the merge, each
    new version would hold ONLY the last story's ACs, and the Verify story-behavior
    gate — which reads the single latest version and checks it against ALL stories' ACs
    — would report "missing generated tests" for every story but the last and fail a
    perfectly-built run. The merge is also harmless to the legacy `run_build` path: on a
    fresh build prior is empty so union == today's scan; a re-run merges forward
    idempotently. Single-story `POST /build/stories/{id}` builds accumulate likewise."""
    refs = scan_generated_test_refs(project_dir, acceptance_criteria_ids)
    prev = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == "generated_test_refs")
    ).scalars().all()
    version = max((a.version for a in prev), default=0) + 1
    prior_refs: list[str] = []
    if prev:
        latest = max(prev, key=lambda a: a.version)
        prior_refs = (latest.evidence_map or {}).get("acceptance_criteria", []) or []
    merged = sorted(set(refs) | set(prior_refs))
    session.add(Artifact(workspace_id=workspace_id, kind="generated_test_refs",
                         version=version, object_uri="inline://generated_test_refs",
                         content_hash="sha256:refs",
                         evidence_map={"acceptance_criteria": merged}))
    session.flush()


def _target_refs(brief: dict) -> list[str]:
    """The COBOL entities this slice is about, named deterministically by the domain
    design: each context's member_programs + every cobol_mapping.cobol_ref. Deduped,
    order-preserving. Empty when no design has been run (caller falls back)."""
    refs: list[str] = []
    dd = brief.get("domain_design") or {}
    for ctx in dd.get("contexts", []):
        refs.extend(ctx.get("member_programs", []) or [])
    for design in dd.get("designs", []):
        for m in design.get("cobol_mapping", []) or []:
            if m.get("cobol_ref"):
                refs.append(m["cobol_ref"])
    return list(dict.fromkeys(r for r in refs if r))


def _slice_pack(deps, brief: dict, *, max_units: int, max_chars: int) -> str:
    """Pre-materialize the slice's COBOL source in Python (cheap Cypher reads) so the
    agent emits directly instead of paying an LLM tool round-trip per entity. Scoped
    to the entities the domain design names (+ their paragraphs), so the pack size
    tracks the SLICE, not the repo — bounded for large codebases. Char-budgeted
    (truncates) and fully defensive: any graph hiccup degrades to '' (tool fallback).

    `from cobol_modernizer.agent import graph_ops` is imported lazily by the caller."""
    from cobol_modernizer.agent import graph_ops as ops

    def _resolve_target(ref: str) -> str:
        ent = ops.get_entity(deps, ref)
        qn = ent.get("qualified_name") if isinstance(ent, dict) else None
        return qn or ref

    try:
        targets = [_resolve_target(t) for t in _target_refs(brief)]
        if not targets:  # no design yet — fall back to the repo's programs (small repos)
            targets = [e["qualified_name"] for e in
                       ops.find_entities(deps, kind="Program", limit=max_units).get("entities", [])]

        ordered: list[str] = []
        seen: set[str] = set()
        for t in targets:
            if t not in seen:
                seen.add(t); ordered.append(t)
            try:  # expand a program to its contained paragraphs so the body is inlined too
                for nb in ops.neighbors(deps, t, edge="CONTAINS", direction="out",
                                        limit=max_units).get("neighbors", []):
                    qn = nb.get("qualified_name")
                    if qn and qn not in seen:
                        seen.add(qn); ordered.append(qn)
            except Exception:  # noqa: BLE001 — a missing edge must not abort the pack
                pass

        parts: list[str] = []
        total = 0
        for qn in ordered[:max_units]:
            sl = ops.get_source_slice(deps, qn)
            src = sl.get("source") if isinstance(sl, dict) else None
            if not src:
                continue
            block = f"### {qn}\n```cobol\n{src}\n```"
            if total + len(block) > max_chars:
                break  # truncate — keep what fits, let tools cover the rest
            total += len(block); parts.append(block)
        return "\n\n".join(parts)
    except Exception:  # noqa: BLE001 — prefetch is an optimization; never fail the build
        logger.warning("build: slice prefetch failed; falling back to graph exploration",
                       exc_info=True)
        return ""


def _codegen_run_plan(*, pack: bool, size: int) -> tuple[int, bool]:
    """Decide how to run codegen. Returns (max_turns, use_graph_tools).

    When the slice source is prefetched we run TOOL-FREE: no MCP graph server, no
    allowed tools, a tiny turn budget — i.e. a single structured completion. The
    agent-SDK turn-loop (re-sending full context per tool round-trip) is the real
    latency sink, and with BRD + design + source inlined there is nothing to look up.
    Only when prefetch yields nothing do we fall back to size-scaled agentic graph
    exploration (graph as the genuine last resort)."""
    from cobol_modernizer.cost.scaling import turns_for
    if pack:
        return int(os.environ.get("CODEGEN_INLINE_TURNS", "2")), False
    lo = int(os.environ.get("CODEGEN_AGENT_MIN_TURNS", "16"))
    hi = int(os.environ.get("CODEGEN_AGENT_MAX_TURNS", "40"))
    return turns_for(size, lo=lo, hi=hi), True


def _generate_slice_graph(slug: str, *, neo4j, repo_path: str,
                          brd_json: str) -> GeneratedProject:
    """Real codegen. Fast path: prefetch the slice source and run the TDD agent
    TOOL-FREE (single structured completion from BRD + design + source). Fallback,
    only when prefetch is empty: stand up the read-only graph MCP server and let the
    agent explore. Imported lazily so the agent SDK is only required when an actual
    generation runs (tests inject a stub instead)."""
    import asyncio

    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
    from cobol_modernizer.agent.harness import SdkAgentRunner
    from cobol_modernizer.codegen.generator import generate_slice
    from cobol_modernizer.cost.scaling import model_for_size

    deps = GraphDeps(client=neo4j, repo_id=slug, repo_path=Path(repo_path))
    runner = SdkAgentRunner()

    # MODEL stays on Sonnet by default: codegen is the highest-stakes LLM task (strict
    # TDD + Spring Boot), and the cheap Haiku tier demonstrably thrashed for minutes and
    # skipped tests. CODEGEN_SMALL_TIER can drop tiny slices to Haiku to save cost; an
    # explicit CODEGEN_MODEL / global pin always wins.
    try:
        size = neo4j.run(
            "MATCH (n:CodeEntity {repo:$r}) WHERE n.kind IN ['Program','Paragraph'] "
            "RETURN count(n) AS c", r=slug)[0]["c"]
    except Exception:  # noqa: BLE001
        size = 0
    pinned = os.environ.get("CODEGEN_MODEL") or os.environ.get("COBOL_MOD_LLM_MODEL")
    model = model_for_size(size, threshold=int(os.environ.get("CODEGEN_SMALL_UNITS", "25")),
                           small_tier=os.environ.get("CODEGEN_SMALL_TIER", "sonnet"),
                           large_tier="sonnet", pinned=pinned)

    # Efficiency: deterministically pre-fetch the slice source (scoped to the design's
    # entities, so it stays bounded for large repos) and inline it. With BRD + design +
    # source in the prompt there is nothing to look up, so we run TOOL-FREE — no MCP
    # graph server, a single structured completion — which is what kills the latency
    # (the SDK turn-loop re-sends the whole context on every tool round-trip). Only an
    # empty prefetch falls back to the agentic graph path (graph as the last resort).
    try:
        brief = json.loads(brd_json)
    except (TypeError, ValueError):
        brief = {}
    pack = _slice_pack(deps, brief,
                       max_units=int(os.environ.get("CODEGEN_PACK_MAX_UNITS", "200")),
                       max_chars=int(os.environ.get("CODEGEN_PACK_MAX_CHARS", "60000")))
    max_turns, use_graph = _codegen_run_plan(pack=bool(pack), size=size)
    server = build_graph_server(deps) if use_graph else None
    allowed_tools = GRAPH_TOOL_NAMES if use_graph else []
    logger.info("build: codegen for repo=%s — %d code units, prefetch=%d chars -> "
                "%d turns, tools=%s, model=%s", slug, size, len(pack), max_turns,
                "graph" if use_graph else "none", model)
    return asyncio.run(generate_slice(
        runner=runner, server=server, model=model, source_pack=pack,
        brd_json=brd_json, golden_summary="(no recorded golden master yet)",
        allowed_tools=allowed_tools, max_turns=max_turns,
        timeout_s=float(os.environ.get("CODEGEN_TIMEOUT_S", "120"))))


def _brd_requirements(brd_node: dict) -> list[dict]:
    """The BRD's actual requirement sections (FRs/NFRs + body), not just metadata.
    Empty list for legacy nodes that predate structured `sections` persistence."""
    raw = brd_node.get("sections")
    if not raw:
        return []
    try:
        secs = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [s for s in secs if isinstance(s, dict)]


def _domain_design_brief(neo4j, slug: str) -> dict | None:
    """The persisted DDD/OO DomainDesign as a plain dict (bounded contexts + the
    tactical designs: aggregates/invariants/value objects/api surface). None when no
    design has been run yet — codegen then grounds on the BRD requirements alone."""
    from cobol_modernizer.controlplane.domain import DomainDesignStorage

    try:
        node = DomainDesignStorage(neo4j).get_latest(slug)
    except _NEO4J_ERRORS:
        return None
    if not node:
        return None
    return {
        "version": node.get("version"),
        "rating": node.get("rating"),
        "contexts": json.loads(node.get("contexts_json") or "[]"),
        "designs": json.loads(node.get("designs_json") or "[]"),
    }


def _backlog_brief(neo4j, slug: str) -> dict | None:
    """The persisted business backlog (epics + user stories with acceptance criteria)
    as a plain dict. None when no backlog has been generated — codegen then grounds on
    the BRD/design alone. Defensive: a graph hiccup degrades to None."""
    try:
        rows = neo4j.run(
            """
            MATCH (r:Repository {slug: $repo_slug})-[:HAS_BACKLOG]->(b:Backlog)
            RETURN b ORDER BY b.version DESC LIMIT 1
            """,
            repo_slug=slug,
        )
    except _NEO4J_ERRORS:
        return None
    if not rows:
        return None
    node = rows[0]["b"]
    return {
        "version": node.get("version"),
        "epics": json.loads(node.get("epics_json") or "[]"),
        "stories": json.loads(node.get("stories_json") or "[]"),
    }


def _technical_design_brief(neo4j, slug: str) -> dict | None:
    """The persisted technical/target architecture (services with API/persistence/
    integration contracts) as a plain dict. None when none has been generated.
    Defensive: a graph hiccup degrades to None."""
    try:
        rows = neo4j.run(
            """
            MATCH (r:Repository {slug: $repo_slug})-[:HAS_TECHNICAL_DESIGN]->(t:TechnicalDesign)
            RETURN t ORDER BY t.version DESC LIMIT 1
            """,
            repo_slug=slug,
        )
    except _NEO4J_ERRORS:
        return None
    if not rows:
        return None
    node = rows[0]["t"]
    return {
        "version": node.get("version"),
        "services": json.loads(node.get("services_json") or "[]"),
    }


def _codegen_brief(neo4j, slug: str, brd_node: dict) -> str:
    """Assemble the codegen brief the TDD agent reasons over: the BRD's real
    requirement text PLUS the DDD/OO domain design. Version/rating metadata alone
    starves the agent — with nothing concrete to assert it emits production code but
    no failing test (generator raises 'no failing test'). The DomainDesign's
    aggregate invariants, methods, and api_surface are directly assertable in JUnit,
    so feeding them in is what lets codegen honor TDD."""
    brief: dict[str, Any] = {
        "repo_id": slug,
        "brd": {"version": brd_node.get("version"), "rating": brd_node.get("rating"),
                "requirements": _brd_requirements(brd_node)},
    }
    design = _domain_design_brief(neo4j, slug)
    if design:
        brief["domain_design"] = design
    backlog = _backlog_brief(neo4j, slug)
    if backlog:
        brief["backlog"] = backlog
    technical = _technical_design_brief(neo4j, slug)
    if technical:
        brief["technical_design"] = technical
    return json.dumps(brief)


def _precheck(neo4j, workspace: Workspace, source_root: Path) -> dict:
    """Fast, synchronous validation before queueing the multi-minute codegen job:
    repo dir present + a BRD exists (the codegen brief). Returns the latest BRD."""
    slug = workspace.repo_slug
    if not (source_root / slug).is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{slug}' not found under {source_root}")
    latest = BRDStorage(neo4j).get_latest(slug)
    if not latest:
        raise HTTPException(status_code=409,
                            detail="no BRD — run the Blueprint stage first")
    return latest


def _codegen_mode() -> str:
    """Which engine `POST /build` routes through. DEFAULT `story`: the story-sliced
    codegen loop (scaffold-from-design + per-story TDD). `legacy_slice`: the original
    one-shot `_generate_slice_graph` + `generate_slice` path (debug/fallback escape
    hatch). Any unrecognized value falls back to the story default."""
    mode = os.environ.get("CODEGEN_MODE", "story").strip().lower()
    return mode if mode in {"story", "legacy_slice"} else "story"


def build_precheck(neo4j, workspace: Workspace, source_root: Path) -> dict:
    """Mode-aware precheck for the public `POST /build`. `legacy_slice` needs only a
    repo dir + BRD (so a repo with just a Blueprint can still use the escape hatch);
    `story` additionally needs the backlog/domain/technical specs (the story engine's
    prerequisites), giving a clear 409 naming the first missing one. Returns the latest
    BRD (legacy) or the BRD after a successful story-spec check."""
    latest = _precheck(neo4j, workspace, source_root)
    if _codegen_mode() == "story":
        from cobol_modernizer.controlplane import build_stories
        build_stories._load_specs(neo4j, workspace.repo_slug)
    return latest


def _scan_module_files(root: Path) -> list[dict[str, Any]]:
    """Enumerate the Java source files written under a scaffolded module, classified
    `test` (filename contains `test`, matching `scan_generated_test_refs`) vs `main`,
    as `{path, kind, evidence}` with a module-relative path. Evidence is left empty —
    the per-story lineage lives in the persisted story status map, not here — so the
    legacy slice UI's file list still renders. Deterministic (sorted by path)."""
    if not root.is_dir():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.java")):
        kind = "test" if "test" in path.name.lower() else "main"
        files.append({"path": str(path.relative_to(root)), "kind": kind,
                      "evidence": []})
    return files


def _story_build_summary(*, session: Session, neo4j, workspace: Workspace,
                         source_root: Path, output_root: Path,
                         build: Callable[..., dict] | None = None) -> dict[str, Any]:
    """Run the story engine for the whole workspace and map its result to a summary
    COMPATIBLE with the legacy `BuildResult`/UI shape. `run_story_build` scaffolds the
    module from the technical design, runs ALL ready stories' TDD loops, records each
    story's `generated_test_refs`, gates, and marks the `build` stage passed — so all
    the legacy side-effects already happen inside it.

    The story run produces per-story results + ONE scaffolded module (not a single
    slice), so the file_count/tests/mains are aggregated by scanning the module on
    disk. `slice_id` is the synthetic `"stories"` (the UI only displays it via the
    type; it renders `module`/`base_package`/`tests`/`mains`/`scaffold_path`/`files`),
    and a `stories` summary (the per-story status list) is added for richer UIs.
    `evidence_map` defaults to `{}` (per-story lineage lives in the story status map)."""
    from cobol_modernizer.controlplane import build_stories

    outcome = build_stories.run_story_build(
        session=session, neo4j=neo4j, workspace=workspace,
        source_root=source_root, output_root=output_root, story_id=None,
        build=build)  # type: ignore[arg-type]

    slug = workspace.repo_slug
    inner = outcome.get("result") or {}
    module_dir = inner.get("module_dir")
    root = Path(module_dir) if module_dir else (output_root / module_name_for(slug))
    files = _scan_module_files(root)
    stories = inner.get("results") or []
    return {
        "repo_slug": slug,
        "slice_id": "stories",
        "module": module_name_for(slug),
        "base_package": _base_package(slug),
        "scaffold_path": str(root),
        "file_count": len(files),
        "tests": sum(1 for f in files if f["kind"] == "test"),
        "mains": sum(1 for f in files if f["kind"] == "main"),
        "files": files,
        "evidence_map": {},
        "stories": stories,
        # Pass-with-deferred progress counts from the gate (folded onto the step result
        # by `run_story_build`): how many stories genuinely built vs were deferred /
        # still pending. Surfaced so the cockpit can show real progress on a build that
        # passed WITH deferred stories.
        "story_counts": {
            "story_count": inner.get("story_count", len(stories)),
            "pass_count": inner.get("pass_count"),
            "deferred_count": inner.get("deferred_count"),
            "skipped_count": inner.get("skipped_count"),
            "pending": inner.get("pending"),
        },
    }


def run_build(*, session: Session, neo4j, workspace: Workspace,
              source_root: Path, output_root: Path,
              generate: Callable[..., GeneratedProject] | None = None,
              build: Callable[..., dict] | None = None) -> dict[str, Any]:
    """Generate code for a workspace and return a `BuildResult`-shaped summary.

    Dispatches on `CODEGEN_MODE` (default `story`): the story engine (scaffold-from-
    design + per-story TDD loop, via `build_stories.run_story_build`) — `build=` is the
    injectable heavy story-run step. `legacy_slice` keeps the original one-shot path
    (`_generate_slice_graph` + `generate_slice`) EXACTLY as-is for debug/fallback;
    `generate=` injects its codegen stub. Both modes mark the `build` stage passed and
    record per-story/slice `generated_test_refs`, and both return the same top-level
    keys the cockpit's `BuildResult` reads."""
    if _codegen_mode() == "story":
        return _story_build_summary(session=session, neo4j=neo4j,
                                    workspace=workspace, source_root=source_root,
                                    output_root=output_root, build=build)

    slug = workspace.repo_slug
    repo_dir = source_root / slug
    latest = _precheck(neo4j, workspace, source_root)
    brd_json = _codegen_brief(neo4j, slug, latest)

    logger.info("build: generating slice for repo=%s (BRD v%s)", slug, latest.get("version"))
    gen = generate or _generate_slice_graph
    project = gen(slug, neo4j=neo4j, repo_path=str(repo_dir.resolve()),
                  brd_json=brd_json)

    base_package = _base_package(slug)
    module = f"{_PKG_SAFE.sub('-', slug.split('/')[-1].lower())}-{project.slice_id}"
    root = scaffold_module(output_root, module=module, base_package=base_package)
    for f in project.files:
        dest = root / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")

    backlog = _backlog_brief(neo4j, slug)
    ac_ids = [c.get("id") for s in (backlog or {}).get("stories", [])
              for c in s.get("acceptance_criteria", []) if c.get("id")] if backlog else []
    if ac_ids:
        _record_generated_test_refs(session, workspace_id=workspace.id,
                                    project_dir=root,
                                    acceptance_criteria_ids=ac_ids)

    _mark_passed(session, workspace.id, "build")
    session.flush()
    files = [{"path": f.path, "kind": f.kind, "evidence": f.evidence}
             for f in project.files]
    return {
        "repo_slug": slug, "slice_id": project.slice_id, "module": module,
        "base_package": base_package, "scaffold_path": str(root),
        "file_count": len(project.files),
        "tests": sum(1 for f in project.files if f.kind == "test"),
        "mains": sum(1 for f in project.files if f.kind == "main"),
        "files": files, "evidence_map": project.evidence_map,
    }


def _job_view(job: dict) -> dict:
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error"), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at")}


@router.post("/workspaces/{wid}/build", status_code=202)
def build_workspace(wid: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    """Kick off the (multi-minute) codegen run as a background job and return 202;
    the UI polls GET .../build. Validates fast first (key / repo dir / BRD present),
    and in story mode (the `CODEGEN_MODE` default) also that the backlog/domain/
    technical specs exist. A TDD violation surfaces as a 'failed' job (error in the
    GET status)."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Build needs an LLM.")
    try:
        build_precheck(neo4j, ws, _source_root())
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            result = run_build(session=s, neo4j=neo, workspace=ws2,
                               source_root=_source_root(), output_root=_output_root())
            s.commit()
            return result
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    logger.info("build: queued background run for workspace=%s repo=%s",
                wid, ws.repo_slug)
    return _job_view(jobs.runner.start("build", wid, _job))


@router.get("/workspaces/{wid}/build")
def build_status(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    """Poll the background codegen job (running / done+manifest / failed+error)."""
    _workspace(session, wid)
    job = jobs.runner.get("build", wid)
    if job is None:
        return {"status": "idle", "result": None, "error": None,
                "started_at": None, "finished_at": None}
    return _job_view(job)
