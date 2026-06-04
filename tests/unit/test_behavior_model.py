from __future__ import annotations

from cobol_modernizer.codegen.behavior_model import build_behavior_model
from cobol_modernizer.codegen.story_plan import StoryCodegenItem


def _item() -> StoryCodegenItem:
    return StoryCodegenItem(
        story_id="US-9",
        bounded_context="Posting",
        service_name="posting-service",
        acceptance_criteria_ids=["AC-1"],
        cobol_refs=["COTRN02C.cbl#L10-L80"],
        depends_on=[],
    )


def test_behavior_model_extracts_core_cobol_signals():
    source = """
       IF WS-AMOUNT > WS-CREDIT-LIMIT
          MOVE 'Y' TO WS-DECLINED-FLAG
       END-IF
       MOVE WS-AMOUNT TO TRN-AMOUNT
       COMPUTE WS-BALANCE = WS-BALANCE + WS-AMOUNT
       ADD WS-FEE TO WS-BALANCE
       READ TRANSACT-FILE
          INVALID KEY MOVE 'NF' TO WS-STATUS
       WRITE TRANSACT-REC
       EXEC CICS
          SEND MAP('TRNMAP') RESP(WS-RESP)
       END-EXEC
       CALL 'ABEND-HANDLER'
    """

    model = build_behavior_model(_item(), source)

    assert model["story_id"] == "US-9"
    assert model["cobol_refs"] == ["COTRN02C.cbl#L10-L80"]
    assert "IF WS-AMOUNT > WS-CREDIT-LIMIT" in model["conditions"]
    assert "'Y' -> WS-DECLINED-FLAG" in model["field_moves"]
    assert "WS-AMOUNT -> TRN-AMOUNT" in model["field_moves"]
    assert "WS-BALANCE = WS-BALANCE + WS-AMOUNT" in model["calculations"]
    assert "ADD WS-FEE TO WS-BALANCE" in model["calculations"]
    assert "READ TRANSACT-FILE" in model["io_operations"]
    assert "WRITE TRANSACT-REC" in model["io_operations"]
    assert any("INVALID KEY" in rule for rule in model["status_rules"])
    assert any("EXEC CICS" in op and "SEND MAP" in op for op in model["cics_operations"])
    assert model["calls"] == ["ABEND-HANDLER"]
    assert model["raw_signals_count"] > 0


def test_behavior_model_deduplicates_and_caps_signal_lists():
    source = "\n".join(
        [f"IF FIELD-{i} = 'Y'" for i in range(40)]
        + ["MOVE A TO B", "MOVE A TO B"]
    )

    model = build_behavior_model(_item(), source)

    assert len(model["conditions"]) == 24
    assert model["field_moves"] == ["A -> B"]
