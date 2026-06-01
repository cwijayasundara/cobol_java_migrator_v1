from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.harness import AgentRunner

from cobol_modernizer.cost.tiering import GLOBAL_ENV, HAIKU, SONNET, resolve_model
from cobol_modernizer.brd.renderer import render_html
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.brd.schema import (
    AttemptRecord, BRD, BRDResult, JudgeReport, Rating, Strategy,
)


@dataclass
class GraphBRDResult:
    """In-memory result of a graph-navigated BRD run, before persistence."""
    brd: BRD
    report: JudgeReport
    rating: Rating
    weighted_score: float
    attempts: int
    attempt_history: list[AttemptRecord]
    strategy: Strategy


def _log_timing(repo_id: str, n_prog: int, small: bool, model: str,
                runner, total_s: float) -> None:
    """Phase-0 instrumentation: print where a BRD run's wall-clock went — total,
    per-call breakdown (map/reduce/judge), and turn counts — so we can confirm the
    agentic loop (not fan-out/retries) is the bottleneck for small repos."""
    calls = getattr(runner, "calls", []) or []
    n_calls = len(calls)
    summed_ms = sum(c.get("wall_ms", 0) for c in calls)
    parallel_savings = max(0, summed_ms - int(total_s * 1000))
    logger.info(
        "BRD timing repo=%s programs=%d small=%s model=%s total_s=%.1f "
        "agent_calls=%d sum_call_ms=%d parallel_overlap_ms=%d",
        repo_id, n_prog, small, model, total_s, n_calls, summed_ms, parallel_savings)
    for c in calls:
        logger.info(
            "  - %s: wall=%dms turns=%s/%s api_ms=%s stop=%s%s",
            c.get("label"), c.get("wall_ms"), c.get("num_turns"),
            c.get("max_turns"), c.get("duration_api_ms"), c.get("stop_reason"),
            " HIT_TURN_CAP" if c.get("hit_turn_cap") else "")


def _draft_to_brd(draft, repo_id: str, model: str, strategy: Strategy) -> BRD:
    return BRD(sections=draft.sections, evidence_map=draft.evidence_map,
               repo_id=repo_id, model=model, strategy=strategy)


async def agenerate_brd_graph(deps: GraphDeps, *, runner: AgentRunner, model: str,
                              max_retries: int, max_turns: int,
                              max_subsystems: int, min_turns: int | None = None,
                              map_concurrency: int = 4,
                              advisor=None, advisor_max_uses: int = 3,
                              judge_model: str | None = None) -> GraphBRDResult:
    from cobol_modernizer.agent.brd_judge import ajudge
    from cobol_modernizer.agent.brd_orchestrator import agenerate_brd_draft

    # The judge is a tool-free scoring pass — run it on a cheap/fast model. Defaults
    # to the draft model only when a caller doesn't supply one (keeps tests stable).
    judge_model = judge_model or model
    attempts: list[AttemptRecord] = []
    best: tuple[BRD, JudgeReport] | None = None

    for attempt_no in range(1, max_retries + 2):
        draft, strategy = await agenerate_brd_draft(
            deps, runner=runner, model=model, max_turns=max_turns,
            max_subsystems=max_subsystems, min_turns=min_turns,
            map_concurrency=map_concurrency, advisor=advisor,
            advisor_max_uses=advisor_max_uses)
        brd = _draft_to_brd(draft, deps.repo_id, model, strategy)
        report = await ajudge(brd, deps, runner=runner, model=judge_model)
        attempts.append(AttemptRecord(attempt=attempt_no, rating=report.rating,
                                      weighted_score=report.weighted_score,
                                      feedback=report.feedback))
        if best is None or report.weighted_score > best[1].weighted_score:
            best = (brd, report)
        if report.rating == Rating.high:
            break

    assert best is not None
    final_brd, final_report = best
    return GraphBRDResult(brd=final_brd, report=final_report,
                          rating=final_report.rating,
                          weighted_score=final_report.weighted_score,
                          attempts=len(attempts), attempt_history=attempts,
                          strategy=final_brd.strategy)


def generate_brd_graph_sync(repo_id: str, *, client=None, repo_path=None,
                            max_retries: int | None = None, model: str | None = None,
                            max_turns: int | None = None,
                            max_subsystems: int | None = None,
                            storage: BRDStorage | None = None) -> BRDResult:
    """Sync entry point for CLI/API. Resolves deps + env defaults, runs the graph
    loop, renders + persists HTML, and returns the existing BRDResult so callers are
    unchanged. Mirrors the old generate_brd() contract."""
    if client is None:
        from cobol_modernizer.neo4j_client import Neo4jClient
        client = Neo4jClient()
    if repo_path is None:
        from cobol_modernizer.repo_manager import RepoManager
        repo = RepoManager(client).get(repo_id)
        if repo is None or not repo.get("local_path"):
            raise ValueError(f"Repo {repo_id} not registered or missing local_path")
        repo_path = repo["local_path"]
    model = model or resolve_model("brd")
    # Probe repo size once — it drives BOTH the strategy and the subsystem count.
    try:
        n_prog = client.run(
            "MATCH (p:CodeEntity {repo:$r}) WHERE p.kind='Program' "
            "RETURN count(p) AS c", r=repo_id)[0]["c"]
    except Exception:  # noqa: BLE001 — fall back to a sane default
        n_prog = 0
    # Small repos: a 3-program codebase has almost nothing to decompose, so the
    # map→reduce fan-out (multiple agents + a merge agent) and the retry loop are
    # pure overhead. Do ONE agent over the whole graph and a single attempt — far
    # faster, just as good. Override with BRD_SINGLE_SHOT_MAX_PROGRAMS / explicit args.
    small = 0 < n_prog <= int(os.getenv("BRD_SINGLE_SHOT_MAX_PROGRAMS", "4"))

    # Judge model is SIZE-TIERED. The judge is a tool-free scoring pass on the
    # serial critical path, so we don't pay Opus latency here. For small repos the
    # rating is purely advisory (max_retries=0 below), so Haiku — fast + cheap —
    # is plenty. For large repos the rating GATES a (multi-minute) retry, so it's
    # worth Sonnet's stronger judgement. An explicit BRD_JUDGE_MODEL / global pin
    # always wins. (Robust parsing in brd_judge tolerates a weaker model's format
    # drift, e.g. capitalized enum values, instead of crashing the run.)
    judge_pin = os.getenv("BRD_JUDGE_MODEL") or os.getenv(GLOBAL_ENV)
    judge_model = judge_pin or (HAIKU if small else SONNET)

    if max_retries is None:
        max_retries = 0 if small else int(os.getenv("BRD_MAX_RETRIES", "1"))
    # The per-subsystem turn budget is now ADAPTIVE (orchestrator scales it to each
    # cluster's size). These are the bounds: floor so even a tiny cluster can
    # explore + emit (the structured-output emission itself costs a turn under
    # claude-agent-sdk 0.2.87), cap so a huge cluster can't run away on cost.
    max_turns = int(os.getenv("BRD_AGENT_MAX_TURNS", "45")) if max_turns is None else max_turns
    min_turns = int(os.getenv("BRD_AGENT_MIN_TURNS", "14"))
    # Bound parallel map agents (cost / rate-limit control on large codebases).
    map_concurrency = int(os.getenv("BRD_MAP_CONCURRENCY", "4"))
    # Subsystem count: 1 (single-shot, no reduce) for small repos; otherwise scale
    # to the codebase (~one cluster per program + a little), bounded by
    # BRD_MAX_SUBSYSTEMS; overflow folds into a 'misc' cluster.
    if max_subsystems is None:
        cap = int(os.getenv("BRD_MAX_SUBSYSTEMS", "24"))
        max_subsystems = 1 if small else max(4, min(cap, n_prog + 2))

    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.harness import SdkAgentRunner
    deps = GraphDeps(client=client, repo_id=repo_id, repo_path=Path(repo_path))
    runner = SdkAgentRunner()
    advisor = None
    advisor_max_uses = int(os.getenv("ADVISOR_MAX_USES", "3"))
    if os.getenv("BRD_ADVISOR_ENABLED", "").lower() in ("1", "true", "yes"):
        from cobol_modernizer.agent.advisor import AnthropicAdvisor
        advisor = AnthropicAdvisor()
    wall_start = time.monotonic()
    result = asyncio.run(agenerate_brd_graph(
        deps, runner=runner, model=model, max_retries=max_retries,
        max_turns=max_turns, max_subsystems=max_subsystems, min_turns=min_turns,
        map_concurrency=map_concurrency,
        advisor=advisor, advisor_max_uses=advisor_max_uses,
        judge_model=judge_model))
    _log_timing(repo_id, n_prog, small, model, runner, time.monotonic() - wall_start)

    html = render_html(result.brd)
    if storage is None:
        storage = BRDStorage(client)
    return storage.save(
        repo_id=repo_id, html=html, judge_report=result.report,
        attempt_history=result.attempt_history, model=model,
        strategy=result.strategy,
        token_usage=dict(runner.token_usage),
    )
