from __future__ import annotations

from typing import Any

from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.clustering import detect_subsystems

# Whitelist: edges and directions an agent may traverse. Anything else is rejected
# so a tool call can never smuggle arbitrary Cypher fragments into a query.
_EDGES = {"CALLS", "IMPORTS", "CONTAINS", "INHERITS", "DECORATES", "RAISES"}
_DIRECTIONS = {"out", "in", "both"}


def get_entity(deps: GraphDeps, name: str) -> dict[str, Any]:
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        WHERE e.qualified_name = $name OR e.simple_name = $name
        RETURN e.qualified_name AS qualified_name, e.simple_name AS simple_name,
               e.kind AS kind, e.file_path AS file_path,
               e.signature AS signature, e.start_line AS start_line,
               e.end_line AS end_line, e.semantic_layer AS semantic_layer,
               e.semantic_summary AS semantic_summary
        LIMIT 1
        """,
        repo=deps.repo_id, name=name,
    )
    if not rows:
        return {"error": f"unknown entity: {name}"}
    return rows[0]


def find_entities(deps: GraphDeps, *, kind: str | None = None,
                  prefix: str | None = None, limit: int = 50) -> dict[str, Any]:
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        WHERE ($kind IS NULL OR e.kind = $kind)
          AND ($prefix IS NULL OR toLower(e.qualified_name) STARTS WITH toLower($prefix))
        RETURN e.qualified_name AS qualified_name, e.kind AS kind,
               e.file_path AS file_path
        ORDER BY size(e.qualified_name), e.qualified_name
        LIMIT $limit
        """,
        repo=deps.repo_id, kind=kind, prefix=prefix, limit=limit,
    )
    return {"entities": rows}


def neighbors(deps: GraphDeps, name: str, *, edge: str,
              direction: str = "out", depth: int = 1, limit: int = 50) -> dict[str, Any]:
    if edge not in _EDGES:
        return {"error": f"unsupported edge {edge!r}; allowed: {sorted(_EDGES)}"}
    if direction not in _DIRECTIONS:
        return {"error": f"unsupported direction {direction!r}"}
    depth = max(1, min(int(depth), 5))
    if direction == "out":
        pattern = f"(a:CodeEntity {{repo: $repo}})-[:{edge}*1..{depth}]->(b:CodeEntity)"
    elif direction == "in":
        pattern = f"(a:CodeEntity {{repo: $repo}})<-[:{edge}*1..{depth}]-(b:CodeEntity)"
    else:
        pattern = f"(a:CodeEntity {{repo: $repo}})-[:{edge}*1..{depth}]-(b:CodeEntity)"
    rows = deps.client.run(
        f"""
        MATCH {pattern}
        WHERE a.qualified_name = $name
        RETURN DISTINCT b.qualified_name AS qualified_name, b.kind AS kind,
               b.file_path AS file_path
        ORDER BY b.qualified_name
        LIMIT $limit
        """,
        repo=deps.repo_id, name=name, limit=limit,
    )
    return {"neighbors": rows}


def get_source_slice(deps: GraphDeps, name: str) -> dict[str, Any]:
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        WHERE e.qualified_name = $name
        RETURN e.file_path AS file, e.start_line AS start, e.end_line AS end
        LIMIT 1
        """,
        repo=deps.repo_id, name=name,
    )
    if not rows or not rows[0].get("file"):
        return {"error": f"unknown entity or no source location: {name}"}
    file = rows[0]["file"]
    start = int(rows[0].get("start") or 1)
    end = int(rows[0].get("end") or start)
    try:
        lines = (deps.repo_path / file).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        return {"error": f"could not read {file}: {type(exc).__name__}"}
    source = "\n".join(lines[max(0, start - 1):end])
    return {"entity": name, "file": file, "start_line": start,
            "end_line": end, "source": source}


def graph_summary(deps: GraphDeps) -> dict[str, Any]:
    counts = deps.client.run(
        "MATCH (e:CodeEntity {repo: $repo}) RETURN e.kind AS kind, count(e) AS count "
        "ORDER BY count DESC",
        repo=deps.repo_id,
    )
    rels = deps.client.run(
        "MATCH (s:CodeEntity {repo: $repo})-[r]->(t) "
        "RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC",
        repo=deps.repo_id,
    )
    return {"entity_counts": counts,
            "relationship_counts": {r["rel_type"]: r["count"] for r in rels}}


# Default integration markers. Language-neutral I/O surface names; override via config.
DEFAULT_INTEGRATION_MARKERS = [
    "db2", "ims", "mq", "vsam", "sql", "jdbc", "http", "rest", "grpc", "kafka",
    "s3", "redis", "queue", "socket", "file", "exec", "cics",
]


def entry_points(deps: GraphDeps, *, limit: int = 50) -> dict[str, Any]:
    """Heuristic, language-agnostic: callable entities with zero incoming CALLS."""
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        WHERE e.kind IN ['Function', 'Method', 'Module']
        OPTIONAL MATCH (e)<-[c:CALLS]-()
        WITH e, count(c) AS callers
        WHERE callers = 0
        RETURN e.qualified_name AS qualified_name, e.kind AS kind,
               e.file_path AS file_path
        ORDER BY e.qualified_name
        LIMIT $limit
        """,
        repo=deps.repo_id, limit=limit,
    )
    return {"entry_points": rows}


def integration_points(deps: GraphDeps, *, markers: list[str] | None = None,
                       limit: int = 50) -> dict[str, Any]:
    markers = markers or DEFAULT_INTEGRATION_MARKERS
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        WHERE e.is_external = true
           OR any(m IN $markers WHERE toLower(e.qualified_name) CONTAINS toLower(m))
        RETURN e.qualified_name AS qualified_name, e.kind AS kind,
               e.file_path AS file_path
        ORDER BY e.qualified_name
        LIMIT $limit
        """,
        repo=deps.repo_id, markers=markers, limit=limit,
    )
    return {"integration_points": rows}


def known_refs(deps: GraphDeps) -> set[str]:
    """Every valid evidence reference for the repo: entity qualified_names + file
    paths. Used by the judge to detect hallucinated references."""
    rows = deps.client.run(
        """
        MATCH (e:CodeEntity {repo: $repo})
        RETURN DISTINCT e.qualified_name AS qualified_name, e.file_path AS file_path
        """,
        repo=deps.repo_id,
    )
    refs: set[str] = set()
    for r in rows:
        if r.get("qualified_name"):
            refs.add(r["qualified_name"])
        if r.get("file_path"):
            refs.add(r["file_path"])
    return refs


def list_subsystems(deps: GraphDeps, *, max_clusters: int = 12) -> dict[str, Any]:
    node_rows = deps.client.run(
        "MATCH (e:CodeEntity {repo: $repo}) RETURN e.qualified_name AS qn",
        repo=deps.repo_id,
    )
    edge_rows = deps.client.run(
        """
        MATCH (a:CodeEntity {repo: $repo})-[:CALLS|IMPORTS|CONTAINS]->(b:CodeEntity {repo: $repo})
        RETURN a.qualified_name AS src, b.qualified_name AS dst
        """,
        repo=deps.repo_id,
    )
    nodes = [r["qn"] for r in node_rows if r.get("qn")]
    edges = [(r["src"], r["dst"]) for r in edge_rows if r.get("src") and r.get("dst")]
    subs = detect_subsystems(nodes, edges, max_clusters=max_clusters)
    return {"subsystems": [{"name": s.name, "members": s.members} for s in subs]}
