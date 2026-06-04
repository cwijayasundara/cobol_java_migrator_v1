def test_list_and_get_workspaces(cp_client):
    rows = cp_client.get("/api/workspaces").json()
    assert len(rows) == 1 and rows[0]["repo_slug"] == "aws-mf-carddemo"
    one = cp_client.get("/api/workspaces/ws-1").json()
    assert one["created_by"] == "cwijay@biz2bricks.ai"
    assert cp_client.get("/api/workspaces/nope").status_code == 404


def test_stages_gates_artifacts_runs_budget(cp_client):
    stages = cp_client.get("/api/workspaces/ws-1/stages").json()
    assert [s["stage_key"] for s in stages][:2] == ["outcome", "intake"]
    assert len(stages) == 13
    gates = cp_client.get("/api/workspaces/ws-1/gates").json()
    assert gates[0]["gate_key"] == "brd_groundedness"
    arts = cp_client.get("/api/workspaces/ws-1/artifacts").json()
    assert arts[0]["kind"] == "brd"
    assert cp_client.get("/api/workspaces/ws-1/artifacts/art-brd-1").json()["version"] == 1
    runs = cp_client.get("/api/workspaces/ws-1/runs").json()
    assert runs[0]["id"] == "run-1" and runs[0]["total_cost_usd"] == 0.42
    budget = cp_client.get("/api/workspaces/ws-1/budget").json()
    assert budget["cap_usd"] == 50.0 and budget["spent_usd"] == 18.42


def test_work_units_progress_filters_and_counts(cp_client):
    all_units = cp_client.get("/api/workspaces/ws-1/work-units").json()
    assert all_units["total"] == 3
    assert all_units["counts"] == {"succeeded": 1, "running": 1, "failed": 1}
    assert all_units["by_stage"]["domain-design"] == {"succeeded": 1, "running": 1}
    assert all_units["by_stage"]["technical-design"] == {"failed": 1}

    domain = cp_client.get("/api/workspaces/ws-1/work-units",
                           params={"stage": "domain-design"}).json()
    assert domain["total"] == 2
    assert {u["unit_type"] for u in domain["units"]} == {
        "decomposition", "tactical-aggregate"}

    running = cp_client.get("/api/workspaces/ws-1/work-units",
                            params={"status": "running"}).json()
    assert running["total"] == 1
    assert running["units"][0]["id"] == "wu-domain-aggregate"
    assert running["units"][0]["timeout_s"] == 300.0


def test_work_units_unknown_workspace_404(cp_client):
    assert cp_client.get("/api/workspaces/nope/work-units").status_code == 404


def test_create_workspace_seeds_stages_and_budget(cp_client):
    created = cp_client.post("/api/workspaces", json={
        "name": "Loans", "repo_slug": "aws-mf-loans", "created_by": "lead@biz2bricks.ai",
    }).json()
    wid = created["id"]
    assert created["name"] == "Loans" and created["status"] == "active"
    stages = cp_client.get(f"/api/workspaces/{wid}/stages").json()
    assert len(stages) == 13 and stages[0]["status"] == "running"
    budget = cp_client.get(f"/api/workspaces/{wid}/budget").json()
    assert budget["cap_usd"] == 50.0 and budget["spent_usd"] == 0.0


def test_create_workspace_is_idempotent_per_repo_slug(cp_client):
    body = {"name": "Mini", "repo_slug": "carddemo-mini", "created_by": "x@y.z"}
    first = cp_client.post("/api/workspaces", json=body).json()
    second = cp_client.post("/api/workspaces", json=body).json()
    assert first["id"] == second["id"]  # same workspace, not a duplicate
    slugs = [w["repo_slug"] for w in cp_client.get("/api/workspaces").json()]
    assert slugs.count("carddemo-mini") == 1


def test_start_run_creates_running_run(cp_client):
    run = cp_client.post("/api/workspaces/ws-1/runs", json={
        "stage_key": "blueprint", "role": "brd", "started_by": "lead@biz2bricks.ai",
    }).json()
    assert run["status"] == "running" and run["role"] == "brd"
    assert run["stage_id"] == "stg-blueprint" and run["model"]


def test_approval_transitions_gate(cp_client):
    res = cp_client.post("/api/gates/gate-brd/approval", json={
        "decision": "approved", "approver_email": "lead@biz2bricks.ai",
        "approver_role": "lead_engineer", "risk_accepted": False,
        "rationale": "groundedness cleared",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "approved" and body["approver_email"] == "lead@biz2bricks.ai"
    gates = cp_client.get("/api/workspaces/ws-1/gates").json()
    assert next(g for g in gates if g["id"] == "gate-brd")["status"] == "passed"


def test_waive_requires_risk_accepted(cp_client):
    res = cp_client.post("/api/gates/gate-brd/approval", json={
        "decision": "waived_with_risk", "approver_email": "lead@biz2bricks.ai",
        "approver_role": "risk_officer", "risk_accepted": False, "rationale": "no",
    })
    assert res.status_code == 400


def test_approval_unknown_gate_404(cp_client):
    res = cp_client.post("/api/gates/nope/approval", json={
        "decision": "approved", "approver_email": "x@y.z",
        "approver_role": "lead_engineer", "risk_accepted": False, "rationale": "ok",
    })
    assert res.status_code == 404
