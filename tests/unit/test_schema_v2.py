from cobol_modernizer import schema


def test_v2_rel_kinds_are_mergeable():
    # every v2 RelKind value must appear in the merge-allowed set
    for k in ("READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"):
        assert k in schema.MERGEABLE_REL_TYPES


def test_seam_indexes_present():
    joined = "\n".join(schema.INDEXES)
    assert "DataItem" in joined            # DataItem label is indexed
    assert "e.kind" in joined


def test_dataitem_label_in_entity_labels():
    assert "DataItem" in schema.ENTITY_LABELS
