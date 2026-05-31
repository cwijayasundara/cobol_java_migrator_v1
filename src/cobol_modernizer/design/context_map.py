"""Deterministic bounded-context assignment from data ownership.

A program belongs to the context that owns the data it WRITES. Writer-set
comes from the v2 graph (READS/WRITES/EXECUTES_* with intent), computed in
Cypher in Phase 1/4 — zero LLM in this path."""
from __future__ import annotations

from collections import Counter
from typing import Protocol

# CardDemo VSAM/file -> bounded context. Grounded in the four Phase-5 contexts.
RESOURCE_CONTEXT: dict[str, str] = {
    "ACCTDAT": "account_management",
    "ACCTFILE": "account_management",
    "CUSTDAT": "account_management",
    "CARDDAT": "card_management",
    "CARDFILE": "card_management",
    "CXACAIX": "card_management",
    "TRANSACT": "transaction_processing",
    "TRANFILE": "transaction_processing",
    "TCATBAL": "transaction_processing",
    "TCATBALF": "transaction_processing",
    "DALYTRAN": "transaction_processing",
    "BILLPAY": "bill_pay_reporting",
    "RPTFILE": "bill_pay_reporting",
}


class _WriterDeps(Protocol):
    def writer_resources(self, program: str) -> list[str]: ...


def owned_resources(deps: _WriterDeps, program: str) -> list[str]:
    """Resources the program WRITES (owns), sorted for determinism."""
    return sorted(set(deps.writer_resources(program)))


def assign_context(deps: _WriterDeps, program: str) -> str:
    owned = owned_resources(deps, program)
    if not owned:
        raise ValueError(f"{program} has no owned (written) resources; "
                         f"reader-only programs are not assigned a context")
    tally: Counter[str] = Counter()
    for res in owned:
        ctx = RESOURCE_CONTEXT.get(res)
        if ctx:
            tally[ctx] += 1
    if not tally:
        raise ValueError(f"{program} owns resources {owned} with no known context")
    # dominant context wins; ties broken by name for determinism
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
