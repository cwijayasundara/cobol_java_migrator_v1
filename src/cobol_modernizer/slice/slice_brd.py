"""Focused, slice-scoped BRD: reuse the working BRD harness + judge + groundedness
gate, but scope the agent's evidence to ONE program's subgraph so the BRD is about
the thin slice, not the whole estate. Seam math is NOT here (it is Phase-1 Cypher);
this only reverse-engineers required behavior for the chosen reader-only program.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cobol_modernizer.cost.tiering import resolve_model


@dataclass
class SliceBrdInput:
    program: str
    read_resources: list[dict]            # [{resource, command, intent}]  (intent=='read')
    copybooks: list[str] = field(default_factory=list)


def slice_brd_model() -> str:
    """The slice BRD is synthesis work -> 'brd' role -> Sonnet tier."""
    return resolve_model("brd")


def build_slice_brd_prompt(inp: SliceBrdInput) -> str:
    resources = ", ".join(r["resource"] for r in inp.read_resources)
    copybooks = ", ".join(inp.copybooks) or "(none)"
    return (
        f"Produce a FOCUSED Business Requirements Document for the single program "
        f"{inp.program}. This is one thin vertical slice of a COBOL modernization; "
        f"scope strictly to this program.\n\n"
        f"This program is READ-ONLY. Its data accesses (all intent=read) are: "
        f"{resources}. Its record layouts come from copybooks: {copybooks}.\n\n"
        f"Use ONLY the read-only graph tools to gather evidence: call get_entity on "
        f"{inp.program}, data_accesses to enumerate its reads, neighbors with "
        f"edge=IMPORTS for copybooks, and get_source_slice to read code lines — never "
        f"request whole files.\n\n"
        f"Separate REQUIRED behavior (the account-view query the business depends on) "
        f"from ACCIDENTAL legacy behavior (screen/BMS formatting, CICS plumbing, "
        f"error-message construction). The migration target reproduces required "
        f"behavior only; we verify OUTCOME parity, not feature parity.\n\n"
        f"Every requirement MUST carry an evidence_map entry referencing the graph "
        f"entity ids / source refs it is grounded in."
    )


async def agenerate_slice_brd(deps, *, runner, model: str, inp: SliceBrdInput,
                              max_retries: int = 1, max_turns: int = 15,
                              advisor=None, advisor_max_uses: int = 3):
    """Run the slice BRD through the SAME groundedness-gated loop as the estate BRD,
    but with a single-program prompt. Returns the GraphBRDResult (brd, report,
    rating, weighted_score). Imported lazily so unit tests need no SDK."""
    from cobol_modernizer.agent.brd_judge import ajudge
    from cobol_modernizer.agent.brd_orchestrator import agenerate_brd_draft
    from cobol_modernizer.brd.pipeline import GraphBRDResult, _draft_to_brd
    from cobol_modernizer.brd.schema import AttemptRecord, Rating

    attempts: list[AttemptRecord] = []
    best: tuple = None
    prompt = build_slice_brd_prompt(inp)
    for attempt_no in range(1, max_retries + 2):
        draft, strategy = await agenerate_brd_draft(
            deps, runner=runner, model=model, max_turns=max_turns,
            max_subsystems=1, advisor=advisor, advisor_max_uses=advisor_max_uses,
            prompt_override=prompt)
        brd = _draft_to_brd(draft, deps.repo_id, model, strategy)
        report = await ajudge(brd, deps, runner=runner, model=model)
        attempts.append(AttemptRecord(attempt=attempt_no, rating=report.rating,
                                      weighted_score=report.weighted_score,
                                      feedback=report.feedback))
        if best is None or report.weighted_score > best[1].weighted_score:
            best = (brd, report)
        if report.rating == Rating.high:
            break
    final_brd, final_report = best
    return GraphBRDResult(brd=final_brd, report=final_report,
                          rating=final_report.rating,
                          weighted_score=final_report.weighted_score,
                          attempts=len(attempts), attempt_history=attempts,
                          strategy=final_brd.strategy)
