from __future__ import annotations

import asyncio
import json

from cobol_modernizer.agent import graph_ops as ops
from cobol_modernizer.agent.advisor import ADVISOR_TOOL_NAME
from cobol_modernizer.agent.brd_schema import BRDDraft, brd_draft_schema
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.brd.schema import BRDSection, Strategy

ELEVEN_SECTIONS = [
    "Executive Summary", "Business Objectives", "Scope", "Stakeholders",
    "Functional Requirements", "Non-functional Requirements", "Data & Integrations",
    "Assumptions", "Constraints", "Risks", "Success Metrics",
]

MAP_SYSTEM = f"""You are a senior business analyst extracting Business Requirements
for ONE subsystem of a codebase. You have graph-navigation tools — use them to pull
ONLY what you need:
- get_source_slice(name) reads one entity's source lines (never whole files)
- neighbors(name, edge, direction) walks CALLS/CONTAINS/IMPORTS/INHERITS
- entry_points / integration_points / get_entity / find_entities

Ground EVERY requirement in real entity ids or file paths you actually inspected.
Use ids FR-1.. and NFR-1.. Provide an evidence_map: requirement_id -> [entity_or_path].
Do NOT invent entities. Cover only this subsystem. Emit the BRDDraft JSON
(sections from this list where relevant: {", ".join(ELEVEN_SECTIONS)})."""

REDUCE_SYSTEM = f"""You are merging per-subsystem BRD drafts into ONE BRD for the whole
repository. Produce exactly these 11 sections in order: {", ".join(ELEVEN_SECTIONS)}.
Deduplicate requirements, reconcile contradictions, keep the most specific wording,
and preserve EVERY evidence pointer (do not drop entries from any evidence_map).
Emit one BRDDraft JSON."""


def _map_prompt(subsystem_name: str, members: list[str]) -> str:
    preview = members[:60]
    return (f"Subsystem: {subsystem_name}\n"
            f"Member entity ids ({len(members)}, first {len(preview)} shown):\n"
            + json.dumps(preview)
            + "\n\nNavigate from these and produce this subsystem's BRD draft.")


def _reduce_prompt(drafts: list[BRDDraft]) -> str:
    payload = [d.model_dump(mode="json") for d in drafts]
    return "Sub-system drafts to merge:\n```json\n" + json.dumps(payload) + "\n```"


def _stub_draft(name: str, exc: Exception) -> BRDDraft:
    return BRDDraft(
        sections=[BRDSection(
            title="Executive Summary",
            body_markdown=f"<subsystem '{name}' failed to generate: {type(exc).__name__}>",
            requirements=[])],
        evidence_map={},
    )


def _merge_drafts_fallback(drafts: list[BRDDraft]) -> BRDDraft:
    """Deterministic reduce used when the LLM reduce step fails: concatenate
    same-titled sections and union every evidence_map (drop nothing)."""
    from collections import OrderedDict
    by_title: "OrderedDict[str, BRDSection]" = OrderedDict()
    evidence: dict[str, list[str]] = {}
    for d in drafts:
        for s in d.sections:
            if s.title in by_title:
                cur = by_title[s.title]
                cur.body_markdown = (cur.body_markdown + "\n\n" + s.body_markdown).strip()
                cur.requirements.extend(s.requirements)
            else:
                by_title[s.title] = BRDSection(title=s.title,
                                               body_markdown=s.body_markdown,
                                               requirements=list(s.requirements))
        for k, refs in d.evidence_map.items():
            bucket = evidence.setdefault(k, [])
            for ref in refs:
                if ref not in bucket:
                    bucket.append(ref)
    return BRDDraft(sections=list(by_title.values()), evidence_map=evidence)


async def _map_one(deps, runner, server, allowed_tools, model, max_turns, sub,
                   prompt_override=None) -> BRDDraft:
    try:
        raw = await runner.run_structured(
            system=MAP_SYSTEM,
            prompt=prompt_override or _map_prompt(sub["name"], sub["members"]),
            server=server, allowed_tools=allowed_tools, model=model,
            max_turns=max_turns, schema=brd_draft_schema(),
        )
        return BRDDraft.model_validate(raw)
    except Exception as exc:  # degrade, don't kill the whole BRD
        return _stub_draft(sub["name"], exc)


async def agenerate_brd_draft(deps: GraphDeps, *, runner: AgentRunner, model: str,
                              max_turns: int, max_subsystems: int,
                              advisor=None, advisor_max_uses: int = 3,
                              prompt_override: str | None = None
                              ) -> tuple[BRDDraft, Strategy]:
    server = build_graph_server(deps, advisor=advisor, advisor_max_uses=advisor_max_uses)
    map_tools = list(GRAPH_TOOL_NAMES) + ([ADVISOR_TOOL_NAME] if advisor is not None else [])
    subs = ops.list_subsystems(deps, max_clusters=max_subsystems)["subsystems"]
    # Drop trivial single-entity "subsystems" (e.g. a lone FILLER / *-STATUS data
    # item that the clusterer split out): spending a map agent — and its whole turn
    # budget — to write a BRD about one field just produces noise and burns the
    # cap. Keep meaningful clusters (>=2 members); fall back to all if that empties.
    meaningful = [s for s in subs if len(s.get("members", [])) >= 2]
    subs = meaningful or subs
    if not subs:
        subs = [{"name": deps.repo_id, "members": []}]

    drafts = await asyncio.gather(*[
        _map_one(deps, runner, server, map_tools, model, max_turns, s, prompt_override)
        for s in subs
    ])

    if len(drafts) == 1:
        return drafts[0], Strategy.single_shot

    try:
        merged = await runner.run_structured(
            system=REDUCE_SYSTEM, prompt=_reduce_prompt(list(drafts)),
            server=server, allowed_tools=GRAPH_TOOL_NAMES, model=model,
            max_turns=max_turns, schema=brd_draft_schema(),
        )
        return BRDDraft.model_validate(merged), Strategy.map_reduce
    except Exception:
        return _merge_drafts_fallback(list(drafts)), Strategy.map_reduce
