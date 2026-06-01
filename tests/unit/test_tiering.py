from cobol_modernizer.cost.tiering import _ROLE_ENV, GLOBAL_ENV, resolve_model


def _clear_model_env(monkeypatch):
    """Isolate from any model overrides leaked into os.environ (e.g. a populated
    .env loaded via dotenv when an earlier test built a Neo4jClient)."""
    monkeypatch.delenv(GLOBAL_ENV, raising=False)
    for env in _ROLE_ENV.values():
        monkeypatch.delenv(env, raising=False)


def test_defaults_by_tier(monkeypatch):
    _clear_model_env(monkeypatch)
    assert resolve_model("enrichment").startswith("claude-haiku")
    assert resolve_model("brd") == "claude-sonnet-4-6"
    assert resolve_model("judge") == "claude-opus-4-8"
    assert resolve_model("unknown-role") == "claude-sonnet-4-6"


def test_per_role_env_override(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("JUDGE_MODEL", "claude-opus-test")
    assert resolve_model("judge") == "claude-opus-test"
