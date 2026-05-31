from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
from cobol_modernizer.codegen.archrules import render_archunit_test


def _design():
    return ServiceDesign(slice_id="posting", deployment="modular_monolith",
        context=BoundedContext.transaction_processing,
        owned_resources=["TRANSACT", "ACCTDAT"],
        transition_pattern="extract_product_lines+legacy_mimic",
        components=["PostingService", "PostingRepository"],
        evidence_map={"DR-1": ["CBTRN02C"]})


def test_archunit_source_pins_layered_architecture_and_package():
    src = render_archunit_test(_design(), base_package="com.cobolmodernizer.posting")
    assert "@AnalyzeClasses(packages = \"com.cobolmodernizer.posting\")" in src
    assert "layeredArchitecture()" in src
    assert "Repository" in src and "Service" in src
    assert "noClasses()" in src  # forbids cross-layer leak
    assert src.strip().endswith("}")


def test_archunit_source_is_compilable_junit5_class():
    src = render_archunit_test(_design(), base_package="com.cobolmodernizer.posting")
    assert "import com.tngtech.archunit.junit.AnalyzeClasses;" in src
    assert "class ArchitectureTest" in src
