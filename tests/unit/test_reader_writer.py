from cobol_modernizer.seam.reader_writer import (
    classify_program, classify_resource, is_identity_drift_writer,
)


class FakeClient:
    """Returns canned rows keyed by a substring of the query."""
    def __init__(self, rows_by_key): self.rows_by_key = rows_by_key
    def run(self, query, **params):
        for key, rows in self.rows_by_key.items():
            if key in query:
                return [r for r in rows if all(r.get(k) == v for k, v in params.items()
                                               if k in r)]
        return []


def test_coactvwc_is_reader_only():
    client = FakeClient({"accesses_for_program": [
        {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
        {"program": "COACTVWC", "resource": "CUSTFILE", "intent": "read"},
    ]})
    result = classify_program(client, repo="cardemo", program="COACTVWC")
    assert result["writes"] == []
    assert set(result["reads"]) == {"ACCTFILE", "CUSTFILE"}
    assert result["reader_only"] is True


def test_cbtrn02c_is_identity_drift_writer():
    # CBTRN02C REWRITEs ACCTFILE; COACTVWC also reads ACCTFILE -> shared writer.
    client = FakeClient({
        "accesses_for_program": [
            {"program": "CBTRN02C", "resource": "ACCTFILE", "intent": "write"},
            {"program": "CBTRN02C", "resource": "TRANSACT", "intent": "write"},
        ],
        "readers_of_resource": [
            {"resource": "ACCTFILE", "reader": "COACTVWC"},
            {"resource": "ACCTFILE", "reader": "CBACT01C"},
        ],
    })
    assert is_identity_drift_writer(client, repo="cardemo", program="CBTRN02C") is True


def test_pure_reader_is_not_identity_drift_writer():
    client = FakeClient({"accesses_for_program": [
        {"program": "COACTVWC", "resource": "ACCTFILE", "intent": "read"},
    ]})
    assert is_identity_drift_writer(client, repo="cardemo", program="COACTVWC") is False
