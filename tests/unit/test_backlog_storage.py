from cobol_modernizer.backlog.schema import AcceptanceCriterion, Backlog, Epic, UserStory
from cobol_modernizer.backlog.storage import BacklogStorage


class FakeNeo4j:
    def __init__(self):
        self.saved = {}
        self.version = 0

    def run(self, query, **params):
        if "CREATE (b:Backlog" in query:
            self.version += 1
            self.saved = dict(params, version=self.version)
            return [{"version": self.version}]
        if "RETURN b ORDER BY b.version DESC" in query:
            if not self.saved:
                return []
            return [{"b": self.saved}]
        return []


def _backlog():
    return Backlog(
        repo_slug="carddemo-mini",
        epics=[Epic(id="EPIC-1", title="Posting", outcome="apply", story_ids=["US-1"])],
        stories=[UserStory(id="US-1", epic_id="EPIC-1", title="Post", actor="batch",
                           narrative="n",
                           acceptance_criteria=[AcceptanceCriterion(id="AC-1", statement="s")],
                           evidence_refs=["CBPOST1M"])],
        evidence_map={"US-1": ["CBPOST1M"]})


def test_save_increments_version_and_serializes_json():
    neo = FakeNeo4j()
    out = BacklogStorage(neo).save(_backlog(), coverage={"coverage_ratio": 0.9},
                                   html="<h1>backlog</h1>", model="m")
    assert out.version == 1
    assert "US-1" in neo.saved["stories_json"]
    assert neo.saved["coverage_json"] == '{"coverage_ratio": 0.9}'


def test_get_latest_returns_node_or_none():
    neo = FakeNeo4j()
    assert BacklogStorage(neo).get_latest("carddemo-mini") is None
    BacklogStorage(neo).save(_backlog(), coverage={}, html="", model="")
    node = BacklogStorage(neo).get_latest("carddemo-mini")
    assert node["version"] == 1
