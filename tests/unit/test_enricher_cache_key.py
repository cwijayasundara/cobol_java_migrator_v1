from cobol_modernizer.agent import enricher
from cobol_modernizer.agent.enricher import (
    ENRICH_PROMPT_VERSION, enrichment_cache_key, should_enrich,
)

def test_cache_key_combines_source_hash_and_prompt_version():
    k = enrichment_cache_key(source_hash="abc123", prompt_version=ENRICH_PROMPT_VERSION)
    assert k == f"abc123:{ENRICH_PROMPT_VERSION}"

def test_should_skip_when_cache_key_matches():
    key = enrichment_cache_key(source_hash="abc123", prompt_version=ENRICH_PROMPT_VERSION)
    node = {"qualified_name": "CBACT01C", "enrich_cache_key": key}
    assert should_enrich(node, source_hash="abc123") is False

def test_should_enrich_when_source_changed():
    node = {"qualified_name": "CBACT01C", "enrich_cache_key": "old:1"}
    assert should_enrich(node, source_hash="newhash") is True

def test_should_enrich_when_prompt_version_bumped(monkeypatch):
    # Node was enriched under prompt_version "1" against the same source hash.
    node = {"qualified_name": "CBACT01C",
            "enrich_cache_key": enrichment_cache_key(source_hash="abc123",
                                                      prompt_version="1")}
    # Bump the effective prompt version to "2": the node must be re-enriched.
    monkeypatch.setattr(enricher, "ENRICH_PROMPT_VERSION", "2")
    assert should_enrich(node, source_hash="abc123") is True
