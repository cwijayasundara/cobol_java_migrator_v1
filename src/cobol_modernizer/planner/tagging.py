"""Tag planner stories with the bounded context + topology decided by the domain-design
stage. Pure + optional: stories whose seam isn't in any context are left untagged."""
from __future__ import annotations

from typing import Any

from cobol_modernizer.planner.schema import Story


def tag_stories_with_contexts(stories: list[Story], contexts: list[dict[str, Any]]) -> list[Story]:
    by_program: dict[str, dict] = {}
    for c in contexts:
        for p in c.get("member_programs", []):
            by_program[p] = c
    for s in stories:
        ctx = by_program.get(s.seam)
        if ctx:
            s.context = ctx.get("name")
            topo = ctx.get("topology") or {}
            s.topology = topo.get("deployment") if isinstance(topo, dict) else None
    return stories
