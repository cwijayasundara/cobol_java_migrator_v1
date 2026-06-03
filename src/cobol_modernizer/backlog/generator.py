from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.backlog.schema import (
    AcceptanceCriterion,
    Backlog,
    Epic,
    UserStory,
)
from cobol_modernizer.enrichment.base import (
    EnrichmentResult,
    run_batched_result,
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


BACKLOG_SCHEMA = {
    "type": "object",
    "properties": {
        "epics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "title": {"type": "string"},
                    "outcome": {"type": "string"},
                    "brd_requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "story_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "outcome"],
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "epic_id": {"type": "string"},
                    "title": {"type": "string"}, "actor": {"type": "string"},
                    "narrative": {"type": "string"},
                    "brd_requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"}, "statement": {"type": "string"},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["id", "statement"],
                        },
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "epic_id", "title", "actor", "narrative", "acceptance_criteria"],
            },
        },
    },
    "required": ["epics", "stories"],
}


# --- Split schemas (Fan-Out-and-Synthesize) -------------------------------
# The legacy BACKLOG_SCHEMA above produces epics + stories in ONE call (kept for
# the size-routed one-shot path). The two schemas below split that call so a large
# repo's backlog can be generated as: epics-only, then stories+ACs per-epic in
# parallel. They are derived from BACKLOG_SCHEMA so the merged {epics, stories}
# they produce is byte-for-byte what `parse_backlog_payload` already consumes.

EPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "epics": BACKLOG_SCHEMA["properties"]["epics"],
    },
    "required": ["epics"],
}

STORIES_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": BACKLOG_SCHEMA["properties"]["stories"],
    },
    "required": ["stories"],
}


EPICS_SYSTEM = (
    "You convert a graph-grounded BRD into the EPIC layer of an implementation "
    "backlog. Produce business epics (capability-level outcomes), NOT user stories, "
    "acceptance criteria, or technical migration tasks. Every epic must be grounded "
    "in the BRD requirements and cite BRD requirement ids and graph evidence refs. "
    "Do not invent requirement ids or graph refs."
)


STORIES_SYSTEM = (
    "You convert a graph-grounded BRD into the user-story layer of an implementation "
    "backlog, scoped to a SINGLE epic. Produce business user stories and acceptance "
    "criteria for that epic only — not technical migration tasks, not other epics. "
    "Every story must set epic_id to the given epic, cite BRD requirement ids and "
    "graph evidence refs, and include acceptance criteria that can become tests. "
    "Do not invent requirement ids or graph refs."
)


def build_backlog_prompt(*, brd_sections: list[dict], known_refs: list[str],
                         known_requirement_ids: list[str]) -> str:
    return (
        "## BRD requirement sections\n```json\n" + json.dumps(brd_sections) + "\n```\n"
        "## Known BRD requirement ids (cite only these)\n" + ", ".join(known_requirement_ids) + "\n"
        "## Known graph evidence refs (cite only these)\n```json\n"
        + json.dumps(known_refs) + "\n```\n"
        "Produce epics and user stories. Every story MUST cite at least one BRD "
        "requirement id and at least one graph evidence ref, and MUST include "
        "acceptance criteria phrased as testable Given/When/Then statements."
    )


async def generate_backlog_result(*, runner, model: str, timeout_s: float,
                                  brd_sections: list[dict], known_refs: list[str],
                                  known_requirement_ids: list[str],
                                  max_turns: int = 6) -> EnrichmentResult:
    """Typed-result variant of `generate_backlog_payload`: returns the
    `EnrichmentResult` so a GATING caller can surface the concrete failure cause
    (timeout / turn cap / api error) instead of a generic 'no output'."""
    prompt = build_backlog_prompt(brd_sections=brd_sections, known_refs=known_refs,
                                  known_requirement_ids=known_requirement_ids)
    return await run_batched_result(runner=runner, system=BACKLOG_SYSTEM, prompt=prompt,
                                    schema=BACKLOG_SCHEMA, model=model, timeout_s=timeout_s,
                                    label="backlog-generate", max_turns=max_turns)


async def generate_backlog_payload(*, runner, model: str, timeout_s: float,
                                   brd_sections: list[dict], known_refs: list[str],
                                   known_requirement_ids: list[str],
                                   max_turns: int = 6) -> dict:
    # max_turns default 6 (not run_batched's 2): emitting the structured-output result
    # consumes a turn under claude-agent-sdk 0.2.87, and a real backlog needs a few
    # reasoning turns before it; 2 risks hitting the turn cap and returning {}.
    # Override via BACKLOG_MAX_TURNS.
    result = await generate_backlog_result(
        runner=runner, model=model, timeout_s=timeout_s, brd_sections=brd_sections,
        known_refs=known_refs, known_requirement_ids=known_requirement_ids,
        max_turns=max_turns)
    return result.payload


# --- Fan-Out-and-Synthesize MAP units -------------------------------------
# Two small, single-call bounded units. The orchestration that gathers them
# (epics -> parallel per-epic stories -> merge -> completeness loop) is Task 5.


def build_epics_prompt(*, brd_sections: list[dict], relevant_refs: list[str],
                       known_requirement_ids: list[str]) -> str:
    """Prompt for the epics-only MAP call. Inlines the BRD requirement sections,
    the citable requirement ids, and the (already lossless-relevant) graph refs —
    NOT the whole graph. Asks for epics only."""
    return (
        "## BRD requirement sections\n```json\n" + json.dumps(brd_sections) + "\n```\n"
        "## Known BRD requirement ids (cite only these)\n"
        + ", ".join(known_requirement_ids) + "\n"
        "## Known graph evidence refs (cite only these)\n```json\n"
        + json.dumps(relevant_refs) + "\n```\n"
        "Produce the EPIC layer only: business epics (capability-level outcomes) "
        "grounded in the BRD requirements above. Do NOT emit user stories or "
        "acceptance criteria. Every epic MUST cite at least one BRD requirement id "
        "and at least one graph evidence ref."
    )


def build_stories_prompt(*, epic: dict, brd_sections_for_epic: list[dict],
                         relevant_refs: list[str],
                         known_requirement_ids: list[str]) -> str:
    """Prompt for the per-epic stories+ACs MAP call. Scoped to ONE epic: only this
    epic's id/title/outcome and the BRD requirement sections it cites are inlined
    (so other epics' content never leaks in), plus this epic's FULL relevant refs
    (no truncation). Asks for user stories + acceptance criteria for THIS epic."""
    epic_id = str(epic.get("id", ""))
    epic_scope = {
        "id": epic_id,
        "title": str(epic.get("title", "")),
        "outcome": str(epic.get("outcome", "")),
    }
    return (
        "## Epic (generate stories for THIS epic only)\n```json\n"
        + json.dumps(epic_scope) + "\n```\n"
        "## BRD requirement sections this epic cites\n```json\n"
        + json.dumps(brd_sections_for_epic) + "\n```\n"
        "## Known BRD requirement ids (cite only these)\n"
        + ", ".join(known_requirement_ids) + "\n"
        "## Known graph evidence refs (cite only these)\n```json\n"
        + json.dumps(relevant_refs) + "\n```\n"
        f"Produce user stories and acceptance criteria for epic {epic_id} ONLY. "
        f"Every emitted story MUST set epic_id to \"{epic_id}\". Every story MUST "
        "cite at least one BRD requirement id and at least one graph evidence ref. "
        "Every story MUST include acceptance criteria phrased as testable "
        "Given/When/Then statements, each carrying a unique AC id and citing the "
        "graph evidence refs it verifies."
    )


async def generate_epics(*, runner, model: str, timeout_s: float, max_turns: int,
                         brd_sections: list[dict], relevant_refs: list[str],
                         known_requirement_ids: list[str]) -> EnrichmentResult:
    """MAP unit 1: a single bounded structured call that emits the EPIC layer only.
    `relevant_refs` is already the lossless relevant set (computed upstream); it is
    inlined as-is — NOT the whole graph, and never truncated. Returns the typed
    result so a gating caller can surface the concrete failure cause."""
    prompt = build_epics_prompt(brd_sections=brd_sections, relevant_refs=relevant_refs,
                                known_requirement_ids=known_requirement_ids)
    return await run_batched_result(
        runner=runner, system=EPICS_SYSTEM, prompt=prompt, schema=EPICS_SCHEMA,
        model=model, timeout_s=timeout_s, label="backlog-epics", max_turns=max_turns)


async def generate_stories_for_epic(*, runner, model: str, timeout_s: float,
                                    max_turns: int, epic: dict,
                                    brd_sections_for_epic: list[dict],
                                    relevant_refs: list[str],
                                    known_requirement_ids: list[str]) -> EnrichmentResult:
    """MAP unit 2: a single bounded structured call that emits user stories +
    acceptance criteria for ONE epic. The prompt is scoped to this epic alone (no
    other epics' content) and inlines this epic's FULL relevant refs — `relevant_refs`
    is computed by the CALLER (Task 5) as relevant_refs(brd_sections_for_epic,
    known_refs) and inlined here without truncation. Returns the typed result."""
    prompt = build_stories_prompt(
        epic=epic, brd_sections_for_epic=brd_sections_for_epic,
        relevant_refs=relevant_refs, known_requirement_ids=known_requirement_ids)
    return await run_batched_result(
        runner=runner, system=STORIES_SYSTEM, prompt=prompt, schema=STORIES_SCHEMA,
        model=model, timeout_s=timeout_s, label="backlog-stories", max_turns=max_turns)
