from pathlib import Path
ROOT = Path(__file__).parents[2]


def test_compose_has_three_backends_and_gds():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "neo4j:" in text and "postgres:" in text and "minio:" in text
    assert "graph-data-science" in text  # GDS plugin enabled
    assert "NEO4J_PLUGINS" in text or "gds" in text.lower()
