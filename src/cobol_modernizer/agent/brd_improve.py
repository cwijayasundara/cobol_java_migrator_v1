"""Instruction-directed, graph-grounded BRD refinement: ONE agent seeded with the
current BRD + a user instruction, using the same graph tools as the draft agent, with
a hard timeout. Raises on empty output so a failed improve never overwrites the prior
version (the pipeline only saves a valid draft)."""
from __future__ import annotations

import asyncio

from cobol_modernizer.agent.advisor import ADVISOR_TOOL_NAME
from cobol_modernizer.agent.brd_schema import BRDDraft, brd_draft_schema
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.brd.schema import Strategy

IMPROVE_SYSTEM = """You are refining an EXISTING Business Requirements Document for a
codebase. Apply the user's improvement instruction. You have graph-navigation tools —
use them to add ONLY grounded detail (real entity ids / file paths you actually inspect:
get_source_slice, neighbors, find_entities, integration_points, ...). PRESERVE correct
existing content and every still-valid evidence pointer; do not invent identifiers.
Keep the same 11 sections. Emit the full improved BRDDraft JSON (sections + evidence_map:
requirement_id -> [entity_or_path])."""


def _improve_prompt(current_brd: str, instruction: str) -> str:
    return ("## Current BRD\n" + current_brd
            + "\n\n## Improvement instruction\n" + instruction
            + "\n\nApply the instruction and emit the full improved BRDDraft.")


async def agenerate_brd_improvement(deps: GraphDeps, *, current_brd: str,
                                    instruction: str, runner: AgentRunner, model: str,
                                    max_turns: int, timeout_s: float,
                                    advisor=None, advisor_max_uses: int = 3
                                    ) -> tuple[BRDDraft, Strategy]:
    server = build_graph_server(deps, advisor=advisor, advisor_max_uses=advisor_max_uses)
    tools = list(GRAPH_TOOL_NAMES) + ([ADVISOR_TOOL_NAME] if advisor is not None else [])
    raw = await asyncio.wait_for(
        runner.run_structured(
            system=IMPROVE_SYSTEM, prompt=_improve_prompt(current_brd, instruction),
            server=server, allowed_tools=tools, model=model, max_turns=max_turns,
            schema=brd_draft_schema(), label="brd-improve"),
        timeout=timeout_s)
    if not raw or not raw.get("sections"):
        raise ValueError("improve agent produced no usable BRD draft")
    return BRDDraft.model_validate(raw), Strategy.single_shot
