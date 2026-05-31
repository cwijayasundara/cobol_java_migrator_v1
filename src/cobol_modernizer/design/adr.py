"""Architecture Decision Records for a writer slice. Each ADR carries lineage
(evidence_refs) so design decisions are auditable, not asserted."""
from __future__ import annotations

from cobol_modernizer.design.schema import ADR


def render_adr(adr: ADR) -> str:
    refs = "\n".join(f"- `{r}`" for r in adr.evidence_refs) or "- (none)"
    return (
        f"# ADR-{adr.number:04d}: {adr.title}\n\n"
        f"## Status\n{adr.status}\n\n"
        f"## Context\n{adr.context}\n\n"
        f"## Decision\n{adr.decision}\n\n"
        f"## Consequences\n{adr.consequences}\n\n"
        f"## Evidence (lineage)\n{refs}\n"
    )


def default_adrs_for_writer_slice(*, slice_id: str,
                                  owned_resources: list[str],
                                  evidence_refs: list[str]) -> list[ADR]:
    res = ", ".join(owned_resources)
    return [
        ADR(number=1, title="Modular monolith as default deployment",
            status="accepted",
            context=f"Writer slice {slice_id} owns {res}; no proven need for "
                    f"independent release or ops autonomy yet.",
            decision="Deploy as a bounded-context module in a modular monolith; "
                     "promote to microservice only when data-ownership + "
                     "independent release + ops autonomy are proven.",
            consequences="Lower operational cost; clear seam for later promotion.",
            evidence_refs=evidence_refs),
        ADR(number=2, title="Extract Product Lines for the writer path",
            status="accepted",
            context=f"{slice_id} mutates {res} (identity-drift hazard if dual-write).",
            decision="Use Extract Product Lines: the new service is the single "
                     "writer of its owned data; readers migrate later.",
            consequences="No dual-write; identity-drift writers stay single-system.",
            evidence_refs=evidence_refs),
        ADR(number=3, title="Legacy Mimic write-back via anti-corruption layer",
            status="accepted",
            context="Un-migrated COBOL programs still read the owned files.",
            decision="An ACL serializes the Java result back to the exact "
                     "mainframe fixed-width record (COMP-3 / scale / sign preserved).",
            consequences="COBOL estate keeps running unchanged during strangler-fig.",
            evidence_refs=evidence_refs),
    ]
