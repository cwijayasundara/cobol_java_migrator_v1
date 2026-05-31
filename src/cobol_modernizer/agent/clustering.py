from __future__ import annotations

from dataclasses import dataclass

import networkx as nx


@dataclass
class Subsystem:
    name: str
    members: list[str]


def _name_for(members: list[str]) -> str:
    """Pick the shortest qualified name as the representative label."""
    return min(members, key=lambda m: (len(m), m)) if members else "misc"


def detect_subsystems(nodes: list[str], edges: list[tuple[str, str]],
                      *, max_clusters: int = 12) -> list[Subsystem]:
    """Partition entities into subsystems by connected components over the
    (undirected projection of the) call/contains/imports graph. Language-agnostic:
    operates purely on node ids and edges. If there are more components than
    max_clusters, the largest (max_clusters - 1) are kept and the rest merged into
    one 'misc' subsystem so fan-out stays bounded."""
    g = nx.Graph()
    g.add_nodes_from(nodes)
    g.add_edges_from((s, t) for s, t in edges if s in set(nodes) and t in set(nodes))

    components = [sorted(c) for c in nx.connected_components(g)]
    components.sort(key=lambda c: (-len(c), c[0] if c else ""))

    if len(components) <= max_clusters:
        return [Subsystem(name=_name_for(c), members=c) for c in components]

    keep = components[: max_clusters - 1]
    merged = sorted(m for c in components[max_clusters - 1:] for m in c)
    result = [Subsystem(name=_name_for(c), members=c) for c in keep]
    result.append(Subsystem(name="misc", members=merged))
    return result
