from __future__ import annotations

from collections import deque

from cobol_modernizer.planner.schema import StoryDAG


class CycleError(Exception):
    """Raised when the story dependency graph is not acyclic, or references an
    unknown story id. A cycle is a hard gate failure."""


def topo_order(dag: StoryDAG) -> list[str]:
    ids = {s.id for s in dag.stories}
    indeg: dict[str, int] = {s.id: 0 for s in dag.stories}
    adj: dict[str, list[str]] = {s.id: [] for s in dag.stories}
    for s in dag.stories:
        for dep in s.depends_on:
            if dep not in ids:
                raise CycleError(f"story {s.id!r} depends on unknown story {dep!r}")
            adj[dep].append(s.id)
            indeg[s.id] += 1
    queue = deque(sorted(i for i, d in indeg.items() if d == 0))
    order: list[str] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if len(order) != len(dag.stories):
        remaining = sorted(i for i in indeg if i not in order)
        raise CycleError(f"story DAG has a cycle among: {remaining}")
    return order


def delivery_waves(dag: StoryDAG) -> list[list[str]]:
    """Group the story DAG into delivery WAVES (level-sets): wave 0 is every story
    with no dependencies, wave 1 every story whose deps are all in wave 0, etc.
    Stories in the same wave have no edges between them and can migrate in parallel.
    Same Kahn's-algorithm pass as topo_order, batched by level. Raises CycleError on
    a cycle / unknown id (a cycle is a hard gate failure, like topo_order)."""
    ids = {s.id for s in dag.stories}
    indeg: dict[str, int] = {s.id: 0 for s in dag.stories}
    adj: dict[str, list[str]] = {s.id: [] for s in dag.stories}
    for s in dag.stories:
        for dep in s.depends_on:
            if dep not in ids:
                raise CycleError(f"story {s.id!r} depends on unknown story {dep!r}")
            adj[dep].append(s.id)
            indeg[s.id] += 1
    frontier = sorted(i for i, d in indeg.items() if d == 0)
    waves: list[list[str]] = []
    seen = 0
    while frontier:
        waves.append(frontier)
        seen += len(frontier)
        nxt: list[str] = []
        for n in frontier:
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    nxt.append(m)
        frontier = sorted(nxt)
    if seen != len(dag.stories):
        remaining = sorted(i for i, d in indeg.items() if d > 0)
        raise CycleError(f"story DAG has a cycle among: {remaining}")
    return waves


def is_acyclic(dag: StoryDAG) -> bool:
    try:
        topo_order(dag)
        return True
    except CycleError:
        return False
