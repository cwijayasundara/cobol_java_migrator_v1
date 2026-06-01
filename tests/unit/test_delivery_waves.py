from cobol_modernizer.planner.dag import delivery_waves, topo_order
from cobol_modernizer.planner.schema import Story, StoryDAG


def _dag(*edges_by_story):
    # edges_by_story: (id, [deps]) tuples
    return StoryDAG(repo_id="r",
                    stories=[Story(id=i, title=i, seam=i, depends_on=list(d))
                             for i, d in edges_by_story])


def test_independent_stories_share_wave_one():
    dag = _dag(("S1", []), ("S2", []), ("S3", []))
    assert delivery_waves(dag) == [["S1", "S2", "S3"]]


def test_dependents_land_in_later_waves():
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S2"]))
    assert delivery_waves(dag) == [["S1"], ["S2"], ["S3"]]


def test_diamond_dag():
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S1"]), ("S4", ["S2", "S3"]))
    assert delivery_waves(dag) == [["S1"], ["S2", "S3"], ["S4"]]


def test_waves_agree_with_topo_order():
    dag = _dag(("S1", []), ("S2", ["S1"]), ("S3", ["S1"]), ("S4", ["S2", "S3"]))
    waves = delivery_waves(dag)
    flat = [s for w in waves for s in w]
    assert sorted(flat) == sorted(topo_order(dag))
    pos = {s: wi for wi, w in enumerate(waves) for s in w}
    for s in dag.stories:
        for dep in s.depends_on:
            assert pos[dep] < pos[s.id]
