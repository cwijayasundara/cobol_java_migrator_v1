from cobol_modernizer.controlplane.enrichment_store import EnrichmentStorage


class _FakeClient:
    """Emulates the :Enrichment save/get_latest with server-side per-(repo,kind) versioning."""
    def __init__(self):
        self.saved: list[dict] = []

    def run(self, query, **params):
        if "CREATE (e:Enrichment" in query:
            version = len([s for s in self.saved
                           if s["repo_slug"] == params["repo_slug"]
                           and s["kind"] == params["kind"]]) + 1
            row = dict(params)
            row["version"] = version
            self.saved.append(row)
            return [{"version": version}]
        if "ORDER BY e.version DESC" in query:
            rows = [s for s in self.saved
                    if s["repo_slug"] == params["repo_slug"] and s["kind"] == params["kind"]]
            return [{"e": rows[-1]}] if rows else []
        return []


def test_roundtrip_versioning_and_kind_isolation():
    store = EnrichmentStorage(_FakeClient())
    assert store.get_latest("r", "seams") is None

    assert store.save("r", "seams", {"narratives": {"x": 1}}) == 1
    assert store.get_latest("r", "seams") == {"narratives": {"x": 1}}

    # re-running (refresh) bumps the version and the latest reflects the new payload
    assert store.save("r", "seams", {"narratives": {"x": 2}}) == 2
    assert store.get_latest("r", "seams") == {"narratives": {"x": 2}}

    # kinds are isolated
    store.save("r", "plan", {"waves": [["S1"]]})
    assert store.get_latest("r", "plan") == {"waves": [["S1"]]}
    assert store.get_latest("r", "seams") == {"narratives": {"x": 2}}
