from fastapi.testclient import TestClient

from cobol_modernizer.api import app


def test_dark_launch_report_endpoint_returns_summary():
    client = TestClient(app)
    payload = {
        "inputs": ["00000000123"],
        "golden": {"00000000123": {"accountId": "00000000123", "activeStatus": "Y",
                   "currentBalance": "1234.56", "creditLimit": "5000.00",
                   "customerId": "000000042", "customerFirstName": "JANE",
                   "customerLastName": "DOE", "ficoScore": "720"}},
        "actual": {"00000000123": {"accountId": "00000000123", "activeStatus": "Y",
                   "currentBalance": "1234.5600", "creditLimit": "5000.00",
                   "customerId": "000000042", "customerFirstName": "JANE",
                   "customerLastName": "DOE  ", "ficoScore": "720"}},
    }
    r = client.post("/api/slice/dark-launch", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is True
    assert body["matched"] == 1


def test_select_slice_endpoint_picks_reader_only():
    client = TestClient(app)
    cands = [
        {"program": "COACTVWC", "fan_in": 1, "fan_out": 0, "reader_only": True,
         "writes": 0, "reads": 3, "score": 0.91},
        {"program": "COACTUPC", "fan_in": 3, "fan_out": 2, "reader_only": False,
         "writes": 2, "reads": 4, "score": 0.31},
    ]
    r = client.post("/api/slice/select", json={"candidates": cands})
    assert r.status_code == 200
    assert r.json()["program"] == "COACTVWC"
