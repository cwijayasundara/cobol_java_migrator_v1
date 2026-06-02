from cobol_modernizer.domain.schema import DomainDesign, BoundedContextDecl, TopologyDecision
from cobol_modernizer.controlplane.domain import DomainDesignStorage


class _FakeClient:
    """Records CREATE params and serves them back for get_latest."""
    def __init__(self):
        self.saved = None

    def run(self, query, **params):
        if "CREATE (d:DomainDesign" in query:
            self.saved = dict(params)
            return [{"version": params["version"]}]
        if "coalesce(max(prev.version), 0) + 1" in query:
            return [{"version": 1}]
        if "ORDER BY d.version DESC" in query:
            return [{"d": self.saved}] if self.saved else []
        return []


def _dd():
    return DomainDesign(repo_slug="r", contexts=[BoundedContextDecl(
        name="A", business_capability="c", member_programs=["P"],
        topology=TopologyDecision(deployment="module", score=0.1))], designs=[])


def test_save_assigns_version_and_serializes():
    client = _FakeClient()
    store = DomainDesignStorage(client)
    dd = store.save(_dd(), html="<html></html>")
    assert dd.version == 1
    latest = store.get_latest("r")
    assert latest["version"] == 1
    assert "A" in latest["contexts_json"]
