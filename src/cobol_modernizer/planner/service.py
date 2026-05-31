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
    dag = derive_dependencies(stories, seam_candidates, repo_id=repo_id)

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
