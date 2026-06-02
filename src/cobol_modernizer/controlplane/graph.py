"""Read-only graph HTTP wrappers for the cockpit GraphView + entity drawer.
Calls CodeGraphQueries read methods; never writes to Neo4j.

If Neo4j is unreachable/misconfigured (down, wrong password, etc.) these return a
clean 503 instead of a 500 with a stack trace — so a graph outage degrades
gracefully and repeated cockpit polls don't spam tracebacks (or, for auth
failures, hammer Neo4j into a rate-limit lockout)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Workspace
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


@router.get("/graph/neighbors")
def get_graph_neighbors(id: str, repo: str | None = None, limit: int = 50,
                        client=Depends(get_neo4j)) -> dict:
    """One-hop neighbors of `id` (qualified_name), shaped like /graph — backs the
    cockpit's double-click-to-expand. `repo` scopes neighbors to the same repo."""
    try:
        return CodeGraphQueries(client).neighbors_of(id, repo=repo, limit=limit)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")


@router.get("/workspaces/{wid}/graph-summary")
def graph_summary(wid: str, session: Session = Depends(get_session),
                  client=Depends(get_neo4j)) -> dict:
    """Cheap COUNT-only graph stats for the workspace's repo (for the Outcome
    overview). entities=0 means the repo hasn't been parsed yet."""
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    try:
        kinds = client.run(
            "MATCH (n:CodeEntity {repo:$r}) RETURN n.kind AS kind, count(*) AS c",
            r=ws.repo_slug)
        rels = client.run(
            "MATCH (:CodeEntity {repo:$r})-[x]->(:CodeEntity {repo:$r}) "
            "RETURN count(x) AS c", r=ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    return {
        "repo_slug": ws.repo_slug,
        "entities": sum(int(r["c"]) for r in kinds),
        "relationships": int(rels[0]["c"]) if rels else 0,
        "by_kind": {r["kind"]: int(r["c"]) for r in kinds},
    }


@router.get("/entity/{qname}")
def get_entity(qname: str, client=Depends(get_neo4j)) -> dict:
    try:
        detail = CodeGraphQueries(client).entity_detail(qname)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity {qname} not found")
    return detail
