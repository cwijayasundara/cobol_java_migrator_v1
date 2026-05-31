from pathlib import Path

ROOT = Path(__file__).parents[2]
CI = ROOT / ".github" / "workflows" / "account-view-ci.yml"


def test_ci_builds_and_tests_the_generated_service():
    text = CI.read_text()
    assert "account-view-service" in text
    assert "mvn" in text and "test" in text
    assert "java-version: '25'" in text or 'java-version: "25"' in text
    assert "jacoco" in text.lower() or "coverage" in text.lower()
