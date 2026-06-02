import json

from cobol_modernizer.controlplane import build as bd


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_DOMAIN_DESIGN" in query:
            return [{"d": {"version": 1, "rating": "high", "contexts_json": "[]", "designs_json": "[]"}}]
        if "HAS_TECHNICAL_DESIGN" in query:
            return [{"t": {"version": 1, "services_json": '[{"name":"posting-service","story_ids":["US-1"]}]'}}]
        if "HAS_BACKLOG" in query:
            return [{"b": {"version": 1, "stories_json": '[{"id":"US-1","title":"Post valid transaction"}]'}}]
        return []


def test_codegen_brief_includes_backlog_and_technical_design():
    brd_node = {
        "version": 1,
        "rating": "high",
        "sections": '[{"title":"Functional Requirements","requirements":[{"id":"FR-1","text":"Post transaction"}]}]',
    }

    brief = json.loads(bd._codegen_brief(FakeNeo4j(), "carddemo-mini", brd_node))

    assert "domain_design" in brief
    assert brief["backlog"]["stories"][0]["id"] == "US-1"
    assert brief["technical_design"]["services"][0]["name"] == "posting-service"
