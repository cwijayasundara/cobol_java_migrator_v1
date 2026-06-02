from cobol_modernizer.domain.decompose import build_decomposition_prompt


def test_decomposition_prompt_includes_backlog_stories():
    prompt = build_decomposition_prompt(
        brd_text="FR-1: Post valid transactions",
        graph_summary={"programs": ["CBPOST1M"]},
        backlog_json='{"stories":[{"id":"US-1","title":"Post valid transaction"}]}',
    )

    assert "FR-1: Post valid transactions" in prompt
    assert "US-1" in prompt
    assert "Post valid transaction" in prompt
