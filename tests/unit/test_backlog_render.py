from cobol_modernizer.backlog.render import render_html
from cobol_modernizer.backlog.schema import AcceptanceCriterion, Backlog, Epic, UserStory


def test_render_html_includes_epics_stories_and_coverage():
    backlog = Backlog(
        repo_slug="carddemo-mini",
        epics=[Epic(id="EPIC-1", title="Transaction Posting", outcome="apply tx", story_ids=["US-1"])],
        stories=[UserStory(id="US-1", epic_id="EPIC-1", title="Post valid transaction",
                           actor="batch", narrative="As a batch I post.",
                           acceptance_criteria=[AcceptanceCriterion(id="AC-1", statement="balance updates")],
                           depends_on=[], evidence_refs=["CBPOST1M"])])
    html = render_html(backlog, {"coverage_ratio": 0.83})

    assert "<html" in html.lower()
    assert "Transaction Posting" in html
    assert "US-1" in html
    assert "Post valid transaction" in html
    assert "AC-1" in html
    assert "balance updates" in html
    assert "83" in html  # coverage percent


def test_render_html_escapes_special_characters():
    backlog = Backlog(
        repo_slug="repo<>&",
        epics=[Epic(id="EPIC-<1>", title="T&T", outcome="o<o", story_ids=[])],
        stories=[])
    html = render_html(backlog, {})
    assert "repo<>" not in html      # raw repo_slug must not appear unescaped
    assert "EPIC-<1>" not in html    # raw epic id must not appear unescaped
    assert "&lt;" in html            # something was escaped
