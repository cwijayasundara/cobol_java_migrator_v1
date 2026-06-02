"""Story-sliced codegen plan (Task 1 of the story-sliced codegen engine).

Transforms already-loaded spec objects (backlog + domain design + technical
design) into an ordered, dependency-respecting work-list that downstream tasks
iterate one story at a time. Each `StoryCodegenItem` carries everything a worker
needs to build ONE story without re-deriving it: the story id, its mapped
bounded context + service, acceptance-criterion ids, deduped COBOL evidence
refs, the story ids it follows, and a mutable status.

This module is PURE/deterministic: no LLM, no Neo4j, no I/O. Ordering uses a
stable topological sort over `UserStory.depends_on`. We do NOT call
`derive_story_dependencies` here: that function's job is to *populate*
`depends_on` from seam read/write overlaps (and it needs `seam_candidates`,
which the planner is not given). By the time a backlog reaches the planner its
`depends_on` edges are already set, so the planner only needs to ORDER over
them — hence the local topological sort. `BacklogDAG` is reused conceptually as
the typed container of ordered stories, but the planner returns the richer
`StoryCodegenPlan`.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from cobol_modernizer.backlog.schema import Backlog, UserStory
from cobol_modernizer.domain.schema import DomainDesign
from cobol_modernizer.technical_design.schema import (
    TechnicalDesign,
    TechnicalService,
)


class StoryCodegenStatus(str, Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    generated_unverified = "generated-unverified"
    blocked = "blocked"


class StoryCodegenItem(BaseModel):
    story_id: str
    bounded_context: str = ""
    service_name: str = ""
    acceptance_criteria_ids: list[str] = Field(default_factory=list)
    cobol_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    status: StoryCodegenStatus = StoryCodegenStatus.pending


class StoryCodegenPlan(BaseModel):
    repo_slug: str
    version: int = 0
    items: list[StoryCodegenItem] = Field(default_factory=list)


def _dedupe(refs: list[str]) -> list[str]:
    """Order-preserving dedupe, dropping falsy entries."""
    return list(dict.fromkeys(r for r in refs if r))


def _ordered_stories(stories: list[UserStory]) -> list[UserStory]:
    """Stable topological order over `depends_on`: a story appears after every
    story it depends on. Ties (and edges to unknown/missing story ids) preserve
    the input order. Cycles cannot starve the output — any story still unemitted
    once no further progress is possible is appended in input order."""
    by_id = {s.id: s for s in stories}
    emitted: set[str] = set()
    order: list[UserStory] = []

    remaining = list(stories)
    while remaining:
        progressed = False
        still: list[UserStory] = []
        for story in remaining:
            deps = [d for d in story.depends_on if d in by_id]
            if all(d in emitted for d in deps):
                order.append(story)
                emitted.add(story.id)
                progressed = True
            else:
                still.append(story)
        remaining = still
        if not progressed:
            # Cycle or self-reference among the rest: emit in input order to
            # guarantee termination and that every story is present.
            for story in remaining:
                order.append(story)
                emitted.add(story.id)
            break
    return order


def _service_by_story_id(
    services: list[TechnicalService],
) -> dict[str, TechnicalService]:
    mapping: dict[str, TechnicalService] = {}
    for svc in services:
        for sid in svc.story_ids:
            mapping.setdefault(sid, svc)
    return mapping


def _service_by_context(
    services: list[TechnicalService],
) -> dict[str, TechnicalService]:
    mapping: dict[str, TechnicalService] = {}
    for svc in services:
        mapping.setdefault(svc.bounded_context, svc)
    return mapping


def _domain_refs_for_context(domain: DomainDesign, context: str) -> list[str]:
    """Member programs + cobol_mapping.cobol_ref for the named bounded context,
    order-preserving (member programs first, then mappings)."""
    refs: list[str] = []
    for ctx in domain.contexts:
        if ctx.name == context:
            refs.extend(ctx.member_programs)
    for design in domain.designs:
        if design.context == context:
            for m in design.cobol_mapping:
                if m.cobol_ref:
                    refs.append(m.cobol_ref)
    return refs


def build_story_codegen_plan(
    backlog: Backlog,
    domain_design: DomainDesign,
    technical_design: TechnicalDesign,
) -> StoryCodegenPlan:
    """Build an ordered, dependency-respecting story codegen plan.

    Mapping rules:
    - story -> service via the explicit `TechnicalService.story_ids` link. Fall
      back to `UserStory.context == TechnicalService.bounded_context` ONLY when
      no service anywhere declares `story_ids`.
    - acceptance_criteria_ids from `UserStory.acceptance_criteria[].id`.
    - cobol_refs from, in order: the story's `evidence_refs`, the mapped
      context's domain member_programs + cobol_mapping.cobol_ref, then the
      mapped service's `evidence_refs`. Deduped, order-preserving.
    - a story with no service/context mapping is `blocked`; otherwise `pending`.
    """
    services = technical_design.services
    by_story_id = _service_by_story_id(services)
    use_context_fallback = not by_story_id  # no story_ids declared anywhere
    by_context = _service_by_context(services) if use_context_fallback else {}

    items: list[StoryCodegenItem] = []
    for story in _ordered_stories(backlog.stories):
        service = by_story_id.get(story.id)
        if service is None and use_context_fallback and story.context:
            service = by_context.get(story.context)

        ac_ids = [ac.id for ac in story.acceptance_criteria]
        depends_on = list(story.depends_on)

        if service is None:
            items.append(
                StoryCodegenItem(
                    story_id=story.id,
                    acceptance_criteria_ids=ac_ids,
                    cobol_refs=_dedupe(list(story.evidence_refs)),
                    depends_on=depends_on,
                    status=StoryCodegenStatus.blocked,
                )
            )
            continue

        context = service.bounded_context
        cobol_refs = _dedupe(
            list(story.evidence_refs)
            + _domain_refs_for_context(domain_design, context)
            + list(service.evidence_refs)
        )
        items.append(
            StoryCodegenItem(
                story_id=story.id,
                bounded_context=context,
                service_name=service.name,
                acceptance_criteria_ids=ac_ids,
                cobol_refs=cobol_refs,
                depends_on=depends_on,
                status=StoryCodegenStatus.pending,
            )
        )

    return StoryCodegenPlan(
        repo_slug=backlog.repo_slug,
        version=backlog.version,
        items=items,
    )
