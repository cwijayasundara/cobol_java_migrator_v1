from cobol_modernizer.controlplane.stages import JOURNEY_STAGES, gate_key_for


def test_canonical_stages_in_order():
    assert [s.key for s in JOURNEY_STAGES] == [
        "outcome", "intake", "parse", "graph", "explore",
        "blueprint", "backlog", "seams", "plan", "domain", "design", "build", "verify",
    ]
    assert [s.ordinal for s in JOURNEY_STAGES] == list(range(13))


def test_gate_key_mapping():
    assert gate_key_for("blueprint") == "brd_groundedness"
    assert gate_key_for("build") == "code"
    assert gate_key_for("intake") is None
    assert gate_key_for("domain") is None   # Domain Design has no hard gate
