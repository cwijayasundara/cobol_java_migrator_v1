"""Read-only graph HTTP wrappers for the cockpit GraphView + entity drawer.
Calls CodeGraphQueries read methods; never writes to Neo4j.

If Neo4j is unreachable/misconfigured (down, wrong password, etc.) these return a
clean 503 instead of a 500 with a stack trace — so a graph outage degrades
gracefully and repeated cockpit polls don't spam tracebacks (or, for auth
failures, hammer Neo4j into a rate-limit lockout)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError

from cobol_modernizer.controlplane.deps import get_neo4j
from cobol_modernizer.queries import CodeGraphQueries

router = APIRouter(prefix="/api", tags=["controlplane-graph"])

# Neo4j connection/auth/query failures (ServiceUnavailable, AuthError, …) all
# derive from one of these two driver bases.
_NEO4J_ERRORS = (Neo4jError, DriverError)


@router.get("/graph")
def get_graph(repo: str | None = None, limit: int = 300,
              client=Depends(get_neo4j)) -> dict:
    try:
        return CodeGraphQueries(client).graph_overview(repo=repo, limit=limit)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")


@router.get("/entity/{qname}")
def get_entity(qname: str, client=Depends(get_neo4j)) -> dict:
    try:
        detail = CodeGraphQueries(client).entity_detail(qname)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity {qname} not found")
    return detail
