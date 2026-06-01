"""The cockpit control-plane router: local repo discovery (repos.py), workspace/
run/gate/artifact/budget + approval (workspaces.py), graph/entity (graph.py), and
the SSE run-events stream (events.py). api.py includes `controlplane_router` with
one line."""
from fastapi import APIRouter

from cobol_modernizer.controlplane.repos import router as _repos_router
from cobol_modernizer.controlplane.workspaces import router as _workspaces_router
from cobol_modernizer.controlplane.parse import router as _parse_router
from cobol_modernizer.controlplane.analysis import router as _analysis_router
from cobol_modernizer.controlplane.ask import router as _ask_router
from cobol_modernizer.controlplane.graph import router as _graph_router
from cobol_modernizer.controlplane.events import router as _events_router

controlplane_router = APIRouter()
controlplane_router.include_router(_repos_router)
controlplane_router.include_router(_workspaces_router)
controlplane_router.include_router(_parse_router)
controlplane_router.include_router(_analysis_router)
controlplane_router.include_router(_ask_router)
controlplane_router.include_router(_graph_router)
controlplane_router.include_router(_events_router)
