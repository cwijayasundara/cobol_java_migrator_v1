"""Shared size-adaptive budgets used by the BRD + codegen LLM stages."""
from cobol_modernizer.cost.scaling import turns_for, model_for_size
from cobol_modernizer.cost.tiering import HAIKU, SONNET


def test_turns_scale_and_clamp():
    assert turns_for(0, lo=14, hi=45) == 14          # floor
    assert turns_for(60, lo=14, hi=45) == 22         # 12 + 60//6
    assert turns_for(10_000, lo=14, hi=45) == 45     # cap
    assert turns_for(30, lo=20, hi=45) == 20         # floor wins
    assert turns_for(-5, lo=14, hi=45) == 14         # negatives don't underflow


def test_model_tiers_by_size_with_pin_override():
    assert model_for_size(5, threshold=25) == HAIKU       # small -> cheap/fast
    assert model_for_size(500, threshold=25) == SONNET    # large -> stronger
    assert model_for_size(5, threshold=25) != SONNET
    # an explicit pin always wins over auto-tiering
    assert model_for_size(5, threshold=25, pinned="claude-opus-4-8") == "claude-opus-4-8"
    assert model_for_size(9999, threshold=25, pinned="my-model") == "my-model"
