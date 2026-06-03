"""Per-story context pack (Task 3 of the story-sliced codegen engine).

Assembles the COMPACT, BOUNDED prompt context for generating ONE user story:
just that story's narrative + acceptance criteria, the summaries of its already
-completed dependency stories, the mapped DDD aggregate (invariants/methods),
the mapped technical service (API + persistence), the relevant BRD
requirements, and the COBOL source snippets for the story's evidence refs. This
replaces whole-repo/graph dumps as the input to per-story test+code generation
(Task 4); the `context_hash` lets later tasks skip regenerating an unchanged
story.

This module is PURE/deterministic: a transform over already-resolved spec
objects plus stable sha256 hashing. It performs NO Neo4j, LLM, or disk I/O — the
COBOL source is passed IN as an already-fetched string (the caller, Task 6,
builds it via `build.py::_slice_pack` scoped to the story's `cobol_refs`). The
only environment reads are the two char-limit overrides, applied at render time;
the hash is computed over the REAL (pre-truncation) content so truncation never
changes a story's identity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from pydantic import BaseModel, Field

from cobol_modernizer.backlog.schema import UserStory
from cobol_modernizer.codegen.story_plan import StoryCodegenItem
from cobol_modernizer.domain.schema import Aggregate
from cobol_modernizer.technical_design.schema import TechnicalService

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 24000
DEFAULT_SOURCE_MAX_CHARS = 12000
_TRUNC_MARK = "\n...[truncated]..."


class StoryContextPack(BaseModel):
    """Structured, bounded context for generating one user story.

    Carries every section explicitly (so callers can inspect/serialize it) plus
    `context_hash`, a stable fingerprint of the REAL inputs. `render()` produces
    the bounded prompt text, applying the char limits.
    """

    story_id: str
    story_title: str = ""
    story_narrative: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    completed_summaries: list[str] = Field(default_factory=list)

    aggregate_name: str = ""
    invariants: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)

    service_name: str = ""
    api_lines: list[str] = Field(default_factory=list)
    persistence_lines: list[str] = Field(default_factory=list)

    brd_requirements: list[str] = Field(default_factory=list)
    source_pack: str = ""

    context_hash: str = ""

    max_chars: int | None = None
    source_max_chars: int | None = None

    def render(self) -> str:
        """Render the bounded prompt text. The COBOL source section is capped at
        `source_max_chars`, then the whole assembled pack is capped at
        `max_chars`. For each limit: an explicit build-time value wins; else an
        env override; else the default."""
        max_chars = _resolve_limit(
            self.max_chars, DEFAULT_MAX_CHARS, "STORY_CONTEXT_MAX_CHARS"
        )
        source_max = _resolve_limit(
            self.source_max_chars,
            DEFAULT_SOURCE_MAX_CHARS,
            "STORY_SOURCE_MAX_CHARS",
        )
        return _render_text(self, max_chars=max_chars, source_max_chars=source_max)


def _resolve_limit(explicit: int | None, default: int, env_var: str) -> int:
    """Explicit build-time value wins; else env override; else default."""
    if explicit is not None:
        return explicit
    raw = os.environ.get(env_var)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "Ignoring non-integer %s=%r; using default %d",
                env_var,
                raw,
                default,
            )
    return default


def _truncate(text: str, limit: int) -> str:
    if limit < 0 or len(text) <= limit:
        return text
    if limit <= len(_TRUNC_MARK):
        return text[:limit]
    return text[: limit - len(_TRUNC_MARK)] + _TRUNC_MARK


def _api_lines(service: TechnicalService) -> list[str]:
    lines: list[str] = []
    for contract in service.api_contracts:
        line = f"{contract.method} {contract.path} ({contract.name})"
        if contract.request_model or contract.response_model:
            line += (
                f" req={contract.request_model} resp={contract.response_model}"
            )
        if contract.details:
            line += f" - {contract.details}"
        lines.append(line)
    return lines


def _persistence_lines(service: TechnicalService) -> list[str]:
    lines: list[str] = []
    for persistence in service.persistence:
        line = f"{persistence.resource} [{persistence.access_pattern}]"
        if persistence.owner_service:
            line += f" owner={persistence.owner_service}"
        if persistence.details:
            line += f" - {persistence.details}"
        lines.append(line)
    return lines


def build_story_context(
    item: StoryCodegenItem,
    *,
    story: UserStory,
    service: TechnicalService | None,
    aggregate: Aggregate | None,
    brd_requirements: list[str],
    completed_summaries: list[str],
    source_pack: str,
    max_chars: int | None = None,
    source_max_chars: int | None = None,
) -> StoryContextPack:
    """Build the per-story context pack for a single `StoryCodegenItem`.

    `service`, `aggregate`, and `brd_requirements` are the already-resolved
    mappings for this story (the caller resolves them from
    `item.bounded_context`/`item.service_name`). A `None` mapping simply omits
    that section. `completed_summaries` are caller-supplied short strings for
    the story's already-done `depends_on` stories — included verbatim, never
    fetched. `source_pack` is the already-fetched COBOL snippet string for the
    story's `cobol_refs`.

    The `context_hash` is computed over the REAL (pre-truncation) content so it
    changes only when BRD/story/DDD/technical/COBOL-evidence content changes,
    never merely because rendering truncated.

    `completed_summaries` is DELIBERATELY excluded from `context_hash`: it is derived
    RUN context (the running list of already-built dependency stories, which the
    plan-level loop threads in as it iterates), not a primary spec input. Including it
    would shift the hash on every run as earlier stories complete, defeating resume —
    `budget.should_skip` would never skip an unchanged-spec story. The summaries still
    appear in the rendered prompt; they just don't define a story's identity.
    """
    acceptance = [ac.statement for ac in story.acceptance_criteria]

    aggregate_name = aggregate.name if aggregate else ""
    invariants = list(aggregate.invariants) if aggregate else []
    methods = list(aggregate.methods) if aggregate else []

    service_name = service.name if service else ""
    api_lines = _api_lines(service) if service else []
    persistence_lines = _persistence_lines(service) if service else []

    brd = list(brd_requirements)
    summaries = list(completed_summaries)

    context_hash = _hash_inputs(
        story_id=item.story_id,
        title=story.title,
        narrative=story.narrative,
        acceptance=acceptance,
        aggregate_name=aggregate_name,
        invariants=invariants,
        methods=methods,
        service_name=service_name,
        api_lines=api_lines,
        persistence_lines=persistence_lines,
        brd_requirements=brd,
        source_pack=source_pack,
    )

    return StoryContextPack(
        story_id=item.story_id,
        story_title=story.title,
        story_narrative=story.narrative,
        acceptance_criteria=acceptance,
        completed_summaries=summaries,
        aggregate_name=aggregate_name,
        invariants=invariants,
        methods=methods,
        service_name=service_name,
        api_lines=api_lines,
        persistence_lines=persistence_lines,
        brd_requirements=brd,
        source_pack=source_pack,
        context_hash=context_hash,
        max_chars=max_chars,
        source_max_chars=source_max_chars,
    )


def _hash_inputs(**inputs: object) -> str:
    """Stable sha256 over the normalized REAL content. JSON with sorted keys +
    explicit separators makes the digest deterministic across runs and
    insensitive to dict ordering, while remaining sensitive to any change in any
    field's value (including list ordering, which is semantically meaningful)."""
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_text(
    pack: StoryContextPack, *, max_chars: int, source_max_chars: int
) -> str:
    sections: list[str] = []

    header = [f"# Story {pack.story_id}: {pack.story_title}".rstrip()]
    if pack.story_narrative:
        header.append(pack.story_narrative)
    sections.append("\n".join(header))

    if pack.acceptance_criteria:
        lines = ["## Acceptance Criteria"]
        lines += [f"- {ac}" for ac in pack.acceptance_criteria]
        sections.append("\n".join(lines))

    if pack.completed_summaries:
        lines = ["## Completed Dependencies"]
        lines += [f"- {s}" for s in pack.completed_summaries]
        sections.append("\n".join(lines))

    if pack.aggregate_name or pack.invariants or pack.methods:
        lines = [f"## Domain Aggregate: {pack.aggregate_name}".rstrip()]
        if pack.invariants:
            lines.append("Invariants:")
            lines += [f"- {i}" for i in pack.invariants]
        if pack.methods:
            lines.append("Methods:")
            lines += [f"- {m}" for m in pack.methods]
        sections.append("\n".join(lines))

    if pack.service_name or pack.api_lines or pack.persistence_lines:
        lines = [f"## Technical Service: {pack.service_name}".rstrip()]
        if pack.api_lines:
            lines.append("API:")
            lines += [f"- {a}" for a in pack.api_lines]
        if pack.persistence_lines:
            lines.append("Persistence:")
            lines += [f"- {p}" for p in pack.persistence_lines]
        sections.append("\n".join(lines))

    if pack.brd_requirements:
        lines = ["## BRD Requirements"]
        lines += [f"- {r}" for r in pack.brd_requirements]
        sections.append("\n".join(lines))

    if pack.source_pack:
        source = _truncate(pack.source_pack, source_max_chars)
        sections.append("## COBOL Source\n" + source)

    return _truncate("\n\n".join(sections), max_chars)
