from fastapi.testclient import TestClient
from cobol_modernizer.api import app

client = TestClient(app)


def test_flip_without_approval_is_refused():
    resp = client.post("/api/workspaces/w1/canary/flip", json={
        "slice_name": "account-view-service", "canary_pct": 10,
        "approval": None,
    })
    assert resp.status_code == 403
    assert "approval" in resp.json()["detail"].lower()


def test_flip_with_attributed_approval_records_gate():
    resp = client.post("/api/workspaces/w1/canary/flip", json={
        "slice_name": "account-view-service", "canary_pct": 10,
        "approval": {
            "decision": "approved",
            "approver_email": "lead@biz2bricks.ai",
            "approver_role": "lead_engineer",
            "risk_accepted": False,
            "rationale": "smoke+perf green, divergence 0",
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["canary_pct"] == 10
    assert body["gate"]["status"] == "passed"
    assert body["gate"]["approver_email"] == "lead@biz2bricks.ai"


def test_routing_exposes_weight_and_remaining_budget():
    resp = client.get("/api/workspaces/w1/routing?slice_name=account-view-service")
    assert resp.status_code == 200
    body = resp.json()
    assert "canary_pct" in body and "legacy_pct" in body
    assert "remaining_usd" in body
