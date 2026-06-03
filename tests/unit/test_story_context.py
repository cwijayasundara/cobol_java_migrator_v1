from __future__ import annotations

import pytest

from cobol_modernizer.backlog.schema import AcceptanceCriterion, UserStory
from cobol_modernizer.codegen.story_context import (
    StoryContextPack,
    build_story_context,
)
from cobol_modernizer.codegen.story_plan import StoryCodegenItem
from cobol_modernizer.domain.schema import Aggregate
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    PersistenceDesign,
    TechnicalService,
)


def _story() -> UserStory:
    return UserStory(
        id="US-1",
        epic_id="E-1",
        title="Post a transaction",
        actor="cardholder",
        narrative="As a cardholder I want to post a transaction so my balance updates.",
        brd_requirement_ids=["BR-1"],
        acceptance_criteria=[
            AcceptanceCriterion(id="AC-1", statement="Balance increases by amount."),
            AcceptanceCriterion(id="AC-2", statement="Reject if over credit limit."),
        ],
        depends_on=["US-0"],
        evidence_refs=["COTRN02C.cbl#L10-L40"],
        context="Posting",
    )


def _item() -> StoryCodegenItem:
    return StoryCodegenItem(
        story_id="US-1",
        bounded_context="Posting",
        service_name="posting-service",
        acceptance_criteria_ids=["AC-1", "AC-2"],
        cobol_refs=["COTRN02C.cbl#L10-L40"],
        depends_on=["US-0"],
    )


def _aggregate() -> Aggregate:
    return Aggregate(
        name="Transaction",
        root_entity="Transaction",
        invariants=["amount > 0", "amount <= creditLimit"],
        methods=["post()", "reverse()"],
    )


def _service() -> TechnicalService:
    return TechnicalService(
        name="posting-service",
        bounded_context="Posting",
        deployment="microservice",
        story_ids=["US-1"],
        api_contracts=[
            ApiContract(
                name="postTxn",
                method="POST",
                path="/transactions",
                request_model="PostTxnRequest",
                response_model="PostTxnResponse",
            )
        ],
        persistence=[
            PersistenceDesign(
                resource="TRANSACT",
                access_pattern="repository",
                owner_service="posting-service",
            )
        ],
    )


def _build(**overrides):
    kwargs = dict(
        item=_item(),
        story=_story(),
        service=_service(),
        aggregate=_aggregate(),
        brd_requirements=["BR-1: Transactions must update balances."],
        completed_summaries=["US-0: account opened, balance initialized."],
        source_pack="COTRN02C.cbl\nMOVE WS-AMT TO WS-BAL.\n",
    )
    kwargs.update(overrides)
    return build_story_context(**kwargs)


# -- Step 1: content presence --------------------------------------------------


def test_pack_is_story_context_pack():
    pack = _build()
    assert isinstance(pack, StoryContextPack)
    assert pack.story_id == "US-1"


def test_pack_includes_story_title_narrative_and_acceptance_criteria():
    pack = _build()
    text = pack.render()
    assert "Post a transaction" in text
    assert "balance updates" in text
    assert "Balance increases by amount." in text
    assert "Reject if over credit limit." in text


def test_pack_includes_completed_dependency_summaries():
    pack = _build()
    text = pack.render()
    assert "US-0: account opened, balance initialized." in text


def test_pack_includes_ddd_aggregate_invariants_and_methods():
    pack = _build()
    text = pack.render()
    assert "Transaction" in text
    assert "amount <= creditLimit" in text
    assert "post()" in text


def test_pack_includes_technical_service_api_and_persistence():
    pack = _build()
    text = pack.render()
    assert "posting-service" in text
    assert "/transactions" in text
    assert "TRANSACT" in text


def test_pack_includes_brd_requirements():
    pack = _build()
    text = pack.render()
    assert "Transactions must update balances." in text


def test_pack_includes_cobol_source_snippets():
    pack = _build()
    text = pack.render()
    assert "MOVE WS-AMT TO WS-BAL." in text


# -- Missing mappings handled gracefully --------------------------------------


def test_missing_aggregate_omits_section_no_error():
    pack = _build(aggregate=None)
    text = pack.render()
    assert "post()" not in text
    assert pack.aggregate_name == ""


def test_missing_service_omits_section_no_error():
    pack = _build(service=None)
    text = pack.render()
    assert "/transactions" not in text
    assert pack.service_name == ""


def test_missing_source_omits_section_no_error():
    pack = _build(source_pack="")
    text = pack.render()
    assert "MOVE WS-AMT TO WS-BAL." not in text


# -- Step 2: char limits ------------------------------------------------------


def test_render_truncated_to_max_chars():
    pack = _build(brd_requirements=["x" * 100000])
    text = pack.render()
    assert len(text) <= 24000


def test_render_respects_env_override_max_chars(monkeypatch):
    monkeypatch.setenv("STORY_CONTEXT_MAX_CHARS", "500")
    pack = _build(brd_requirements=["y" * 100000])
    text = pack.render()
    assert len(text) <= 500


def test_source_section_truncated_to_source_max_chars():
    big = "Z" * 50000
    pack = _build(source_pack=big, max_chars=1_000_000)
    text = pack.render()
    # The COBOL source contribution is capped well below its 50k input.
    assert text.count("Z") <= 12000


def test_source_section_respects_env_override(monkeypatch):
    monkeypatch.setenv("STORY_SOURCE_MAX_CHARS", "100")
    big = "Z" * 50000
    pack = _build(source_pack=big, max_chars=1_000_000)
    text = pack.render()
    assert text.count("Z") <= 100


def test_explicit_args_override_env(monkeypatch):
    monkeypatch.setenv("STORY_CONTEXT_MAX_CHARS", "999999")
    pack = _build(brd_requirements=["q" * 100000], max_chars=300)
    text = pack.render()
    assert len(text) <= 300


# -- Step 3: stable hashing ---------------------------------------------------


def test_identical_inputs_produce_identical_hash():
    assert _build().context_hash == _build().context_hash
    assert len(_build().context_hash) == 64


def test_changing_story_text_changes_hash():
    base = _build().context_hash
    other = _story()
    other.narrative = "different narrative"
    assert _build(story=other).context_hash != base


def test_changing_acceptance_criterion_changes_hash():
    base = _build().context_hash
    other = _story()
    other.acceptance_criteria[0].statement = "totally different AC"
    assert _build(story=other).context_hash != base


def test_changing_aggregate_changes_hash():
    base = _build().context_hash
    other = _aggregate()
    other.invariants.append("new invariant")
    assert _build(aggregate=other).context_hash != base


def test_changing_service_changes_hash():
    base = _build().context_hash
    other = _service()
    other.api_contracts[0].path = "/different"
    assert _build(service=other).context_hash != base


def test_changing_brd_changes_hash():
    base = _build().context_hash
    assert _build(brd_requirements=["BR-1: changed text."]).context_hash != base


def test_changing_source_changes_hash():
    base = _build().context_hash
    assert _build(source_pack="DIFFERENT SOURCE").context_hash != base


def test_hash_uses_pre_truncation_content():
    # Two packs whose rendered text both saturate the cap but whose REAL source
    # differs must still hash differently (hash over pre-truncation content).
    a = _build(source_pack="A" * 50000)
    b = _build(source_pack="B" * 50000)
    assert a.context_hash != b.context_hash


def test_changing_completed_summaries_changes_hash():
    base = _build().context_hash
    assert _build(completed_summaries=["US-0: something else."]).context_hash != base


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
