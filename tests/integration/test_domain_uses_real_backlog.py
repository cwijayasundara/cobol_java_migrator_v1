import json

from cobol_modernizer.controlplane import analysis


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_BACKLOG" in query or "(b:Backlog)" in query:
            return [{"b": {"version": 1,
                           "stories_json": json.dumps([{"id": "US-1", "title": "Post valid tx"}]),
                           "epics_json": "[]"}}]
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return []
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        return []


def test_backlog_json_for_domain_reads_persisted_stories():
    payload = analysis._backlog_json_for_domain(FakeNeo4j(), "carddemo-mini")
    assert "US-1" in payload
    assert "Post valid tx" in payload


def test_backlog_json_for_domain_empty_when_none():
    class Empty:
        def run(self, q, **k):
            return []
    assert analysis._backlog_json_for_domain(Empty(), "carddemo-mini") == ""
