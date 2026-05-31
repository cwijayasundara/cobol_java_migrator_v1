from __future__ import annotations

from cobol_modernizer.planner.schema import Story, StoryDAG


def stories_from_seam_set(seam_candidates: list[dict], *, repo_id: str) -> list[Story]:
    """One story per seam, id = S{rank}, highest-scoring seam first (S1)."""
    ordered = sorted(seam_candidates,
                     key=lambda c: c["score"]["weighted"], reverse=True)
    return [Story(id=f"S{i+1}", title=f"Migrate {c['program']}",
                  seam=c["program"], evidence_map={"seam": [c["program"]]})
            for i, c in enumerate(ordered)]


def derive_dependencies(stories: list[Story], seam_candidates: list[dict],
                        *, repo_id: str = "") -> StoryDAG:
    """A writer story depends on the (lower-risk) reader stories of any resource it
    writes that another seam reads — read paths land before write paths (strangler-fig,
    reader-before-writer). Deterministic; acyclic because reader.score > writer.score
    and edges only point reader -> writer.

    repo_id is generic and defaults to ""; the service layer rebuilds the DAG with the
    real repo id (kept out of this layer to honor the no-hardcoded-repo constraint)."""
    by_program = {c["program"]: c for c in seam_candidates}
    story_for = {s.seam: s for s in stories}
    for s in stories:
        cand = by_program[s.seam]
        deps: set[str] = set()
        for resource in cand.get("writes", []):
            for other in seam_candidates:
                if other["program"] != s.seam and resource in other.get("reads", []):
                    deps.add(story_for[other["program"]].id)
        s.depends_on = sorted(deps)
    return StoryDAG(repo_id=repo_id, stories=stories)
