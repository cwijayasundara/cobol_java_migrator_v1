def test_core_modules_import():
    from cobol_modernizer import parser, neo4j_client, schema, git_analyzer
    assert hasattr(parser, "parse_directory")
    assert hasattr(neo4j_client, "Neo4jClient")
