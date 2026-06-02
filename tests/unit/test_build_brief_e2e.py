import json

from cobol_modernizer.controlplane import build as bd


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_DOMAIN_DESIGN" in query or "(d:DomainDesign)" in query:
            return [{"d": {"version": 1, "rating": "high", "contexts_json": "[]", "designs_json": "[]"}}]
        if "HAS_TECHNICAL_DESIGN" in query or "(t:TechnicalDesign)" in query:
            return [{"t": {"version": 1, "services_json": json.dumps([{"name": "posting-service"}])}}]
        if "HAS_BACKLOG" in query or "(b:Backlog)" in query:
            return [{"b": {"version": 1, "epics_json": "[]",
                           "stories_json": json.dumps([{"id": "US-1", "title": "Post"}])}}]
        return []


def test_codegen_brief_contains_backlog_and_technical_design():
    brd_node = {"version": 1, "rating": "high",
                "sections": json.dumps([{"title": "Functional",
                    "requirements": [{"id": "FR-1", "text": "Post tx"}]}])}
    brief = json.loads(bd._codegen_brief(FakeNeo4j(), "carddemo-mini", brd_node))
    assert brief["backlog"]["stories"][0]["id"] == "US-1"
    assert brief["technical_design"]["services"][0]["name"] == "posting-service"
