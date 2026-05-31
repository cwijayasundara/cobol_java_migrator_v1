from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from claude_agent_sdk import tool, create_sdk_mcp_server, ToolAnnotations

from cobol_modernizer.agent import graph_ops as ops
from cobol_modernizer.agent.deps import GraphDeps

SERVER_NAME = "graph"

# Fully-qualified names to pre-approve in allowed_tools.
GRAPH_TOOL_NAMES = [
    f"mcp__{SERVER_NAME}__{n}"
    for n in (
        "list_subsystems", "get_entity", "find_entities", "neighbors",
        "get_source_slice", "entry_points", "integration_points", "graph_summary",
        # v2 seam-discovery tools (read-only; seam math stays in Cypher)
        "data_accesses", "reader_writer_classification", "seam_candidates",
    )
]

_READ_ONLY = ToolAnnotations(readOnlyHint=True)


def _ok(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _make_handlers(deps: GraphDeps) -> dict[str, Callable[[dict], Awaitable[dict]]]:
    """Plain async handlers (no decorator) so tests can call op logic directly."""
    async def list_subsystems(args):
        return _ok(ops.list_subsystems(deps, max_clusters=int(args.get("max_clusters", 12))))

    async def get_entity(args):
        return _ok(ops.get_entity(deps, args["name"]))

    async def find_entities(args):
        return _ok(ops.find_entities(deps, kind=args.get("kind"),
                                     prefix=args.get("prefix"),
                                     limit=int(args.get("limit", 50))))

    async def neighbors(args):
        return _ok(ops.neighbors(deps, args["name"], edge=args["edge"],
                                 direction=args.get("direction", "out"),
                                 depth=int(args.get("depth", 1)),
                                 limit=int(args.get("limit", 50))))

    async def get_source_slice(args):
        return _ok(ops.get_source_slice(deps, args["name"]))

    async def entry_points(args):
        return _ok(ops.entry_points(deps, limit=int(args.get("limit", 50))))

    async def integration_points(args):
        return _ok(ops.integration_points(deps, markers=args.get("markers"),
                                          limit=int(args.get("limit", 50))))

    async def graph_summary(args):
        return _ok(ops.graph_summary(deps))

    async def data_accesses(args):
        return _ok(ops.data_accesses(deps, args["name"],
                                     intent=args.get("intent"),
                                     limit=int(args.get("limit", 50))))

    async def reader_writer_classification(args):
        return _ok(ops.reader_writer_classification(deps, args["resource"]))

    async def seam_candidates(args):
        return _ok(ops.seam_candidates(deps, limit=int(args.get("limit", 20))))

    return {
        "list_subsystems": list_subsystems, "get_entity": get_entity,
        "find_entities": find_entities, "neighbors": neighbors,
        "get_source_slice": get_source_slice, "entry_points": entry_points,
        "integration_points": integration_points, "graph_summary": graph_summary,
        "data_accesses": data_accesses,
        "reader_writer_classification": reader_writer_classification,
        "seam_candidates": seam_candidates,
    }


def build_graph_server(deps: GraphDeps, *, advisor=None, advisor_max_uses: int = 3):
    """Build the in-process MCP server exposing graph navigation tools, all bound to
    this repo's GraphDeps. All tools are read-only. If `advisor` (an AdvisorBackend)
    is given, a consult_advisor tool is added with a shared per-server use budget."""
    h = _make_handlers(deps)

    tools = [
        tool("list_subsystems",
             "List the repo's subsystems (graph communities). Returns name + member "
             "entity ids. Call this first to plan which subsystem to analyse.",
             {"max_clusters": int}, annotations=_READ_ONLY)(h["list_subsystems"]),
        tool("get_entity", "Look up one entity by qualified or simple name.",
             {"name": str}, annotations=_READ_ONLY)(h["get_entity"]),
        tool("find_entities",
             "Find entities. Optional 'kind' (Class/Function/Method/Module) and "
             "'prefix' filters; both optional, read with care.",
             {"kind": str, "prefix": str, "limit": int},
             annotations=_READ_ONLY)(h["find_entities"]),
        tool("neighbors",
             "Traverse the graph from an entity. 'edge' one of "
             "CALLS/IMPORTS/CONTAINS/INHERITS/DECORATES/RAISES or v2 "
             "READS/WRITES/EXECUTES_CICS/EXECUTES_SQL/MOVES_TO/GO_TO; 'direction' "
             "out/in/both; 'depth' 1-5.",
             {"name": str, "edge": str, "direction": str, "depth": int, "limit": int},
             annotations=_READ_ONLY)(h["neighbors"]),
        tool("get_source_slice",
             "Return ONLY the source lines for one entity (start_line..end_line). "
             "Use this to read code instead of whole files.",
             {"name": str}, annotations=_READ_ONLY)(h["get_source_slice"]),
        tool("entry_points", "Heuristic entry points (entities with no callers).",
             {"limit": int}, annotations=_READ_ONLY)(h["entry_points"]),
        tool("integration_points",
             "External/IO touch points (DB, MQ, files, HTTP, ...). Optional 'markers' "
             "list to override the default IO name registry.",
             {"markers": list, "limit": int},
             annotations=_READ_ONLY)(h["integration_points"]),
        tool("graph_summary", "Entity and relationship counts for the repo.",
             {}, annotations=_READ_ONLY)(h["graph_summary"]),
        tool("data_accesses",
             "List a program's file/VSAM/CICS/SQL accesses as {resource, kind, "
             "intent, mode}. Optional 'intent' filter (read|write). Read-only.",
             {"name": str, "intent": str, "limit": int},
             annotations=_READ_ONLY)(h["data_accesses"]),
        tool("reader_writer_classification",
             "Classify programs touching a resource into readers vs writers "
             "(Fowler's pivotal seam split), computed in Cypher. Read-only.",
             {"resource": str}, annotations=_READ_ONLY)(h["reader_writer_classification"]),
        tool("seam_candidates",
             "Ranked strangler-fig seam candidates (reader-only first; fan-in/out, "
             "side-effect aware). Scoring is pure Cypher — no LLM. Read-only.",
             {"limit": int}, annotations=_READ_ONLY)(h["seam_candidates"]),
    ]
    if advisor is not None:
        from cobol_modernizer.agent.advisor import build_advisor_tool
        tools.append(build_advisor_tool(advisor, advisor_max_uses))
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=tools)
