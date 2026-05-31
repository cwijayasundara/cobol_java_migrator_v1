from cobol_modernizer.slice.slice_brd import build_slice_brd_prompt, SliceBrdInput


def test_prompt_is_scoped_to_one_program_and_its_io():
    inp = SliceBrdInput(
        program="COACTVWC",
        read_resources=[
            {"resource": "CXACAIX", "command": "READ", "intent": "read"},
            {"resource": "ACCTDAT", "command": "READ", "intent": "read"},
            {"resource": "CUSTDAT", "command": "READ", "intent": "read"},
        ],
        copybooks=["CVACT01Y", "CVACT03Y", "CVCUS01Y"],
    )
    prompt = build_slice_brd_prompt(inp)
    # scoped to ONE program
    assert "COACTVWC" in prompt
    assert "single program" in prompt.lower()
    # the slice's read resources are named so the agent reads only their slices
    assert "ACCTDAT" in prompt and "CXACAIX" in prompt and "CUSTDAT" in prompt
    # explicit instruction to use read-only graph tools, not whole files
    assert "get_source_slice" in prompt
    # required-vs-accidental behavior separation (outcome parity, not feature parity)
    assert "required" in prompt.lower() and "accidental" in prompt.lower()


def test_uses_brd_role_model(monkeypatch):
    monkeypatch.delenv("BRD_AGENT_MODEL", raising=False)
    from cobol_modernizer.slice.slice_brd import slice_brd_model
    assert slice_brd_model() == "claude-sonnet-4-6"  # 'brd' role tier
