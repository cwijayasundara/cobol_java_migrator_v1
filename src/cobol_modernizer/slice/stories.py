"""Story cluster for the thin slice: INVEST-style stories with an explicit
acyclic dependency DAG and per-story evidence_map (lineage non-negotiable).
The DAG gate is deterministic (Kahn's algorithm); the LLM only proposes stories.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cobol_modernizer.cost.tiering import resolve_model


@dataclass
class Story:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    evidence_map: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class StoryCluster:
    program: str
    stories: list[Story]

    def topological_order(self) -> list[str]:
        indeg = {s.id: 0 for s in self.stories}
        adj: dict[str, list[str]] = {s.id: [] for s in self.stories}
        for s in self.stories:
            for dep in s.depends_on:
                adj[dep].append(s.id)
                indeg[s.id] += 1
        queue = sorted([sid for sid, d in indeg.items() if d == 0])
        order: list[str] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
            queue.sort()
        if len(order) != len(self.stories):
            raise ValueError("story dependency graph has a cycle")
        return order


def story_model() -> str:
    return resolve_model("story")


def assert_acyclic(cluster: StoryCluster) -> None:
    """Hard gate: the story DAG must be acyclic AND every story must carry evidence
    (lineage). Raises ValueError on a cycle or a story with an empty evidence_map."""
    for s in cluster.stories:
        if not s.evidence_map:
            raise ValueError(f"story {s.id} has no evidence (lineage required)")
    cluster.topological_order()  # raises on cycle
