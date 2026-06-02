from cobol_modernizer.domain.inputs import graph_coupling_summary


class _FakeClient:
    def __init__(self, rows_by_marker):
        self._rows = rows_by_marker

    def run(self, query, **params):
        for marker, rows in self._rows.items():
            if marker in query:
                return rows
        return []


def test_summary_assembles_writers_and_cross_reads():
    client = _FakeClient({
        "// writers": [{"program": "P1", "writes": ["R1"]},
                       {"program": "P2", "writes": ["R2"]}],
        "// cross_reads": [{"reader": "P2", "resource": "R1", "writer": "P1"}],
        "// calls": [{"caller": "P2", "callee": "P1"}],
        "// co_change": [{"a": "P1", "b": "P2", "times": 5}],
    })
    s = graph_coupling_summary(client, "repo", top_n=10, cochange_floor=2)
    assert {w["program"] for w in s["writers"]} == {"P1", "P2"}
    assert s["cross_reads"] == [{"reader": "P2", "resource": "R1", "writer": "P1"}]
    assert s["calls"][0]["caller"] == "P2"
    assert s["co_change"][0]["times"] == 5
