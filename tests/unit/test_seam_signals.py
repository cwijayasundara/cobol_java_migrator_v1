from cobol_modernizer.seam.signals import raw_signals_for_program


class FakeClient:
    def __init__(self, mapping): self.mapping = mapping
    def run(self, query, **params):
        for key, rows in self.mapping.items():
            if key in query:
                return rows
        return []


def test_reader_only_program_signals():
    client = FakeClient({
        "// fan_in":            [{"fan_in": 2, "is_entry": True}],
        "// max_fan_in":        [{"max_fan_in": 4}],
        "// touched_resources": [{"resource": "ACCTFILE", "intent": "read", "shared": True, "exclusive": False},
                                 {"resource": "CUSTFILE", "intent": "read", "shared": False, "exclusive": True}],
        "// goto_count":        [{"goto_count": 0}],
        "// billing_audit":     [{"hits": 0}],
        "// churn":             [{"churn": 0, "max_churn": 10}],
    })
    sig = raw_signals_for_program(client, repo="cardemo", program="COACTVWC")
    assert sig.risk == 0.0                 # reader, no billing, no churn
    assert sig.testability == 1.0          # reader_only, goto=0
    assert 0.0 < sig.isolation < 1.0       # 1 shared of 2 touched -> 0.5
    assert sig.data_ownership == 0.5       # 1 exclusive of 2
    assert sig.business == 0.75            # (fan_in 2 / max 4)=0.5 + entry 0.25 cap -> 0.75


def test_writer_program_has_risk():
    client = FakeClient({
        "// fan_in":            [{"fan_in": 0, "is_entry": False}],
        "// max_fan_in":        [{"max_fan_in": 4}],
        "// touched_resources": [{"resource": "ACCTFILE", "intent": "write", "shared": True, "exclusive": False}],
        "// goto_count":        [{"goto_count": 6}],
        "// billing_audit":     [{"hits": 1}],
        "// churn":             [{"churn": 10, "max_churn": 10}],
    })
    sig = raw_signals_for_program(client, repo="cardemo", program="CBTRN02C")
    assert sig.risk == 1.0                 # writer .5 + billing .3 + churn .2
    assert sig.testability < 0.4           # writer + goto penalty
