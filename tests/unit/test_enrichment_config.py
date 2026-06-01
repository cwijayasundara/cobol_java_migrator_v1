from cobol_modernizer.enrichment.config import enrich_model, enrich_timeout_s
from cobol_modernizer.cost.tiering import SONNET


def test_enrich_model_defaults_to_sonnet(monkeypatch):
    for k in ("SEAM_ENRICH_MODEL", "PLAN_ENRICH_MODEL", "DESIGN_ENRICH_MODEL",
              "COBOL_MOD_LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert enrich_model("seams") == SONNET
    assert enrich_model("plan") == SONNET
    assert enrich_model("design") == SONNET


def test_per_stage_env_overrides(monkeypatch):
    monkeypatch.setenv("SEAM_ENRICH_MODEL", "claude-haiku-4-5-20251001")
    assert enrich_model("seams") == "claude-haiku-4-5-20251001"


def test_global_pin_applies_when_no_stage_env(monkeypatch):
    monkeypatch.delenv("PLAN_ENRICH_MODEL", raising=False)
    monkeypatch.setenv("COBOL_MOD_LLM_MODEL", "claude-opus-4-8")
    assert enrich_model("plan") == "claude-opus-4-8"


def test_timeout_default_and_override(monkeypatch):
    monkeypatch.delenv("SEAMS_ENRICH_TIMEOUT_S", raising=False)
    assert enrich_timeout_s("seams") == 180.0
    monkeypatch.setenv("SEAMS_ENRICH_TIMEOUT_S", "30")
    assert enrich_timeout_s("seams") == 30.0
