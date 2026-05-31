import pytest
from cobol_modernizer.planner.schema import Story, StoryDAG
from cobol_modernizer.planner.dag import topo_order, is_acyclic, CycleError


def _dag():
    return StoryDAG(repo_id="cardemo", stories=[
        Story(id="S1", title="Account view read path", seam="COACTVWC", depends_on=[]),
        Story(id="S2", title="Card xref ACL", seam="COCRDSLC", depends_on=["S1"]),
        Story(id="S3", title="Txn poster writer", seam="CBTRN02C", depends_on=["S1", "S2"]),
    ])


def test_acyclic_topo_order():
    order = topo_order(_dag())
    assert order.index("S1") < order.index("S2") < order.index("S3")
    assert is_acyclic(_dag()) is True


def test_cycle_rejected():
    bad = StoryDAG(repo_id="cardemo", stories=[
        Story(id="A", title="a", seam="X", depends_on=["B"]),
        Story(id="B", title="b", seam="Y", depends_on=["A"]),
    ])
    assert is_acyclic(bad) is False
    with pytest.raises(CycleError):
        topo_order(bad)


def test_unknown_dependency_rejected():
    bad = StoryDAG(repo_id="cardemo", stories=[
        Story(id="A", title="a", seam="X", depends_on=["GHOST"]),
    ])
    with pytest.raises(CycleError, match="unknown"):
        topo_order(bad)
