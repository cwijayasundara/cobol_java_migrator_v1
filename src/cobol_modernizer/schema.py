from __future__ import annotations

# v2 graph vocabulary (Phase 1). DataItem is a CodeEntity label like Program/Paragraph.
ENTITY_LABELS = [
    "Program", "Section", "Paragraph", "Copybook", "DataItem", "External",
]

# Relationship types the ingestion MERGE accepts (v1 + v2). Used to guard the
# `%(rel_type)s` interpolation in MERGE_RELATIONSHIP against arbitrary input.
MERGEABLE_REL_TYPES = {
    "CALLS", "CONTAINS", "IMPORTS",                                  # v1
    "READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL",              # v2 IO
    "MOVES_TO", "GO_TO",                                             # v2 data/control flow
}

CONSTRAINTS = [
    # qualified_name is unique PER REPO (composite), not globally — two repos may
    # each define a program named CBACT01C without colliding.
    "CREATE CONSTRAINT entity_repo_qname IF NOT EXISTS FOR (e:CodeEntity) REQUIRE (e.repo, e.qualified_name) IS UNIQUE",
    "CREATE CONSTRAINT file_repo_path IF NOT EXISTS FOR (f:File) REQUIRE (f.repo, f.path) IS UNIQUE",
    "CREATE CONSTRAINT author_email IF NOT EXISTS FOR (a:Author) REQUIRE a.email IS UNIQUE",
    "CREATE CONSTRAINT brd_id IF NOT EXISTS FOR (b:BRD) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT domain_design_id IF NOT EXISTS FOR (d:DomainDesign) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT enrichment_id IF NOT EXISTS FOR (e:Enrichment) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT repo_slug IF NOT EXISTS FOR (r:Repository) REQUIRE r.slug IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX entity_kind IF NOT EXISTS FOR (e:CodeEntity) ON (e.kind)",
    "CREATE INDEX entity_file IF NOT EXISTS FOR (e:CodeEntity) ON (e.file_path)",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:CodeEntity) ON (e.simple_name)",
    "CREATE INDEX entity_layer IF NOT EXISTS FOR (e:CodeEntity) ON (e.semantic_layer)",
    "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS FOR (e:CodeEntity) ON EACH [e.simple_name, e.qualified_name, e.docstring]",
    "CREATE INDEX brd_repo IF NOT EXISTS FOR (b:BRD) ON (b.repo_id)",
    "CREATE INDEX brd_version IF NOT EXISTS FOR (b:BRD) ON (b.version)",
    # v2 seam-discovery support
    "CREATE INDEX entity_dataitem IF NOT EXISTS FOR (e:DataItem) ON (e.qualified_name)",
    "CREATE INDEX reads_resource IF NOT EXISTS FOR ()-[r:READS]-() ON (r.resource)",
    "CREATE INDEX writes_resource IF NOT EXISTS FOR ()-[r:WRITES]-() ON (r.resource)",
    "CREATE INDEX cics_resource IF NOT EXISTS FOR ()-[r:EXECUTES_CICS]-() ON (r.resource)",
    "CREATE INDEX sql_resource IF NOT EXISTS FOR ()-[r:EXECUTES_SQL]-() ON (r.resource)",
]

CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"

MERGE_ENTITY = """
MERGE (e:CodeEntity {repo: $repo, qualified_name: $qualified_name})
SET e += $props,
    e:%(label)s
"""

LINK_FILES_FOR_REPO = """
MATCH (m:CodeEntity {repo: $slug})
WHERE m.kind = 'Module' AND m.file_path IS NOT NULL
MERGE (f:File {repo: $slug, path: m.file_path})
MERGE (m)-[:DEFINED_IN]->(f)
RETURN count(DISTINCT f) AS file_count
"""

DELETE_FILES_FOR_REPO = "MATCH (f:File {repo: $slug}) DETACH DELETE f"

MERGE_RELATIONSHIP = """
MATCH (src:CodeEntity {repo: $repo, qualified_name: $source_qname})
MATCH (tgt:CodeEntity {repo: $repo, qualified_name: $target_qname})
MERGE (src)-[r:%(rel_type)s]->(tgt)
SET r += $props
"""

MERGE_RELATIONSHIP_TO_UNRESOLVED = """
MATCH (src:CodeEntity {repo: $repo, qualified_name: $source_qname})
MERGE (tgt:CodeEntity {repo: $repo, qualified_name: $target_qname})
ON CREATE SET tgt.kind = 'External', tgt:External
MERGE (src)-[r:%(rel_type)s]->(tgt)
SET r += $props
"""

MERGE_AUTHOR = """
MERGE (a:Author {email: $email})
SET a.name = $name,
    a.commit_count = $commit_count
"""

MERGE_AUTHORED_BY = """
MATCH (e:CodeEntity {file_path: $file_path})
MATCH (a:Author {email: $email})
WHERE e.kind IN ['Module', 'File']
MERGE (e)-[r:AUTHORED_BY]->(a)
SET r.rank = $rank
"""

MERGE_CO_CHANGE = """
MATCH (a:CodeEntity {qualified_name: $qname_a})
MATCH (b:CodeEntity {qualified_name: $qname_b})
WHERE a.kind = 'Module' AND b.kind = 'Module'
MERGE (a)-[r:CO_CHANGED_WITH]-(b)
SET r.times = $times,
    r.confidence = $confidence
"""

# --- Content-hash manifest persistence (incremental re-ingest) ---
# The manifest (repo-relative path -> source_hash) is stored as a JSON string on
# the per-repo Repository node, so an unchanged re-ingest re-pays ~0 parse cost.
SAVE_MANIFEST = """
MERGE (r:Repository {slug: $slug})
SET r.manifest_json = $manifest_json
"""

LOAD_MANIFEST = """
MATCH (r:Repository {slug: $slug})
RETURN r.manifest_json AS manifest_json
"""
