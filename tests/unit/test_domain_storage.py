from cobol_modernizer.domain.schema import DomainDesign, BoundedContextDecl, TopologyDecision
from cobol_modernizer.controlplane.domain import DomainDesignStorage


class _FakeClient:
    """Emulates the :DomainDesign save/get_latest: server-side incrementing version."""
    def __init__(self):
        self.saved: list[dict] = []

    def run(self, query, **params):
        if "CREATE (d:DomainDesign" in query:
            version = len(self.saved) + 1            # coalesce(max(prev.version),0)+1
            row = dict(params)
            row["version"] = version
            self.saved.append(row)
            return [{"version": version}]
        if "ORDER BY d.version DESC" in query:
            return [{"d": self.saved[-1]}] if self.saved else []
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


def test_save_increments_version_on_refine():
    client = _FakeClient()
    store = DomainDesignStorage(client)
    store.save(_dd(), html="<v1>")
    dd2 = store.save(_dd(), html="<v2>")
    assert dd2.version == 2
    assert store.get_latest("r")["version"] == 2
