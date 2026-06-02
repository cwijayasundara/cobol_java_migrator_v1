"""Phase 1: the LLM proposes bounded contexts from the BRD + a bounded graph-coupling
summary; Python computes the topology decision (from seam signals) and the strangler-fig
extraction order, then runs deterministic gates with a bounded repair loop."""
from __future__ import annotations

import json
from typing import Any, Callable

from cobol_modernizer.domain.gates import run_phase1_gates
from cobol_modernizer.domain.inputs import graph_coupling_summary
from cobol_modernizer.domain.schema import (
    DECOMP_SCHEMA, BoundedContextDecl, DecompositionMap, TopologyDecision,
)
from cobol_modernizer.domain.topology import (
    assign_extraction_ranks, deployment_for, extract_score,
)
from cobol_modernizer.enrichment.base import run_batched
from cobol_modernizer.seam.signals import raw_signals_for_program

DECOMPOSE_SYSTEM = (
    "You are a software architect decomposing a legacy COBOL system into business-capability "
    "bounded contexts (Domain-Driven Design) for a Spring Boot rebuild. Group the writer "
    "programs into contexts by BUSINESS CAPABILITY, not by COBOL structure — do NOT emit one "
    "context per program. Every writer program in the graph summary MUST be assigned to exactly "
    "one context. A resource may be OWNED (written) by only one context. Ground every context in "
    "the BRD and the graph: cite BRD requirement ids and program qualified-names in cited_refs; "
    "invent no identifiers. Declare inter-context dependencies (sync for request/response, async "
    "for events) with a grounded reason. "
    'Return JSON: {"contexts":[{"name","business_capability","member_programs":[str],'
    '"owned_resources":[str],"depends_on":[{"target","style","reason","cited_refs":[str]}],'
    '"cited_refs":[str]}],"unassigned_programs":[str],"cited_refs":[str]}.'
)

_WRITES_BY_PROGRAM = """
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
RETURN p.qualified_name AS program,
       collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
"""
_KNOWN_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"

SignalsFn = Callable[..., Any]


def _writers(client: Any, repo: str) -> set[str]:
    rows = client.run(_WRITES_BY_PROGRAM, repo=repo)
    return {r["program"] for r in rows if any(w for w in (r.get("writes") or []))}


def _known_refs(client: Any, repo: str) -> set[str]:
    return {r["q"] for r in client.run(_KNOWN_REFS_Q, repo=repo)}


def _parse(raw: dict, repo: str) -> DecompositionMap:
    contexts = []
    for c in raw.get("contexts", []):
        if isinstance(c, dict) and isinstance(c.get("name"), str):
            try:
                contexts.append(BoundedContextDecl.model_validate(c))
            except Exception:  # noqa: BLE001 — skip malformed; gates catch coverage gaps
                continue
    return DecompositionMap(repo_slug=repo, contexts=contexts,
                            unassigned_programs=list(raw.get("unassigned_programs", [])),
                            cited_refs=list(raw.get("cited_refs", [])))


def _apply_topology(client: Any, repo: str, dm: DecompositionMap,
                    signals_fn: SignalsFn) -> None:
    inbound = {c.name: 0 for c in dm.contexts}
    business: dict[str, float] = {}
    sig_by_name: dict[str, tuple] = {}
    for c in dm.contexts:
        sigs = [signals_fn(client, repo=repo, program=p) for p in c.member_programs] or None
        iso = sum(s.isolation for s in sigs) / len(sigs) if sigs else 0.0
        own = sum(s.data_ownership for s in sigs) / len(sigs) if sigs else 0.0
        biz = sum(s.business for s in sigs) / len(sigs) if sigs else 0.0
        rsk = sum(s.risk for s in sigs) / len(sigs) if sigs else 0.0
        business[c.name] = biz
        sig_by_name[c.name] = (iso, own, biz, rsk)
    for c in dm.contexts:
        for dep in c.depends_on:
            if dep.target in inbound:
                inbound[dep.target] += 1
    for c in dm.contexts:
        c.identity_drift = inbound.get(c.name, 0) > 0
    max_inbound = max(inbound.values()) if inbound else 0
    for c in dm.contexts:
        iso, own, biz, rsk = sig_by_name[c.name]
        inbound_norm = (inbound[c.name] / max_inbound) if max_inbound else 0.0
        score = extract_score(isolation_mean=iso, data_ownership_mean=own,
                              business_mean=biz, risk_mean=rsk, inbound_norm=inbound_norm)
        c.topology = TopologyDecision(
            deployment=deployment_for(score), score=round(score, 4),
            inputs={"isolation_mean": round(iso, 4), "data_ownership_mean": round(own, 4),
                    "business_mean": round(biz, 4), "risk_mean": round(rsk, 4),
                    "inbound_norm": round(inbound_norm, 4)},
            rationale=("high cohesion/ownership favors extraction"
                       if deployment_for(score) == "microservice"
                       else "shared data / low isolation favors a module"))
    assign_extraction_ranks(dm.contexts, inbound=inbound, business=business)


async def decompose(client: Any, repo: str, *, brd_text: str, runner: Any, model: str,
                    timeout_s: float, signals_fn: SignalsFn = raw_signals_for_program,
                    max_repairs: int = 2) -> DecompositionMap:
    writers = _writers(client, repo)
    known = _known_refs(client, repo)
    summary = graph_coupling_summary(client, repo)
    base_prompt = ("## BRD\n" + brd_text + "\n\n## Graph coupling summary\n```json\n"
                   + json.dumps(summary) + "\n```\nDecompose into business-capability "
                   "bounded contexts. Every writer program must be assigned exactly once.")
    violations: list[str] = []
    for attempt in range(max_repairs + 1):
        prompt = base_prompt
        if violations:
            prompt += ("\n\n## Fix these violations from your previous answer\n- "
                       + "\n- ".join(violations))
        raw = await run_batched(runner=runner, system=DECOMPOSE_SYSTEM, prompt=prompt,
                                schema=DECOMP_SCHEMA, model=model, timeout_s=timeout_s,
                                label="domain-decompose")
        dm = _parse(raw, repo)
        _apply_topology(client, repo, dm, signals_fn)
        violations = run_phase1_gates(dm.contexts, writers, known)
        if not violations:
            return dm
    raise ValueError("domain decomposition failed gates after "
                     f"{max_repairs + 1} attempts: {'; '.join(violations)}")
