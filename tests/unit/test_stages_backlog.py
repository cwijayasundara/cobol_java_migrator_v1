from cobol_modernizer.controlplane.stages import JOURNEY_STAGES


def test_backlog_stage_exists_between_blueprint_and_seams():
    keys = [s.key for s in JOURNEY_STAGES]
    assert keys.index("backlog") == keys.index("blueprint") + 1
    assert keys.index("backlog") == keys.index("seams") - 1


def test_ordinals_are_contiguous_and_unique():
    ords = [s.ordinal for s in JOURNEY_STAGES]
    assert ords == list(range(len(JOURNEY_STAGES)))
