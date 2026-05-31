from __future__ import annotations

from typing import Any, Protocol

from cobol_modernizer.seam.deadcode import dead_paragraphs
from cobol_modernizer.seam.reader_writer import (
    classify_program, is_identity_drift_writer,
)
from cobol_modernizer.seam.scoring import score_signals
from cobol_modernizer.seam.signals import raw_signals_for_program
from cobol_modernizer.seam.schema import (
    SeamCandidate, SeamSet,
)
from cobol_modernizer.seam.transition import classify_seam_type, transition_for


class GraphClient(Protocol):
    def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


_ALL_PROGRAMS = """
// all_programs
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
RETURN p.simple_name AS program ORDER BY program
"""

_HAS_CICS = """
// has_cics
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[:EXECUTES_CICS]->()
WHERE p.simple_name = $program OR p.qualified_name = $program
RETURN count(*) AS n
"""

# A batch-IO seam genuinely reads sequential files (READS edges, sequential mode).
# This is what distinguishes it from a db_reader (CICS/keyed read). The plan's
# greedy "any non-CICS reader is batch_io" made db_reader unreachable and
# mis-typed CICS readers when CICS could not be detected; require a real signal.
_BATCH_SEQ_READ = """
// batch_seq_read
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS]->(res)
WHERE (p.qualified_name = $program OR p.simple_name = $program)
  AND coalesce(r.mode, 'sequential') = 'sequential'
RETURN count(r) AS n
"""


def _one(rows: list[dict], key: str, default: Any = 0) -> Any:
    return rows[0].get(key, default) if rows else default


def _profile(client: GraphClient, repo: str, program: str) -> dict:
    cls = classify_program(client, repo=repo, program=program)
    has_cics = bool(_one(client.run(_HAS_CICS, repo=repo, program=program), "n", 0))
    is_writer = len(cls["writes"]) > 0
    seq_reads = int(_one(client.run(_BATCH_SEQ_READ, repo=repo, program=program), "n", 0))
    is_batch_io = (not has_cics) and not is_writer and seq_reads > 0
    return {"has_cics": has_cics, "is_writer": is_writer, "is_copybook": False,
            "is_batch_io": is_batch_io, "reader_only": cls["reader_only"]}


def _candidate(client: GraphClient, repo: str, program: str) -> SeamCandidate:
    signals = raw_signals_for_program(client, repo=repo, program=program)
    score = score_signals(signals)
    profile = _profile(client, repo, program)
    seam_type = classify_seam_type(profile)
    transition = transition_for(seam_type)
    evidence = {
        "business": [program], "isolation": [program], "testability": [program],
        "data_ownership": [program], "risk": [program],
    }
    return SeamCandidate(
        program=program, seam_type=seam_type, signals=signals, score=score,
        transition=transition, evidence_map=evidence,
        identity_drift_writer=is_identity_drift_writer(client, repo=repo, program=program),
    )


def rank_candidates(client: GraphClient, *, repo: str, limit: int = 20) -> list[dict]:
    """LLM-free ranked seam backlog (what the MCP seam_candidates tool returns)."""
    programs = [r["program"] for r in client.run(_ALL_PROGRAMS, repo=repo)
                if r.get("program")]
    cands = [_candidate(client, repo, p) for p in programs]
    cands.sort(key=lambda c: c.score.weighted, reverse=True)
    return [c.model_dump(mode="json") for c in cands[:limit]]


async def build_seam_set(client: GraphClient, *, repo: str, known_refs: set[str],
                         runner, model: str, limit: int = 20) -> SeamSet:
    from cobol_modernizer.seam.dedup import duplicate_capabilities
    from cobol_modernizer.seam.rationale import awrite_rationale

    programs = [r["program"] for r in client.run(_ALL_PROGRAMS, repo=repo)
                if r.get("program")]
    cands = [_candidate(client, repo, p) for p in programs]
    cands.sort(key=lambda c: c.score.weighted, reverse=True)
    cands = cands[:limit]

    for c in cands:
        out = await awrite_rationale(program=c.program, evidence=c.evidence_map,
                                     known_refs=known_refs, runner=runner, model=model)
        c.rationale = out["rationale"]

    dead: list[str] = []
    for p in programs:
        dead.extend(dead_paragraphs(client, repo=repo, program=p))

    # Capability fingerprint over each program's (resource, intent) access signature.
    access_profiles: dict[str, dict] = {}
    for p in programs:
        cls = classify_program(client, repo=repo, program=p)
        access_profiles[p] = {"accesses": [(r, "read") for r in cls["reads"]]
                              + [(w, "write") for w in cls["writes"]]}
    dups = duplicate_capabilities(access_profiles, key="accesses")

    return SeamSet(repo_id=repo, candidates=cands,
                   duplicate_capabilities=dups, dead_paragraphs=sorted(set(dead)))
