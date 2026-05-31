"""Read-only graph HTTP wrappers for the cockpit GraphView + entity drawer.
Calls CodeGraphQueries read methods; never writes to Neo4j."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cobol_modernizer.controlplane.deps import get_neo4j
from cobol_modernizer.queries import CodeGraphQueries

router = APIRouter(prefix="/api", tags=["controlplane-graph"])


@router.get("/graph")
def get_graph(repo: str | None = None, limit: int = 300,
              client=Depends(get_neo4j)) -> dict:
    return CodeGraphQueries(client).graph_overview(repo=repo, limit=limit)


@router.get("/entity/{qname}")
def get_entity(qname: str, client=Depends(get_neo4j)) -> dict:
    detail = CodeGraphQueries(client).entity_detail(qname)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity {qname} not found")
    return detail
