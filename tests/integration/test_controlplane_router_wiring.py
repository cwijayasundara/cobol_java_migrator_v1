from cobol_modernizer.controlplane import controlplane_router


def test_router_exposes_all_cockpit_paths():
    paths = {r.path for r in controlplane_router.routes}
    expected = {
        "/api/workspaces", "/api/workspaces/{wid}",
        "/api/workspaces/{wid}/stages", "/api/workspaces/{wid}/gates",
        "/api/workspaces/{wid}/artifacts", "/api/workspaces/{wid}/artifacts/{aid}",
        "/api/workspaces/{wid}/runs", "/api/workspaces/{wid}/budget",
        "/api/gates/{gate_id}/approval",
        "/api/graph", "/api/entity/{qname}",
        "/api/workspaces/{wid}/runs/{run_id}/events",
    }
    assert expected <= paths
