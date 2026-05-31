from cobol_modernizer.slice.design import (
    choose_transition_pattern, DesignDecision, design_model,
)


def test_reader_only_chooses_cdc_replica_with_acl_for_dark_launch():
    d = choose_transition_pattern(reader_only=True, writes=0)
    assert isinstance(d, DesignDecision)
    assert d.production_pattern == "CDC/replica"
    assert d.dark_launch_pattern == "captured-VSAM ACL"
    assert "no identity drift" in d.rationale.lower()


def test_writer_routes_to_extract_product_lines_and_is_out_of_scope():
    import pytest
    with pytest.raises(ValueError, match="writer slice is Phase 5"):
        choose_transition_pattern(reader_only=False, writes=2)


def test_design_role_is_opus():
    assert design_model() == "claude-opus-4-8"  # 'design' role tier
