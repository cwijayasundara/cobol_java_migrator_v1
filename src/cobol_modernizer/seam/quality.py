from __future__ import annotations

from typing import Any


def assess_seam_quality(candidates: list[dict], *, known_refs: set[str]) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    programs = [str(c.get("program", "")) for c in candidates if c.get("program")]
    program_set = set(programs)
    seam_types = {str(c.get("seam_type", "")) for c in candidates if c.get("seam_type")}
    identity_drift = [str(c.get("program")) for c in candidates if c.get("identity_drift_writer")]
    missing_evidence = sorted(
        str(c.get("program", ""))
        for c in candidates
        if not any((c.get("evidence_map") or {}).values())
    )
    invalid_scores = sorted(
        str(c.get("program", ""))
        for c in candidates
        if not isinstance((c.get("score") or {}).get("weighted"), int | float)
    )
    unknown_refs: set[str] = set()
    allowed_refs = known_refs | program_set
    for cand in candidates:
        for refs in (cand.get("evidence_map") or {}).values():
            for ref in refs or []:
                if ref and ref not in allowed_refs:
                    unknown_refs.add(str(ref))

    result = {
        "candidate_count": len(candidates),
        "program_count": len(program_set),
        "seam_types": sorted(seam_types),
        "identity_drift_writers": sorted(identity_drift),
        "missing_evidence_programs": missing_evidence,
        "invalid_score_programs": invalid_scores,
        "unknown_evidence_refs": sorted(unknown_refs),
        "has_reader_candidate": any(t in {"db_reader", "batch_io", "cics_api"} for t in seam_types),
        "has_writer_candidate": any(t == "db_writer" for t in seam_types),
    }
    threshold = {
        "min_candidates": 1,
        "require_evidence": True,
        "require_valid_scores": True,
        "allow_unknown_refs": False,
    }
    passed = (
        len(candidates) >= 1
        and not missing_evidence
        and not invalid_scores
        and not unknown_refs
    )
    return passed, result, threshold
