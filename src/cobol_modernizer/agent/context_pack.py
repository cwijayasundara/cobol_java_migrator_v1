"""Shared context-pack model for bounded work units.

A context pack is the explicit input contract for one LLM or verification unit:
structured sections, citable refs, optional source slices, and a stable hash over the
real content. It is pure and deterministic so every stage can cache work units by the
same `input_hash` concept.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextPackSection:
    title: str
    content: Any
    required: bool = True
    refs: tuple[str, ...] = ()

    def normalized(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "required": self.required,
            "refs": list(self.refs),
        }


@dataclass(frozen=True)
class ContextPack:
    stage: str
    unit_type: str
    unit_key: str
    sections: tuple[ContextPackSection, ...] = ()
    refs: tuple[str, ...] = ()
    source_slices: tuple[ContextPackSection, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt_version: str = "v1"

    def normalized(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "unit_type": self.unit_type,
            "unit_key": self.unit_key,
            "prompt_version": self.prompt_version,
            "metadata": self.metadata,
            "refs": list(self.refs),
            "sections": [s.normalized() for s in self.sections],
            "source_slices": [s.normalized() for s in self.source_slices],
        }

    @property
    def input_hash(self) -> str:
        payload = json.dumps(self.normalized(), sort_keys=True,
                             separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def render(self, *, max_chars: int | None = None) -> tuple[str, dict[str, Any]]:
        """Render a readable prompt body and return diagnostics.

        The render does not drop required sections. If `max_chars` is exceeded, the
        text is returned intact and diagnostics record the overage. Callers can decide
        whether to decompose further, fail the unit, or pass the full prompt.
        """
        blocks = [
            f"# Context Pack: {self.stage}/{self.unit_type}/{self.unit_key}",
            f"prompt_version: {self.prompt_version}",
        ]
        if self.refs:
            blocks.append("## Citable Refs\n" + json.dumps(list(self.refs)))
        for section in self.sections:
            blocks.append(_render_section(section))
        for section in self.source_slices:
            blocks.append(_render_section(section, prefix="Source"))
        text = "\n\n".join(blocks)
        diagnostics = self.diagnostics(max_chars=max_chars)
        return text, diagnostics

    def diagnostics(self, *, max_chars: int | None = None) -> dict[str, Any]:
        normalized = self.normalized()
        char_count = len(json.dumps(normalized, sort_keys=True, default=str))
        required_sections = [s.title for s in self.sections if s.required]
        required_sections.extend(f"Source: {s.title}" for s in self.source_slices
                                 if s.required)
        over_limit = max_chars is not None and char_count > max_chars
        return {
            "input_hash": self.input_hash,
            "char_count": char_count,
            "max_chars": max_chars,
            "over_limit": over_limit,
            "section_count": len(self.sections),
            "source_slice_count": len(self.source_slices),
            "required_sections": required_sections,
            "ref_count": len(self.refs),
        }


def build_context_pack(*, stage: str, unit_type: str, unit_key: str,
                       sections: list[dict[str, Any]] | None = None,
                       refs: list[str] | None = None,
                       source_slices: list[dict[str, Any]] | None = None,
                       metadata: dict[str, Any] | None = None,
                       prompt_version: str = "v1") -> ContextPack:
    return ContextPack(
        stage=stage,
        unit_type=unit_type,
        unit_key=unit_key,
        sections=tuple(_section(s) for s in (sections or [])),
        refs=tuple(_dedupe(refs or [])),
        source_slices=tuple(_section(s) for s in (source_slices or [])),
        metadata=dict(metadata or {}),
        prompt_version=prompt_version,
    )


def build_domain_decomposition_pack(*, repo_slug: str, brd_text: str,
                                    backlog_json: str) -> ContextPack:
    sections = [{"title": "BRD", "content": brd_text}]
    if backlog_json.strip():
        sections.append({"title": "Backlog", "content": backlog_json, "required": False})
    return build_context_pack(
        stage="domain-design", unit_type="decomposition", unit_key="decompose",
        sections=sections, metadata={"repo_slug": repo_slug},
        prompt_version="domain-decompose-v1")


def build_domain_tactical_pack(*, unit_type: str, unit_key: str,
                               context: dict[str, Any], known_refs: set[str],
                               aggregate: dict | None = None,
                               contract: dict | None = None) -> ContextPack:
    sections: list[dict[str, Any]] = [
        {"title": "Bounded context", "content": context,
         "refs": list(context.get("cited_refs") or [])},
    ]
    if aggregate is not None:
        sections.append({"title": "Aggregate model", "content": aggregate})
    if contract is not None:
        sections.append({"title": "Tactical contracts", "content": contract})
    return build_context_pack(
        stage="domain-design", unit_type=unit_type, unit_key=unit_key,
        sections=sections, refs=sorted(known_refs),
        metadata={"context": unit_key}, prompt_version="domain-tactical-v1")


def build_backlog_oneshot_pack(*, brd_sections: list[dict], known_refs: list[str],
                               brd_evidence_map: dict,
                               known_requirement_ids: list[str],
                               relevant_refs_fn) -> ContextPack:
    brd_relevant = relevant_refs_fn(brd_evidence_map, known_refs) or list(known_refs)
    return build_context_pack(
        stage="backlog", unit_type="oneshot", unit_key="backlog",
        sections=[
            {"title": "BRD sections", "content": brd_sections},
            {"title": "BRD evidence map", "content": brd_evidence_map,
             "required": False},
            {"title": "Known requirement ids", "content": known_requirement_ids},
        ],
        refs=brd_relevant,
        prompt_version="backlog-oneshot-v1")


def build_backlog_epics_pack(*, brd_sections: list[dict], known_refs: list[str],
                             brd_evidence_map: dict,
                             known_requirement_ids: list[str],
                             relevant_refs_fn) -> ContextPack:
    brd_relevant = relevant_refs_fn(brd_evidence_map, known_refs) or list(known_refs)
    return build_context_pack(
        stage="backlog", unit_type="epics", unit_key="epics",
        sections=[
            {"title": "BRD sections", "content": brd_sections},
            {"title": "BRD evidence map", "content": brd_evidence_map,
             "required": False},
            {"title": "Known requirement ids", "content": known_requirement_ids},
        ],
        refs=brd_relevant,
        prompt_version="backlog-epics-v1")


def build_backlog_stories_pack(*, epic: dict, req_ids: set[str],
                               brd_sections_for_epic: list[dict],
                               refs: list[str],
                               known_requirement_ids: list[str],
                               round_key: str) -> ContextPack:
    epic_id = str(epic.get("id", ""))
    return build_context_pack(
        stage="backlog", unit_type="stories", unit_key=f"{round_key}:{epic_id}",
        sections=[
            {"title": "Epic", "content": {
                "id": epic_id,
                "title": str(epic.get("title", "")),
                "outcome": str(epic.get("outcome", "")),
            }},
            {"title": "Requirement ids to cover", "content": sorted(req_ids)},
            {"title": "BRD sections for epic", "content": brd_sections_for_epic},
            {"title": "Known requirement ids", "content": known_requirement_ids},
        ],
        refs=refs,
        metadata={"round": round_key, "epic_id": epic_id},
        prompt_version="backlog-stories-v1")


def build_technical_service_pack(*, context: dict, stories: list[dict],
                                 seam_waves: list, known_refs: list[str],
                                 known_story_ids: list[str],
                                 relevant_refs_fn) -> ContextPack:
    ctx_name = str(context.get("name", ""))
    refs = relevant_refs_fn(context, known_refs)
    return build_context_pack(
        stage="technical-design", unit_type="service", unit_key=ctx_name,
        sections=[
            {"title": "Bounded context", "content": context,
             "refs": list(context.get("cited_refs") or [])},
            {"title": "Stories", "content": {"stories": stories}, "required": False},
            {"title": "Seam waves", "content": seam_waves, "required": False},
            {"title": "Known story ids", "content": known_story_ids, "required": False},
        ],
        refs=refs,
        metadata={"context": ctx_name},
        prompt_version="technical-service-v1")


def build_story_codegen_pack(*, story_id: str, context_hash: str,
                             context: Any, project_index: list[str] | None = None,
                             phase: str = "story-codegen") -> ContextPack:
    return build_context_pack(
        stage="build", unit_type=phase, unit_key=story_id,
        sections=[
            {"title": "Story context", "content": context},
            {"title": "Project index", "content": project_index or [],
             "required": False},
        ],
        metadata={"story_id": story_id, "context_hash": context_hash},
        prompt_version="story-codegen-v1")


def _section(raw: dict[str, Any]) -> ContextPackSection:
    return ContextPackSection(
        title=str(raw.get("title", "")),
        content=raw.get("content", ""),
        required=bool(raw.get("required", True)),
        refs=tuple(_dedupe(raw.get("refs") or [])),
    )


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in out:
            out.append(value)
    return out


def _render_section(section: ContextPackSection, *, prefix: str = "") -> str:
    title = f"{prefix}: {section.title}" if prefix else section.title
    marker = "required" if section.required else "optional"
    content = (section.content if isinstance(section.content, str)
               else json.dumps(section.content, sort_keys=True))
    refs = ("\nrefs: " + json.dumps(list(section.refs))) if section.refs else ""
    return f"## {title} ({marker}){refs}\n{content}"
