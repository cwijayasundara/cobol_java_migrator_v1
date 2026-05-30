import os
from cobol_modernizer.cost.tiering import resolve_model


def test_defaults_by_tier():
    assert resolve_model("enrichment").startswith("claude-haiku")
    assert resolve_model("brd") == "claude-sonnet-4-6"
    assert resolve_model("judge") == "claude-opus-4-8"
    assert resolve_model("unknown-role") == "claude-sonnet-4-6"


def test_per_role_env_override(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "claude-opus-test")
    assert resolve_model("judge") == "claude-opus-test"
