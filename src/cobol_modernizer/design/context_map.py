"""Deterministic, GENERIC bounded-context assignment from data ownership.

A program belongs to the context that owns the data it WRITES. The context
label is derived generically from the names of the owned resources — no
hardcoded resource->context map. Writer-set comes from the v2 graph
(READS/WRITES/EXECUTES_* with intent), computed in Cypher in Phase 1/4 —
zero LLM in this path.

NOTE: this is the legacy DETERMINISTIC fallback. The LLM domain-design stage
does not use this module."""
from __future__ import annotations

import re
from typing import Protocol


class _WriterDeps(Protocol):
    def writer_resources(self, program: str) -> list[str]: ...


def owned_resources(deps: _WriterDeps, program: str) -> list[str]:
    """Resources the program WRITES (owns), sorted for determinism."""
    return sorted(set(deps.writer_resources(program)))


def assign_context_generic(adapter, program: str) -> str:
    """Derive a bounded-context label generically from the resources a program writes —
    the longest common alpha prefix of its owned resources, lowercased. No hardcoded map."""
    resources = [r for r in adapter.writer_resources(program) if r]
    if not resources:
        raise ValueError(f"{program} writes no resources")
    tokens = [re.sub(r"[^A-Za-z]", "", r).upper() for r in resources]
    tokens = [t for t in tokens if t] or [re.sub(r"[^A-Za-z]", "", program).upper()]
    prefix = tokens[0]
    for t in tokens[1:]:
        while not t.startswith(prefix) and len(prefix) > 3:
            prefix = prefix[:-1]
    base = prefix if len(prefix) >= 3 else tokens[0]
    return f"{base.lower()}_context"


def assign_context(adapter: _WriterDeps, program: str) -> str:
    """Back-compat alias; delegates to the generic implementation."""
    return assign_context_generic(adapter, program)
