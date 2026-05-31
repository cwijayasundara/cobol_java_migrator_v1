from cobol_modernizer.design.schema import ADR
from cobol_modernizer.design.adr import render_adr, default_adrs_for_writer_slice


def test_render_adr_is_markdown_with_standard_sections():
    adr = ADR(number=3, title="Legacy Mimic write-back",
              status="accepted", context="Un-migrated COBOL still reads ACCTFILE",
              decision="Serialize Java result to ACCOUNT-RECORD fixed-width bytes",
              consequences="COBOL estate keeps running; ACL owns the format",
              evidence_refs=["CBTRN02C.2800-UPDATE-ACCOUNT-REC", "ACCTDAT"])
    md = render_adr(adr)
    assert md.startswith("# ADR-0003: Legacy Mimic write-back")
    assert "## Status\naccepted" in md
    assert "## Decision" in md and "## Consequences" in md
    assert "CBTRN02C.2800-UPDATE-ACCOUNT-REC" in md  # lineage embedded


def test_default_adrs_for_writer_slice_cover_monolith_eps_and_mimic():
    adrs = default_adrs_for_writer_slice(
        slice_id="posting", owned_resources=["TRANSACT", "ACCTDAT"],
        evidence_refs=["CBTRN02C"])
    titles = [a.title.lower() for a in adrs]
    assert any("monolith" in t for t in titles)
    assert any("extract product lines" in t for t in titles)
    assert any("mimic" in t for t in titles)
    assert [a.number for a in adrs] == [1, 2, 3]
