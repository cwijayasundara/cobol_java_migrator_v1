from cobol_modernizer.design.context_map import assign_context_generic


class _Adapter:
    def __init__(self, writes): self._w = writes
    def writer_resources(self, program): return self._w.get(program, [])


def test_generic_context_named_from_dominant_resource():
    adapter = _Adapter({"CBACT01C": ["ACCT-MASTER", "ACCT-IDX"]})
    ctx = assign_context_generic(adapter, "CBACT01C")
    assert "ACCT" in ctx.upper()


def test_generic_context_stable_and_nonempty():
    adapter = _Adapter({"P": ["XREF"]})
    assert assign_context_generic(adapter, "P")
