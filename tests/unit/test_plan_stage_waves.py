from cobol_modernizer.controlplane import analysis


class _FakeNeo:
    def run(self, q, **kw):
        return []


def test_run_plan_includes_delivery_waves(monkeypatch):
    cands = [
        {"program": "P1", "reads": ["R"], "writes": [], "score": {"weighted": 0.9}},
        {"program": "P2", "reads": [], "writes": ["R"], "score": {"weighted": 0.5}},
        {"program": "P3", "reads": [], "writes": [], "score": {"weighted": 0.7}},
    ]
    monkeypatch.setattr(analysis, "rank_candidates", lambda *a, **k: cands)

    class _WS:
        repo_slug = "demo"
    monkeypatch.setattr(analysis, "_workspace", lambda s, w: _WS())
    monkeypatch.setattr(analysis, "_mark_passed", lambda *a, **k: None)

    class _Sess:
        def flush(self):
            pass
    out = analysis.run_plan("wid", session=_Sess(), neo4j=_FakeNeo())
    assert out["acyclic"] is True
    assert "delivery_waves" in out
    waves = out["delivery_waves"]
    assert "S1" in waves[0] and "S2" in waves[0]
    flat = [s for w in waves for s in w]
    assert sorted(flat) == ["S1", "S2", "S3"]
