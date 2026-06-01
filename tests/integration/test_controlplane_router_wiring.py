from cobol_modernizer.controlplane import controlplane_router


def test_router_exposes_all_cockpit_paths():
    paths = {r.path for r in controlplane_router.routes}
    expected = {
        "/api/workspaces", "/api/workspaces/{wid}",
        "/api/workspaces/{wid}/stages", "/api/workspaces/{wid}/gates",
        "/api/workspaces/{wid}/artifacts", "/api/workspaces/{wid}/artifacts/{aid}",
        "/api/workspaces/{wid}/runs", "/api/workspaces/{wid}/budget",
        "/api/workspaces/{wid}/graph-summary",
        "/api/workspaces/{wid}/parse",
        "/api/workspaces/{wid}/seams",
        "/api/workspaces/{wid}/plan",
        "/api/workspaces/{wid}/ask",
        "/api/gates/{gate_id}/approval",
        "/api/repos",
        "/api/graph", "/api/entity/{qname}",
        "/api/workspaces/{wid}/runs/{run_id}/events",
    }
    assert expected <= paths
