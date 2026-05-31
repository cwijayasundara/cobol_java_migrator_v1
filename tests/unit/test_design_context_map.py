from cobol_modernizer.design.context_map import (
    assign_context, owned_resources, RESOURCE_CONTEXT,
)


class FakeDeps:
    """Stands in for GraphDeps; exposes only what context_map needs."""
    def __init__(self, writes):
        self._writes = writes  # program -> [resource,...] (WRITES/REWRITE intent)

    def writer_resources(self, program):
        return self._writes.get(program, [])


def test_resource_context_table_maps_carddemo_files():
    assert RESOURCE_CONTEXT["ACCTDAT"] == "account_management"
    assert RESOURCE_CONTEXT["TRANSACT"] == "transaction_processing"
    assert RESOURCE_CONTEXT["CARDDAT"] == "card_management"


def test_owned_resources_are_writer_resources_only():
    deps = FakeDeps({"CBTRN02C": ["TRANSACT", "ACCTDAT", "TCATBAL"]})
    assert owned_resources(deps, "CBTRN02C") == ["ACCTDAT", "TCATBAL", "TRANSACT"]


def test_assign_context_by_dominant_owned_resource():
    # CBTRN02C writes TRANSACT(txn-proc), ACCTDAT(acct), TCATBAL(txn-proc):
    # transaction_processing dominates (2 vs 1).
    deps = FakeDeps({"CBTRN02C": ["TRANSACT", "ACCTDAT", "TCATBAL"]})
    assert assign_context(deps, "CBTRN02C") == "transaction_processing"


def test_assign_context_no_writes_raises():
    import pytest
    deps = FakeDeps({})
    with pytest.raises(ValueError, match="no owned"):
        assign_context(deps, "COACTVWC")  # a reader-only program owns no data
