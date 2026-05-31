import pytest

from cobol_modernizer.slice.stories import (
    Story, StoryCluster, assert_acyclic, story_model,
)


def _cluster(deps):
    return StoryCluster(
        program="COACTVWC",
        stories=[
            Story(id="S1", title="Decode COBOL account/customer/xref records (ACL)",
                  depends_on=[], evidence_map={"S1": ["CVACT01Y", "CVACT03Y"]}),
            Story(id="S2", title="Assemble AccountView from xref->acct->cust reads",
                  depends_on=["S1"], evidence_map={"S2": ["COACTVWC.9000-READ-ACCT"]}),
            Story(id="S3", title="Expose GET /api/accounts/{id}/view",
                  depends_on=["S2"], evidence_map={"S3": ["COACTVWC"]}),
        ],
    )


def test_story_cluster_is_acyclic():
    c = _cluster(None)
    assert_acyclic(c)  # no raise
    order = c.topological_order()
    assert order.index("S1") < order.index("S2") < order.index("S3")


def test_cycle_is_rejected():
    c = StoryCluster(program="X", stories=[
        Story(id="A", title="a", depends_on=["B"], evidence_map={"A": ["x"]}),
        Story(id="B", title="b", depends_on=["A"], evidence_map={"B": ["y"]}),
    ])
    with pytest.raises(ValueError, match="cycle"):
        assert_acyclic(c)


def test_every_story_carries_evidence():
    c = StoryCluster(program="X", stories=[
        Story(id="A", title="a", depends_on=[], evidence_map={}),
    ])
    with pytest.raises(ValueError, match="evidence"):
        assert_acyclic(c)


def test_story_role_model():
    assert story_model() == "claude-sonnet-4-6"  # 'story' role tier
