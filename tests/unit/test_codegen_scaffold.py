from pathlib import Path
from cobol_modernizer.codegen.scaffold import scaffold_module


def test_scaffold_writes_pom_with_all_four_quality_plugins(tmp_path):
    root = scaffold_module(tmp_path, module="carddemo-posting",
                           base_package="com.cobolmodernizer.posting")
    pom = (root / "pom.xml").read_text()
    assert "spring-boot-starter" in pom and "<java.version>25</java.version>" in pom
    assert "spotbugs-maven-plugin" in pom
    assert "error_prone_core" in pom
    assert "maven-checkstyle-plugin" in pom
    assert "archunit-junit5" in pom


def test_scaffold_creates_main_and_test_source_roots(tmp_path):
    root = scaffold_module(tmp_path, module="carddemo-posting",
                           base_package="com.cobolmodernizer.posting")
    assert (root / "src/main/java/com/cobolmodernizer/posting").is_dir()
    assert (root / "src/test/java/com/cobolmodernizer/posting").is_dir()
    assert (root / "config/checkstyle.xml").exists()


def test_scaffold_is_idempotent(tmp_path):
    r1 = scaffold_module(tmp_path, module="m", base_package="com.x")
    r2 = scaffold_module(tmp_path, module="m", base_package="com.x")
    assert r1 == r2 and (r2 / "pom.xml").exists()
