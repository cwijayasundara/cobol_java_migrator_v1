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
