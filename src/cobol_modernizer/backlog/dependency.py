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
