from __future__ import annotations

import asyncio
import json
import logging
import os
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
from cobol_modernizer.enrichment.refs import relevant_refs

logger = logging.getLogger(__name__)


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


async def _generate_backlog_oneshot(*, runner, model: str, timeout_s: float,
                                    brd_sections: list[dict], relevant_refs: list[str],
                                    known_requirement_ids: list[str],
                                    max_turns: int = 6) -> EnrichmentResult:
    """The preserved LEGACY single-call path: epics + stories in ONE structured call
    over BACKLOG_SCHEMA. The size router (`generate_backlog_result`) reaches this for
    small inputs (or when BACKLOG_GEN_MODE=oneshot). `relevant_refs` is the
    evidence-map-derived whole-BRD relevant set (NON-empty, never 0) — inlined into the
    prompt. Returns the typed result so a gating caller can surface the concrete
    failure cause (timeout / turn cap / api error) instead of a generic 'no output'."""
    prompt = build_backlog_prompt(brd_sections=brd_sections, known_refs=relevant_refs,
                                  known_requirement_ids=known_requirement_ids)
    return await run_batched_result(runner=runner, system=BACKLOG_SYSTEM, prompt=prompt,
                                    schema=BACKLOG_SCHEMA, model=model, timeout_s=timeout_s,
                                    label="backlog-generate", max_turns=max_turns)


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
                         known_requirement_ids: list[str],
                         attempts: int = 1, escalate: bool = True) -> EnrichmentResult:
    """MAP unit 1: a single bounded structured call that emits the EPIC layer only.
    `relevant_refs` is already the lossless relevant set (computed upstream); it is
    inlined as-is — NOT the whole graph, and never truncated. `attempts`/`escalate`
    are threaded into the shared `run_batched_result` primitive so a timed-out /
    turn-capped epics unit is retried with an escalated budget rather than dying on
    one timeout. Returns the typed result so a gating caller can surface the concrete
    failure cause."""
    prompt = build_epics_prompt(brd_sections=brd_sections, relevant_refs=relevant_refs,
                                known_requirement_ids=known_requirement_ids)
    return await run_batched_result(
        runner=runner, system=EPICS_SYSTEM, prompt=prompt, schema=EPICS_SCHEMA,
        model=model, timeout_s=timeout_s, label="backlog-epics", max_turns=max_turns,
        attempts=attempts, escalate=escalate)


async def generate_stories_for_epic(*, runner, model: str, timeout_s: float,
                                    max_turns: int, epic: dict,
                                    brd_sections_for_epic: list[dict],
                                    relevant_refs: list[str],
                                    known_requirement_ids: list[str],
                                    attempts: int = 1,
                                    escalate: bool = True) -> EnrichmentResult:
    """MAP unit 2: a single bounded structured call that emits user stories +
    acceptance criteria for ONE epic. The prompt is scoped to this epic alone (no
    other epics' content) and inlines this epic's FULL relevant refs — `relevant_refs`
    is computed by the CALLER (Task 5) as relevant_refs(brd_sections_for_epic,
    known_refs) and inlined here without truncation. `attempts`/`escalate` are threaded
    into the shared `run_batched_result` primitive so a timed-out / turn-capped story
    unit is retried with an escalated budget — a unit no longer dies on one timeout.
    Returns the typed result."""
    prompt = build_stories_prompt(
        epic=epic, brd_sections_for_epic=brd_sections_for_epic,
        relevant_refs=relevant_refs, known_requirement_ids=known_requirement_ids)
    return await run_batched_result(
        runner=runner, system=STORIES_SYSTEM, prompt=prompt, schema=STORIES_SCHEMA,
        model=model, timeout_s=timeout_s, label="backlog-stories", max_turns=max_turns,
        attempts=attempts, escalate=escalate)


# --- Orchestrator: size router -> fan-out -> merge -> completeness loop -----
# Reads top-to-bottom: route by input size; for the decomposed path generate the
# epic layer, fan out per-epic story calls (bounded by a semaphore, NOT capped),
# merge into a parse-compatible {epics, stories}, then a Loop-Until-Done guard
# tops up any BRD requirement no produced story covers. HARD CONSTRAINT: no caps /
# truncation anywhere; a requirement is dropped ONLY after the loop genuinely
# cannot cover it (no progress / max rounds).

COVERAGE_TOPUP_EPIC_ID = "EPIC-COVERAGE-TOPUP"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _requirement_ids_of_sections(brd_sections: list[dict]) -> list[str]:
    """All BRD requirement ids in `brd_sections`, first-seen order, deduped."""
    out: list[str] = []
    seen: set[str] = set()
    for sec in brd_sections:
        if not isinstance(sec, dict):
            continue
        for req in sec.get("requirements", []) or []:
            rid = req.get("id") if isinstance(req, dict) else None
            if rid and str(rid) not in seen:
                seen.add(str(rid))
                out.append(str(rid))
    return out


def _sections_for_requirements(brd_sections: list[dict], req_ids: set[str]) -> list[dict]:
    """The BRD subset relevant to `req_ids`: every section that declares at least one
    in-scope requirement, with its `requirements` list filtered to the in-scope ones
    (so an epic's per-epic call only ever sees the requirements it owns — no leakage,
    no truncation of what IS in scope)."""
    subset: list[dict] = []
    for sec in brd_sections:
        if not isinstance(sec, dict):
            continue
        kept = [req for req in sec.get("requirements", []) or []
                if isinstance(req, dict) and str(req.get("id", "")) in req_ids]
        if kept:
            sec_copy = dict(sec)
            sec_copy["requirements"] = kept
            subset.append(sec_copy)
    return subset


def _covered_requirements(stories: list[dict]) -> set[str]:
    """The set of BRD requirement ids that at least one produced story cites."""
    covered: set[str] = set()
    for story in stories:
        for rid in story.get("brd_requirement_ids", []) or []:
            if rid:
                covered.add(str(rid))
    return covered


def _decompose(brd_sections: list[dict], known_requirement_ids: list[str]) -> bool:
    """Classify-and-Act size router. Proxy = number of BRD requirements
    (`len(known_requirement_ids)`): it is the count of work items the backlog must
    cover, the thing decomposition parallelizes. BACKLOG_GEN_MODE forces the path;
    in `auto`, decompose at/above BACKLOG_DECOMPOSE_MIN_EPICS (default 3)."""
    mode = os.environ.get("BACKLOG_GEN_MODE", "auto").strip().lower()
    if mode == "decomposed":
        return True
    if mode == "oneshot":
        return False
    min_epics = _env_int("BACKLOG_DECOMPOSE_MIN_EPICS", 3)
    proxy = len(known_requirement_ids) or len(brd_sections)
    return proxy >= min_epics


def _scope_epic_refs(req_ids: set[str], brd_evidence_map: dict[str, list[str]],
                     known_refs: list[str], brd_relevant: list[str]) -> list[str]:
    """The evidence-map-derived refs for the requirements `req_ids` cover, falling
    back to the whole-BRD relevant set when those requirements have no grounding.
    NEVER returns empty (the no-regression / never-inline-0 guarantee): per-req
    evidence_map entries, else `brd_relevant` (itself a non-empty fallback to all
    known_refs upstream). No cap / truncation — relevant_refs is lossless."""
    evidence_subset = {r: brd_evidence_map.get(r, []) for r in req_ids}
    return relevant_refs(evidence_subset, known_refs) or list(brd_relevant)


async def _generate_stories_round(*, runner, model: str, brd_sections: list[dict],
                                  known_refs: list[str],
                                  known_requirement_ids: list[str],
                                  brd_evidence_map: dict[str, list[str]],
                                  brd_relevant: list[str],
                                  units: list[tuple[dict, set[str]]],
                                  story_timeout_s: float, story_max_turns: int,
                                  semaphore: asyncio.Semaphore,
                                  unit_attempts: int = 1) -> list[dict]:
    """Fan out one round of per-epic stories calls under `semaphore` (bounds parallel
    IN-FLIGHT calls, NOT story count). Each unit is (epic, req_ids_to_cover): the epic
    plus the subset of its requirements this round should produce stories for. The
    per-epic refs are scoped by the BRD `evidence_map` (the entities the BRD grounded
    those requirements to), falling back to `brd_relevant` so a unit is NEVER given 0
    refs. A unit whose call returns not-ok contributes no stories (logged) but never
    fails the round — partial failure is tolerated."""
    async def _one(epic: dict, req_ids: set[str]) -> list[dict]:
        sections_for_epic = _sections_for_requirements(brd_sections, req_ids)
        if not sections_for_epic:
            # The epic cites no (resolvable) requirement ids — rather than hand the
            # model an empty "sections this epic cites" block while still listing all
            # known requirement ids (telling it to cite reqs it sees no text for),
            # fall back to the FULL BRD sections so it has real context to ground on.
            sections_for_epic = brd_sections
        refs = _scope_epic_refs(req_ids, brd_evidence_map, known_refs, brd_relevant)
        async with semaphore:
            res = await generate_stories_for_epic(
                runner=runner, model=model, timeout_s=story_timeout_s,
                max_turns=story_max_turns, epic=epic,
                brd_sections_for_epic=sections_for_epic, relevant_refs=refs,
                known_requirement_ids=known_requirement_ids,
                attempts=unit_attempts, escalate=True)
        if not res.ok:
            logger.warning("backlog: stories call for epic %s failed (%s) — no stories "
                           "from this epic this round", epic.get("id"), res.cause)
            return []
        return [s for s in res.payload.get("stories", []) if isinstance(s, dict)]

    results = await asyncio.gather(*[_one(epic, req_ids) for epic, req_ids in units])
    merged: list[dict] = []
    for stories in results:
        merged.extend(stories)
    return merged


async def generate_backlog_result(*, runner, model: str, timeout_s: float,
                                  brd_sections: list[dict], known_refs: list[str],
                                  known_requirement_ids: list[str],
                                  brd_evidence_map: dict[str, list[str]] | None = None,
                                  max_turns: int = 6) -> EnrichmentResult:
    """Size-routed backlog generation returning the typed result.

    Graph-ref scoping is driven by the BRD `evidence_map` (`requirement_id ->
    [qualified_names]`, the entities the BRD already grounded each requirement to),
    NOT by the BRD section text (which carries no refs). The whole-BRD relevant set
    (`brd_relevant`) is the evidence-map-derived refs, falling back to ALL `known_refs`
    when the evidence_map is empty/legacy — so the prompt NEVER inlines 0 refs (the
    no-regression guarantee). Per-epic, refs are scoped to that epic's requirements'
    evidence_map entries, falling back to `brd_relevant`.

    auto/oneshot small input -> preserved one-shot path (inlines `brd_relevant`).
    Decomposed path:
      1. generate the EPIC layer (inlines `brd_relevant`; fail loud if it fails /
         yields no epics),
      2. fan out per-epic stories (bounded concurrency, partial failure tolerated),
      3. merge into a parse-compatible {epics, stories},
      4. Loop-Until-Done (UNCAPPED): top up any uncovered BRD requirement until full
         coverage OR BACKLOG_NO_PROGRESS_ROUNDS (default 2) CONSECUTIVE no-progress
         rounds. BACKLOG_MAX_ROUNDS (default 100) is a high SAFETY backstop only — NOT
         the normal stop — so a slow-but-progressing repo keeps looping past the old
         hard cap of 3 instead of dying mid-coverage at the 300s cliff.
    Per-unit retry: each epics / per-epic-stories MAP call threads
    `attempts=BACKLOG_UNIT_ATTEMPTS` (default 2, escalate=True) into the shared
    primitive, so a unit that times out / hits its turn cap is re-issued with an
    escalated budget rather than dying on one timeout.
    Never caps/truncates; never drops a requirement to finish (only the loop's
    no-progress/safety-bound terminus drops a genuinely uncoverable one)."""
    brd_evidence_map = brd_evidence_map or {}
    # Whole-BRD relevant: the BRD-grounded refs, or ALL known_refs if the evidence_map
    # is empty/legacy. NEVER empty -> the epics call and the per-epic fallback never
    # inline 0 refs. Lossless (no cap).
    brd_relevant = relevant_refs(brd_evidence_map, known_refs) or list(known_refs)

    if not _decompose(brd_sections, known_requirement_ids):
        return await _generate_backlog_oneshot(
            runner=runner, model=model, timeout_s=timeout_s, brd_sections=brd_sections,
            relevant_refs=brd_relevant, known_requirement_ids=known_requirement_ids,
            max_turns=max_turns)

    epic_timeout_s = _env_float("BACKLOG_EPIC_TIMEOUT_S", 120.0)
    story_timeout_s = _env_float("BACKLOG_STORY_TIMEOUT_S", 120.0)
    story_max_turns = _env_int("BACKLOG_STORY_MAX_TURNS", 6)
    max_concurrency = max(1, _env_int("BACKLOG_MAX_CONCURRENCY", 4))
    # The completeness loop is UNCAPPED in practice: its PRIMARY exit is full coverage
    # OR BACKLOG_NO_PROGRESS_ROUNDS consecutive no-progress rounds. BACKLOG_MAX_ROUNDS
    # is a large SAFETY backstop (default 100), not the normal stop — so a
    # slow-but-progressing repo keeps looping past the old hard cap of 3.
    max_rounds = max(1, _env_int("BACKLOG_MAX_ROUNDS", 100))
    no_progress_limit = max(1, _env_int("BACKLOG_NO_PROGRESS_ROUNDS", 2))
    # Per-unit retry-with-escalation: a unit no longer dies on one timeout/turn-cap.
    unit_attempts = max(1, _env_int("BACKLOG_UNIT_ATTEMPTS", 2))
    semaphore = asyncio.Semaphore(max_concurrency)

    # 1. EPIC layer (whole-BRD evidence-map relevant refs) — fail loud on failure / empty.
    epics_res = await generate_epics(
        runner=runner, model=model, timeout_s=epic_timeout_s, max_turns=max_turns,
        brd_sections=brd_sections, relevant_refs=brd_relevant,
        known_requirement_ids=known_requirement_ids,
        attempts=unit_attempts, escalate=True)
    epics = [e for e in epics_res.payload.get("epics", []) if isinstance(e, dict)]
    if not epics_res.ok or not epics:
        cause = epics_res.cause or "no epics"
        return EnrichmentResult(payload={}, ok=False,
                                cause=f"epics generation failed: {cause}")

    # 2. Fan out per-epic stories (each epic covers ALL its requirements).
    first_units = [(epic, set(epic.get("brd_requirement_ids", []) or []))
                   for epic in epics]
    all_stories = await _generate_stories_round(
        runner=runner, model=model, brd_sections=brd_sections, known_refs=known_refs,
        known_requirement_ids=known_requirement_ids,
        brd_evidence_map=brd_evidence_map, brd_relevant=brd_relevant,
        units=first_units, story_timeout_s=story_timeout_s,
        story_max_turns=story_max_turns, semaphore=semaphore,
        unit_attempts=unit_attempts)

    # Fail loud if NO epic produced a story.
    if not all_stories:
        return EnrichmentResult(payload={}, ok=False,
                                cause="stories generation failed: no stories produced "
                                      "for any epic")

    # 3+4. Loop-Until-Done completeness guard (UNCAPPED).
    # PRIMARY exit: full coverage OR `no_progress_limit` CONSECUTIVE no-progress
    # top-up rounds (a progress round resets the streak). `max_rounds` is a high
    # SAFETY backstop bounding the TOTAL top-up rounds so a degenerate fixture that
    # always reports progress still terminates — it is not the normal stop.
    all_req_ids = set(known_requirement_ids) or set(
        _requirement_ids_of_sections(brd_sections))
    epics_by_id = {str(e.get("id", "")): e for e in epics}
    topup_round = 0  # number of top-up rounds run (safety bound counter)
    no_progress_streak = 0  # consecutive top-up rounds that covered nothing new
    while topup_round < max_rounds:
        covered = _covered_requirements(all_stories)
        uncovered = all_req_ids - covered
        if not uncovered:
            break
        # Map each uncovered req to the epic that OWNS it; orphans go to a
        # synthetic catch-all epic (created once, deterministic id).
        units: dict[str, tuple[dict, set[str]]] = {}
        orphans: set[str] = set()
        for rid in uncovered:
            owner = next((e for e in epics
                          if rid in (e.get("brd_requirement_ids") or [])), None)
            if owner is None:
                orphans.add(rid)
                continue
            eid = str(owner.get("id", ""))
            units.setdefault(eid, (owner, set()))[1].add(rid)
        if orphans:
            topup = epics_by_id.get(COVERAGE_TOPUP_EPIC_ID)
            if topup is None:
                topup = {"id": COVERAGE_TOPUP_EPIC_ID,
                         "title": "Coverage top-up",
                         "outcome": "Cover BRD requirements not owned by any epic.",
                         "brd_requirement_ids": sorted(orphans),
                         "evidence_refs": []}
                epics.append(topup)
                epics_by_id[COVERAGE_TOPUP_EPIC_ID] = topup
            else:
                topup["brd_requirement_ids"] = sorted(
                    set(topup.get("brd_requirement_ids", [])) | orphans)
            units[COVERAGE_TOPUP_EPIC_ID] = (topup, set(orphans))

        new_stories = await _generate_stories_round(
            runner=runner, model=model, brd_sections=brd_sections, known_refs=known_refs,
            known_requirement_ids=known_requirement_ids,
            brd_evidence_map=brd_evidence_map, brd_relevant=brd_relevant,
            units=list(units.values()), story_timeout_s=story_timeout_s,
            story_max_turns=story_max_turns, semaphore=semaphore,
            unit_attempts=unit_attempts)
        topup_round += 1
        newly_covered = _covered_requirements(new_stories) & uncovered
        all_stories.extend(new_stories)
        if newly_covered:
            no_progress_streak = 0  # progress — reset the no-progress streak
        else:
            no_progress_streak += 1
        logger.info("backlog: completeness top-up round %d — %d uncovered before, "
                    "%d newly covered (no-progress streak %d/%d)", topup_round,
                    len(uncovered), len(newly_covered), no_progress_streak,
                    no_progress_limit)
        if no_progress_streak >= no_progress_limit:
            # `no_progress_limit` consecutive no-progress rounds — the rest is
            # genuinely uncoverable; stop (PRIMARY exit, not the safety backstop).
            break

    merged = {"epics": epics, "stories": all_stories}
    return EnrichmentResult(payload=merged, ok=True, cause=None)


async def generate_backlog_payload(*, runner, model: str, timeout_s: float,
                                   brd_sections: list[dict], known_refs: list[str],
                                   known_requirement_ids: list[str],
                                   brd_evidence_map: dict[str, list[str]] | None = None,
                                   max_turns: int = 6) -> dict:
    # max_turns default 6 (not run_batched's 2): emitting the structured-output result
    # consumes a turn under claude-agent-sdk 0.2.87, and a real backlog needs a few
    # reasoning turns before it; 2 risks hitting the turn cap and returning {}.
    # Override via BACKLOG_MAX_TURNS. Returns the merged raw dict, or {} on failure
    # (Task 6 will switch run_backlog to consume the typed result directly).
    result = await generate_backlog_result(
        runner=runner, model=model, timeout_s=timeout_s, brd_sections=brd_sections,
        known_refs=known_refs, known_requirement_ids=known_requirement_ids,
        brd_evidence_map=brd_evidence_map, max_turns=max_turns)
    return result.payload
