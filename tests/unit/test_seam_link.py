from cobol_modernizer.equivalence.seam_link import resolve_source_seam, SeamRef


class FakeGraphOps:
    """Mimics agent.graph_ops read-only helpers used by the resolver."""
    def __init__(self, mapping): self._m = mapping
    def writers_of_data_item(self, qname):
        return self._m.get(qname, [])


def test_resolves_field_to_writing_paragraph():
    ops = FakeGraphOps({
        "CBACT01C.ACCT-CURR-BAL": [
            {"qualified_name": "CBACT01C.1300-POPUL-ACCT-RECORD",
             "kind": "Paragraph", "edge": "MOVES_TO",
             "file_path": "app/cbl/CBACT01C.cbl", "line": 218},
        ]
    })
    seam = resolve_source_seam(ops, program="CBACT01C", field="ACCT-CURR-BAL")
    assert isinstance(seam, SeamRef)
    assert seam.entity_qname == "CBACT01C.1300-POPUL-ACCT-RECORD"
    assert seam.edge_kind == "MOVES_TO"
    assert seam.file_path == "app/cbl/CBACT01C.cbl"
    assert seam.line == 218


def test_unresolved_field_falls_back_to_program_with_flag():
    ops = FakeGraphOps({})
    seam = resolve_source_seam(ops, program="CBACT01C", field="ACCT-CURR-BAL")
    assert seam.entity_qname == "CBACT01C"   # never invents; falls back to program
    assert seam.unresolved is True
