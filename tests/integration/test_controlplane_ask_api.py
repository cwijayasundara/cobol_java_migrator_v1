"""Ask endpoint: grounded-context build + LLM answer, with a fake Neo4j (canned
rows) and an injected fake LLM (no real Anthropic call)."""
import asyncio

from cobol_modernizer.controlplane.ask import answer_question, _build_context


class _FakeNeo4j:
    """Returns canned rows per query, matched by a substring of the Cypher."""
    def __init__(self, by_fragment):
        self._by = by_fragment

    def run(self, query, **params):
        for frag, rows in self._by.items():
            if frag in query:
                return rows
        return []


def _populated():
    return _FakeNeo4j({
        "RETURN n.kind AS kind": [{"kind": "Program", "c": 2}, {"kind": "Copybook", "c": 1}],
        "WHERE p.kind = 'Program'": [
            {"program": "CBPOST1M", "edges": ["WRITES ACCTFILE", "WRITES TRANFILE", "CALLS CBVALDTM"]},
            {"program": "CBACT01M", "edges": ["READS ACCTFILE"]},
        ],
        "c.kind='Copybook'": [{"name": "ACCOUNT-RECORD"}],
    })


def test_build_context_includes_io_and_counts():
    facts, n = _build_context(_populated(), "carddemo-mini")
    assert n == 3
    assert "CBPOST1M: WRITES ACCTFILE" in facts
    assert "READS ACCTFILE" in facts
    assert "Copybooks: ACCOUNT-RECORD" in facts


def test_answer_question_calls_llm_with_grounded_facts():
    captured = {}

    async def fake_llm(system, prompt):
        captured["system"] = system
        captured["prompt"] = prompt
        return "CBPOST1M writes ACCTFILE."

    out = asyncio.run(answer_question(_populated(), "carddemo-mini",
                                      "which programs write ACCTFILE?", llm=fake_llm))
    assert out["grounded"] is True and out["context_entities"] == 3
    assert out["answer"] == "CBPOST1M writes ACCTFILE."
    assert "WRITES ACCTFILE" in captured["prompt"]          # facts were grounded in
    assert "which programs write ACCTFILE?" in captured["prompt"]


def test_answer_question_short_circuits_when_repo_not_parsed():
    called = {"llm": False}

    async def fake_llm(system, prompt):
        called["llm"] = True
        return "should not be called"

    empty = _FakeNeo4j({"RETURN n.kind AS kind": []})
    out = asyncio.run(answer_question(empty, "carddemo-mini", "anything?", llm=fake_llm))
    assert out["grounded"] is False and out["context_entities"] == 0
    assert "Parse stage" in out["answer"]
    assert called["llm"] is False                            # no LLM spend on empty graph
