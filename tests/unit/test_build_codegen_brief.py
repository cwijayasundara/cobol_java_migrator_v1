"""The codegen brief must carry concrete, assertable behavior — the BRD's actual
requirement text AND the persisted DDD/OO DomainDesign (bounded contexts +
aggregates/invariants/api surface). Metadata alone (version/rating) starves the
TDD agent: it emits code but no failing test. See build._codegen_brief."""
import json

from cobol_modernizer.controlplane import build as bd


_BRD_NODE = {
    "version": 3,
    "rating": "high",
    "sections": json.dumps([
        {"title": "Posting", "body_markdown": "Debit the account on each posted txn.",
         "requirements": [{"id": "FR-1", "text": "Reject overlimit transactions"}]},
    ]),
}

_DESIGN_NODE = {
    "version": 2,
    "rating": "high",
    "contexts_json": json.dumps([
        {"name": "Posting", "business_capability": "Apply transactions",
         "member_programs": ["CBTRN02C"], "owned_resources": ["ACCTFILE"]},
    ]),
    "designs_json": json.dumps([
        {"context": "Posting", "api_surface": "POST /accounts/{id}/transactions",
         "aggregates": [{"name": "Account", "root_entity": "Account",
                         "invariants": ["balance must not exceed credit limit"],
                         "methods": ["post(txn)"]}]},
    ]),
}


class _FakeNeo4j:
    def __init__(self, design_node=None):
        self.design_node = design_node

    def run(self, query, **params):
        if "HAS_DOMAIN_DESIGN" in query:
            return [{"d": self.design_node}] if self.design_node else []
        return []


def test_brief_includes_brd_requirements_and_domain_design():
    brief = json.loads(bd._codegen_brief(_FakeNeo4j(_DESIGN_NODE), "carddemo", _BRD_NODE))
    assert brief["repo_id"] == "carddemo"
    # BRD requirement text is present (not just version/rating metadata).
    blob = json.dumps(brief)
    assert "Reject overlimit transactions" in blob
    assert "Debit the account on each posted txn." in blob
    # The DDD/OO design's assertable behavior is present.
    assert "domain_design" in brief
    assert "balance must not exceed credit limit" in blob  # aggregate invariant
    assert "POST /accounts/{id}/transactions" in blob       # api surface


def test_brief_without_domain_design_still_carries_requirements():
    brief = json.loads(bd._codegen_brief(_FakeNeo4j(None), "carddemo", _BRD_NODE))
    assert "Reject overlimit transactions" in json.dumps(brief)
    # No design persisted yet -> omitted, but the brief is still richer than metadata.
    assert "domain_design" not in brief


def test_brief_is_not_bare_metadata():
    """Regression: the old brief was {repo_id, version, rating} only — which starved
    the agent into emitting code with no test. Guard that we never ship that again."""
    brief = json.loads(bd._codegen_brief(_FakeNeo4j(_DESIGN_NODE), "carddemo", _BRD_NODE))
    assert set(brief) != {"repo_id", "version", "rating"}
