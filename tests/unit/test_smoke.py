from cobol_modernizer.deploy.smoke import SmokeRunner, Probe


class FakeClient:
    def __init__(self, responses):  # path -> status_code
        self._r = responses

    def get(self, url):
        for path, code in self._r.items():
            if url.endswith(path):
                return type("R", (), {"status_code": code})()
        return type("R", (), {"status_code": 404})()


def test_all_probes_pass():
    client = FakeClient({"/actuator/health": 200, "/api/accounts/1": 200})
    runner = SmokeRunner(base_url="http://localhost:8080", client=client)
    res = runner.run([
        Probe(path="/actuator/health", expect=200),
        Probe(path="/api/accounts/1", expect=200),
    ], slice_name="account-view-service")
    assert res.passed is True
    assert res.endpoints_ok == 2 and res.endpoints_total == 2


def test_health_failure_fails_gate():
    client = FakeClient({"/actuator/health": 503, "/api/accounts/1": 200})
    runner = SmokeRunner(base_url="http://localhost:8080", client=client)
    res = runner.run([
        Probe(path="/actuator/health", expect=200, is_health=True),
        Probe(path="/api/accounts/1", expect=200),
    ], slice_name="s")
    assert res.health_ok is False
    assert res.passed is False
    assert "/actuator/health" in res.failures[0]
