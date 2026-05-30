# Foundation & Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Lock the shared, cross-cutting decisions every downstream phase plan (01–08) builds on: the greenfield project layout, the single versioned Python↔Java JSON contract (`schemaVersion: 2`), the Postgres run/audit/version schema, model-tiering + cost-cap/kill-switch policy, the read-only MCP graph tool surface, the port-map from `source_graphs_v1.0`, and project conventions. This is the **barrier** the other 8 plans depend on — its decisions are binding and MUST be referenced verbatim.

**Architecture:** Deterministic Neo4j code-graph (source of truth) + bounded agents reading via read-only Cypher MCP tools + hard human gates persisted in Postgres. A ProLeap-based Java extractor emits the **only** Python↔Java coupling: a single versioned JSON contract. Seam math runs in Cypher/Neo4j-GDS, never in prompts. Token economy is a budgeted first-class concern (model tiering, prompt caching, 4-bucket token tracking, hard per-workspace/per-run cost caps with kill-switch). Outcome parity via dual-run, not feature parity.

**Tech Stack (pinned):**
- **Python 3.12** managed by **uv** (`uv` ≥ 0.5); analysis core, FastAPI control plane, agent harness, MCP graph server.
- **Java 25 (LTS)** + **Maven 3.9** for the ProLeap COBOL extractor and (later) generated Spring Boot 3.3 / Spring Boot test harness.
- **Next.js 15** (App Router) + **React 19** + **Tailwind CSS 3.4** + TypeScript 5.6 for the web cockpit.
- **Neo4j 5.x Community/Enterprise + Graph Data Science (GDS) 2.x** — code graph ONLY.
- **PostgreSQL 16** — run/audit/version/RBAC state ONLY.
- **GnuCOBOL 3.2** — Equivalence Lab batch execution (Phase 3+).
- **MinIO** (S3-compatible) object store — source snapshots, line slices, generated projects, golden files.
- **Anthropic Claude Agent SDK** `claude-agent-sdk==0.2.87` (verified to support `output_format`, `setting_sources`, `tools`, `ResultMessage.structured_output`, `ResultMessage.usage`, `ResultMessage.total_cost_usd`).
- Test: **pytest** (Python), **JUnit 5** (Java), **Vitest + Playwright** (web).

**Python package name decision:** the partial impl uses `code_context_graph`. The greenfield project renames the top-level package to **`cobol_modernizer`** (clearer product intent; avoids confusion with the old tree). All ported modules move under `src/cobol_modernizer/...`. Import rewrites `code_context_graph` → `cobol_modernizer` are part of every PORT/ADAPT task in downstream plans.

---

## File Structure

Everything below is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── IMPLEMENTATION_PLAN.md                         # master plan (exists; authoritative)
├── README.md                                      # quickstart (created in Task 1)
├── pyproject.toml                                 # uv/pip project, package = cobol_modernizer (Task 1)
├── uv.lock                                         # uv lockfile (Task 1)
├── .python-version                                # "3.12" (Task 1)
├── .env.example                                   # all env vars: models, costs, neo4j, pg, minio (Task 4)
├── docker-compose.yml                             # neo4j(+GDS) + postgres + minio (Task 6)
├── docs/
│   ├── cobol-modernization-platform-design.html   # exists
│   ├── ui-agentic-architecture.html               # exists
│   └── plans/
│       ├── 00-foundation-and-architecture.md      # THIS FILE
│       └── 01..08-*.md                             # downstream phase plans (other runs)
├── src/cobol_modernizer/                          # Python analysis core (renamed from code_context_graph)
│   ├── __init__.py
│   ├── models.py                                  # CodeEntity/CodeRelationship/ParseResult + EntityKind/RelKind (PORT+EXTEND v2)
│   ├── parser.py                                  # COBOL-agnostic generic parser dispatch (PORT-AS-IS)
│   ├── schema.py                                  # Neo4j CONSTRAINTS/INDEXES/MERGE Cypher (PORT+EXTEND v2 labels/rels)
│   ├── neo4j_client.py                            # Neo4j driver wrapper (PORT-AS-IS)
│   ├── ingestion.py                               # repo → ParseResult → Neo4j (ADAPT: content-hash incremental)
│   ├── queries.py                                 # parametrized read-only Cypher (PORT+EXTEND seam queries)
│   ├── api.py                                     # FastAPI control plane (ADAPT: stages/approvals/cost/SSE)
│   ├── contract/
│   │   ├── __init__.py
│   │   └── cobol_contract.py                      # schemaVersion=2 loader + version-mismatch-raises (REBUILD from mapping.py)
│   ├── persistence/                               # NEW — Postgres run/audit/version state
│   │   ├── __init__.py
│   │   ├── db.py                                  # SQLAlchemy engine/session
│   │   ├── tables.py                              # Workspace/JourneyStage/AgentRun/Artifact/Gate/Approval/Budget
│   │   └── migrations/                            # Alembic migrations
│   │       └── 0001_initial.py
│   ├── cost/                                      # NEW — token economy policy module
│   │   ├── __init__.py
│   │   ├── tiering.py                             # resolve_model(role) (PORT+EXTEND roles) + caching prefixes
│   │   └── policy.py                              # CostPolicy: 4-bucket tracking, cap check, kill-switch
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── harness.py                             # SdkAgentRunner tools=[]/setting_sources=[]/json_schema (PORT-AS-IS)
│   │   ├── deps.py                                # GraphDeps (PORT-AS-IS)
│   │   ├── graph_ops.py                           # Cypher op functions behind tools (PORT+EXTEND)
│   │   ├── graph_tools.py                         # MCP graph server: read-only tools (PORT+EXTEND v2 tools)
│   │   ├── advisor.py                             # worker+advisor budget tool (PORT-AS-IS)
│   │   ├── brd_judge.py                           # groundedness gate (PORT-AS-IS)
│   │   └── enricher.py                            # per-node summaries (ADAPT)
│   ├── brd/
│   │   ├── __init__.py
│   │   ├── schema.py                              # BRD/EvidenceMap/JudgeReport (PORT-AS-IS)
│   │   ├── pipeline.py                            # map/reduce BRD (PORT-AS-IS)
│   │   ├── renderer.py                            # BRD → HTML (PORT-AS-IS)
│   │   └── storage.py                             # BRD persistence (ADAPT → Postgres Artifact)
│   └── cobol/
│       ├── __init__.py
│       ├── parser.py                              # invoke extractor JAR, get JSON (PORT-AS-IS)
│       └── mapping.py                             # delegates to contract/cobol_contract.py (ADAPT)
├── tools/cobol-extractor/                          # Java ProLeap extractor (PORT+EXTEND v2 walker)
│   ├── pom.xml                                    # Java 25, ProLeap, Jackson (ADAPT)
│   └── src/main/java/com/cobolmodernizer/cobol/
│       ├── ExtractorMain.java                     # CLI entry (PORT, repackage)
│       ├── CobolWalker.java                       # v1 walker (PORT) — v2 edges added in Phase 1 plan
│       ├── DataFlowWalker.java                    # NEW (Phase 1) — DataItem/READS/WRITES/MOVES_TO/CICS/SQL/GOTO
│       ├── ExternalResolver.java                  # cross-program CALL resolution (PORT)
│       └── json/
│           ├── ExtractionJson.java               # {schemaVersion, files[]} (PORT, bump v2)
│           ├── FileResultJson.java               # {filePath,parseStatus,error,entities,relationships} (PORT)
│           ├── EntityJson.java                    # v1 entity record (PORT)
│           ├── DataItemJson.java                  # NEW (Phase 1) v2 DataItem fields
│           └── RelationshipJson.java             # {sourceQname,targetQname,kind,filePath,line,metadata} (PORT)
├── generated/                                      # generated Spring Boot services land here (Phase 5+)
│   └── .gitkeep
├── web/                                            # Next.js 15 / React 19 cockpit (ADAPT from source web/)
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── src/...
├── infra/
│   ├── neo4j/                                     # neo4j conf + GDS plugin mount
│   ├── postgres/initdb/                           # bootstrap SQL (optional)
│   └── minio/                                     # bucket bootstrap
└── tests/
    ├── conftest.py                               # shared fixtures (neo4j testcontainer, pg, fake runner)
    ├── unit/
    │   ├── test_cobol_contract.py                # schemaVersion=2 + mismatch-raises
    │   ├── test_cost_policy.py                    # caps + kill-switch
    │   ├── test_tiering.py                        # resolve_model roles
    │   └── test_persistence_tables.py            # Postgres schema round-trips
    ├── integration/
    │   └── test_graph_tools_readonly.py          # MCP tools reject writes
    └── fixtures/
        └── contract_v2_sample.json               # canonical v2 contract document
```

---

## 1. Greenfield project layout & tech-stack pinning

### Decisions (binding)
- **Root:** `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.
- **Python package:** `cobol_modernizer` (was `code_context_graph`). `src/`-layout; installed editable via uv.
- **Java package:** `com.cobolmodernizer.cobol` (was `com.codecontextgraph.cobol`).
- **Neo4j = code graph only. Postgres = run/audit/version/RBAC only.** No overlap, ever.
- **Object store (MinIO):** raw COBOL source, per-entity line slices, generated projects, golden files. Never materialized into prompts.

### Task 1.1 — Bootstrap the Python project

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/pyproject.toml`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/.python-version`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/__init__.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_package_imports.py`

Steps:
- [ ] Write failing test `tests/unit/test_package_imports.py`:
  ```python
  def test_package_version():
      import cobol_modernizer
      assert cobol_modernizer.__version__ == "0.1.0"
  ```
- [ ] Run `uv run pytest tests/unit/test_package_imports.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer'`.
- [ ] Create `pyproject.toml`:
  ```toml
  [project]
  name = "cobol-modernizer"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = [
    "pydantic>=2.9",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "neo4j>=5.24",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "boto3>=1.35",
    "claude-agent-sdk==0.2.87",
    "anthropic>=0.39",
  ]

  [project.optional-dependencies]
  dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "testcontainers>=4.8"]

  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  testpaths = ["tests"]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/cobol_modernizer"]
  ```
- [ ] Create `.python-version` containing `3.12`.
- [ ] Create `src/cobol_modernizer/__init__.py`:
  ```python
  __version__ = "0.1.0"
  ```
- [ ] Run `uv run pytest tests/unit/test_package_imports.py` — expected PASS (1 passed).
- [ ] Commit: `chore: bootstrap cobol_modernizer python package (uv, py3.12)`

---

## 2. The single versioned JSON contract (`schemaVersion: 2`)

This is the **ONLY** Python↔Java coupling surface. It is defined once, in Java records and a Python loader, and the **loader raises on any version mismatch**. Grounded in the partial impl's `EntityJson`/`RelationshipJson`/`ExtractionJson`/`FileResultJson` Java records and `cobol/mapping.py` (`SUPPORTED_SCHEMA_VERSION = 1`).

### Top-level document
```json
{
  "schemaVersion": 2,
  "files": [ FileResult, ... ]
}
```
`FileResult`:
```json
{
  "filePath": "app/cbl/CBACT01C.cbl",
  "parseStatus": "ok" | "error",
  "error": null | "string",
  "entities":      [ Entity, ... ],
  "dataItems":     [ DataItem, ... ],          // v2 (omitted/empty in v1)
  "relationships": [ Relationship, ... ]
}
```

### v1 Entity (unchanged from partial impl `EntityJson`)
```json
{
  "kind": "Program" | "Section" | "Paragraph" | "Copybook",
  "qualifiedName": "CBACT01C.1000-MAIN",
  "simpleName": "1000-MAIN",
  "filePath": "app/cbl/CBACT01C.cbl",
  "startLine": 0,
  "endLine": 0,
  "isExternal": false
}
```

### v2 DataItem (NEW node type)
WORKING-STORAGE / LINKAGE items and copybook fields. Lives in the graph, **never** in prompts.
```json
{
  "kind": "DataItem",
  "qualifiedName": "CBACT01C.WS-ACCT-ID",
  "simpleName": "WS-ACCT-ID",
  "filePath": "app/cbl/CBACT01C.cbl",
  "startLine": 0,
  "endLine": 0,
  "isExternal": false,
  "level": 5,                         // COBOL level number (01/05/10/...)
  "picture": "9(11)",                 // PIC clause or null
  "usage": "COMP-3" | "DISPLAY" | null,
  "redefines": "WS-OTHER" | null,
  "occurs": 0,                        // OCCURS count, 0 if none
  "parentQname": "CBACT01C.WS-ACCT-REC" | null  // group-item parent
}
```

### v1 + v2 Relationship (`RelationshipJson` shape, kind drives behavior)
```json
{
  "sourceQname": "CBACT01C.1000-MAIN",
  "targetQname": "CBACT01C.2000-READ",
  "kind": "CALLS" | "CONTAINS" | "IMPORTS"      // v1
        | "READS" | "WRITES" | "EXECUTES_CICS" | "EXECUTES_SQL" | "MOVES_TO" | "GO_TO", // v2
  "filePath": "app/cbl/CBACT01C.cbl",
  "line": 142,
  "metadata": { ... }                  // kind-specific, see below
}
```

**v1 edge metadata (existing):**
- `CALLS` (PERFORM): `{"type":"perform"}` — paragraph→paragraph.
- `CALLS` (CALL): `{"type":"call"}` — program→program.
- `CONTAINS`: program→section, section→paragraph, program→paragraph. `{}`.
- `IMPORTS`: program→copybook (from `COPY`). `{}`.

**v2 edge metadata (NEW — the seam-scoring signals):**
- `READS` / `WRITES`: program/paragraph → file/VSAM/DataItem. `{"resource":"ACCTDAT","resourceType":"VSAM"|"FILE"|"DATAITEM","mode":"sequential"|"random"|"dynamic"}`. The `kind` itself (READS vs WRITES) carries the reader/writer distinction Fowler calls pivotal.
- `EXECUTES_CICS`: program → CICS resource. `{"resource":"ACCTFILE","command":"READ"|"WRITE"|"REWRITE"|"DELETE"|"STARTBR"|"SEND"|"RECEIVE","intent":"read"|"write"}`.
- `EXECUTES_SQL`: program → SQL table. `{"resource":"ACCOUNT","operation":"SELECT"|"INSERT"|"UPDATE"|"DELETE","intent":"read"|"write"}`.
- `MOVES_TO`: DataItem → DataItem. `{"line":142}` (data-flow within a program).
- `GO_TO`: paragraph → paragraph. `{}` (control-flow; flags spaghetti / dead-paragraph analysis).

### Version-mismatch rule (binding)
The Python loader `cobol_modernizer/contract/cobol_contract.py` defines `SUPPORTED_SCHEMA_VERSION = 2` and **raises `ValueError` if `payload["schemaVersion"] != 2`** (extends the existing `mapping.py` rule). v1 documents are NOT silently upgraded; the extractor must emit v2. Forward/backward compatibility is intentionally not supported — one version, lockstep.

### Task 2.1 — Contract loader with mismatch-raises

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/contract/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/contract/cobol_contract.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/contract_v2_sample.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_cobol_contract.py`

Steps:
- [ ] Create fixture `tests/fixtures/contract_v2_sample.json`:
  ```json
  {
    "schemaVersion": 2,
    "files": [
      {
        "filePath": "app/cbl/CBACT01C.cbl",
        "parseStatus": "ok",
        "error": null,
        "entities": [
          {"kind":"Program","qualifiedName":"CBACT01C","simpleName":"CBACT01C","filePath":"app/cbl/CBACT01C.cbl","startLine":1,"endLine":200,"isExternal":false}
        ],
        "dataItems": [
          {"kind":"DataItem","qualifiedName":"CBACT01C.WS-ACCT-ID","simpleName":"WS-ACCT-ID","filePath":"app/cbl/CBACT01C.cbl","startLine":40,"endLine":40,"isExternal":false,"level":5,"picture":"9(11)","usage":"DISPLAY","redefines":null,"occurs":0,"parentQname":"CBACT01C.WS-ACCT-REC"}
        ],
        "relationships": [
          {"sourceQname":"CBACT01C","targetQname":"ACCTDAT","kind":"READS","filePath":"app/cbl/CBACT01C.cbl","line":120,"metadata":{"resource":"ACCTDAT","resourceType":"VSAM","mode":"random"}}
        ]
      }
    ]
  }
  ```
- [ ] Write failing test `tests/unit/test_cobol_contract.py`:
  ```python
  import json
  from pathlib import Path
  import pytest
  from cobol_modernizer.contract.cobol_contract import (
      SUPPORTED_SCHEMA_VERSION, load_contract,
  )

  FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_sample.json"

  def test_supported_version_is_2():
      assert SUPPORTED_SCHEMA_VERSION == 2

  def test_loads_v2_entities_dataitems_and_edges():
      results = load_contract(json.loads(FIX.read_text()))
      assert len(results) == 1
      r = results[0]
      assert r.file_path == "app/cbl/CBACT01C.cbl"
      assert any(e.qualified_name == "CBACT01C.WS-ACCT-ID" for e in r.entities)
      reads = [rel for rel in r.relationships if rel.kind.value == "READS"]
      assert reads and reads[0].metadata["resource"] == "ACCTDAT"

  def test_version_mismatch_raises():
      with pytest.raises(ValueError, match="schemaVersion"):
          load_contract({"schemaVersion": 1, "files": []})
  ```
- [ ] Run `uv run pytest tests/unit/test_cobol_contract.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/contract/cobol_contract.py`:
  ```python
  """The ONLY Python<->Java coupling: the versioned COBOL extractor JSON contract.
  Mismatched schemaVersion raises — one version, lockstep, no silent upgrade."""
  from __future__ import annotations

  from cobol_modernizer.models import (
      CodeEntity, CodeRelationship, EntityKind, ParseResult, RelKind,
  )

  SUPPORTED_SCHEMA_VERSION: int = 2

  def _entity(d: dict) -> CodeEntity:
      return CodeEntity(
          kind=EntityKind(d["kind"]),
          qualified_name=d["qualifiedName"],
          simple_name=d["simpleName"],
          file_path=d.get("filePath", ""),
          start_line=d.get("startLine", 0),
          end_line=d.get("endLine", 0),
          is_external=d.get("isExternal", False),
          # v2 DataItem fields ride in metadata-free explicit columns:
          level=d.get("level"),
          picture=d.get("picture"),
          usage=d.get("usage"),
          redefines=d.get("redefines"),
          occurs=d.get("occurs", 0),
          parent_qname=d.get("parentQname"),
      )

  def _rel(d: dict) -> CodeRelationship:
      return CodeRelationship(
          source_qname=d["sourceQname"],
          target_qname=d["targetQname"],
          kind=RelKind(d["kind"]),
          file_path=d.get("filePath"),
          line=d.get("line"),
          metadata=d.get("metadata") or {},
      )

  def load_contract(payload: dict) -> list[ParseResult]:
      version = payload.get("schemaVersion")
      if version != SUPPORTED_SCHEMA_VERSION:
          raise ValueError(
              f"Unsupported COBOL extractor schemaVersion {version!r}; "
              f"expected {SUPPORTED_SCHEMA_VERSION}"
          )
      results: list[ParseResult] = []
      for f in payload.get("files", []):
          ents = [_entity(e) for e in f.get("entities", [])]
          ents += [_entity(di) for di in f.get("dataItems", [])]
          results.append(ParseResult(
              file_path=f["filePath"],
              entities=ents,
              relationships=[_rel(r) for r in f.get("relationships", [])],
          ))
      return results
  ```
- [ ] Add to `EntityKind` in `models.py`: `DATA_ITEM = "DataItem"`. Add to `RelKind`: `EXECUTES_CICS = "EXECUTES_CICS"`, `EXECUTES_SQL = "EXECUTES_SQL"`, `MOVES_TO = "MOVES_TO"`, `GO_TO = "GO_TO"` (READS/WRITES/CONTAINS/CALLS/IMPORTS already exist). Add the v2 optional columns (`level`, `picture`, `usage`, `redefines`, `occurs`, `parent_qname`) to `CodeEntity` (all defaulting None/0).
- [ ] Run `uv run pytest tests/unit/test_cobol_contract.py` — expected PASS (3 passed).
- [ ] Commit: `feat(contract): schemaVersion=2 loader with v2 DataItem + IO edges, mismatch-raises`

---

## 3. Postgres schema (NEW) — run/audit/version/RBAC state

Neo4j is code-graph only. All run/audit/version/RBAC state is in Postgres. Tables: `workspace`, `journey_stage`, `agent_run`, `artifact`, `gate`, `approval`, `budget`. Identity/RBAC fields are on `approval` and `agent_run`.

### Table definitions (binding column names — downstream plans reference these verbatim)

```
workspace
  id              UUID PK
  name            TEXT NOT NULL
  repo_slug       TEXT NOT NULL                  -- ties to Neo4j Repository.slug
  graph_snapshot  TEXT                           -- pinned Neo4j snapshot id
  created_by      TEXT NOT NULL                  -- user email (RBAC identity)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  status          TEXT NOT NULL DEFAULT 'active' -- active|archived

journey_stage     -- the 11 cockpit stages per workspace
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  stage_key       TEXT NOT NULL    -- intake|graph|brd|seams|stories|design|build|equivalence|deploy|...
  ordinal         INT  NOT NULL
  status          TEXT NOT NULL DEFAULT 'pending'  -- pending|running|blocked|passed|failed
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (workspace_id, stage_key)

agent_run
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  stage_id        UUID FK -> journey_stage(id) ON DELETE CASCADE
  role            TEXT NOT NULL          -- resolve_model role: brd|enrichment|ask|advisor|seam|story|design|codegen|equivalence
  model           TEXT NOT NULL          -- resolved Claude model id actually used
  status          TEXT NOT NULL DEFAULT 'running'  -- running|succeeded|failed|killed
  started_by      TEXT NOT NULL          -- user email (RBAC identity)
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  finished_at     TIMESTAMPTZ
  input_tokens    BIGINT NOT NULL DEFAULT 0
  output_tokens   BIGINT NOT NULL DEFAULT 0
  cache_read_tokens     BIGINT NOT NULL DEFAULT 0
  cache_creation_tokens BIGINT NOT NULL DEFAULT 0
  total_cost_usd  NUMERIC(12,6) NOT NULL DEFAULT 0
  error           TEXT

artifact          -- versioned deliverables (BRD, seam set, story DAG, design, generated project, equivalence report)
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  stage_id        UUID FK -> journey_stage(id) ON DELETE CASCADE
  agent_run_id    UUID FK -> agent_run(id)            -- producing run (nullable for manual)
  kind            TEXT NOT NULL    -- brd|seam_set|story_dag|design|spring_boot_project|equivalence_report
  version         INT  NOT NULL    -- monotonically increasing per (workspace,kind)
  object_uri      TEXT NOT NULL    -- MinIO uri to the artifact body
  content_hash    TEXT NOT NULL    -- sha256 (drives incremental skip)
  evidence_map    JSONB NOT NULL DEFAULT '{}'  -- requirement_id -> [graph entity ids / source refs]
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (workspace_id, kind, version)

gate              -- a hard checkpoint between stages
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  stage_id        UUID FK -> journey_stage(id) ON DELETE CASCADE
  gate_key        TEXT NOT NULL    -- parse|graph|brd_groundedness|stories_dag|design_data_ownership|code|equivalence|deploy
  status          TEXT NOT NULL DEFAULT 'open'  -- open|passed|failed|waived
  threshold       JSONB NOT NULL DEFAULT '{}'   -- e.g. {"min_weighted":4.2,"accuracy_floor":3}
  result          JSONB NOT NULL DEFAULT '{}'   -- actual measured values
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (workspace_id, gate_key)

approval          -- attributed, RBAC human decision on a gate
  id              UUID PK
  gate_id         UUID FK -> gate(id) ON DELETE CASCADE
  decision        TEXT NOT NULL    -- approved|rejected|waived_with_risk
  approver_email  TEXT NOT NULL    -- RBAC approver identity (non-negotiable)
  approver_role   TEXT NOT NULL    -- e.g. lead_engineer|architect|risk_officer
  risk_accepted   BOOLEAN NOT NULL DEFAULT false  -- true only for waived_with_risk
  rationale       TEXT NOT NULL
  decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()

budget            -- per-workspace and per-run cost caps + running spend
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  scope           TEXT NOT NULL    -- 'workspace' | 'run'
  agent_run_id    UUID FK -> agent_run(id)   -- set when scope='run', else NULL
  cap_usd         NUMERIC(12,6) NOT NULL
  spent_usd       NUMERIC(12,6) NOT NULL DEFAULT 0
  killed          BOOLEAN NOT NULL DEFAULT false  -- kill-switch tripped
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Task 3.1 — SQLAlchemy tables + Postgres round-trip

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/db.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/tables.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_persistence_tables.py`

Steps:
- [ ] Write failing test (uses in-memory SQLite for shape; JSONB→JSON, UUID→str fallback) `tests/unit/test_persistence_tables.py`:
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session
  from cobol_modernizer.persistence.tables import Base, Workspace, Gate, Approval

  def test_workspace_and_approval_roundtrip():
      eng = create_engine("sqlite://")
      Base.metadata.create_all(eng)
      with Session(eng) as s:
          ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                         created_by="cwijay@biz2bricks.ai")
          s.add(ws); s.flush()
          g = Gate(workspace_id=ws.id, stage_id=None, gate_key="brd_groundedness",
                   threshold={"min_weighted": 4.2, "accuracy_floor": 3})
          s.add(g); s.flush()
          ap = Approval(gate_id=g.id, decision="waived_with_risk",
                        approver_email="lead@biz2bricks.ai", approver_role="lead_engineer",
                        risk_accepted=True, rationale="known dead path")
          s.add(ap); s.commit()
          assert ap.approver_email == "lead@biz2bricks.ai"
          assert g.threshold["accuracy_floor"] == 3
  ```
- [ ] Run `uv run pytest tests/unit/test_persistence_tables.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/persistence/tables.py` with `DeclarativeBase Base` and the seven mapped classes above (use `sqlalchemy.types.JSON` for portability so JSONB columns work on both Postgres and SQLite; `String` UUIDs with `default=lambda: str(uuid4())`; nullable FKs where noted). Mirror every column name from the schema verbatim.
- [ ] Create `db.py` with `make_engine(url=os.environ["POSTGRES_URL"])` and `session_scope()` contextmanager.
- [ ] Run `uv run pytest tests/unit/test_persistence_tables.py` — expected PASS (1 passed).
- [ ] Commit: `feat(persistence): Postgres run/audit/RBAC tables (workspace..budget)`

---

## 4. Model tiering + cost-cap/kill-switch policy

Grounded in partial impl `agent/models.py` (`resolve_model`), `harness.py` 4-bucket `token_usage` + `cost_usd`, `advisor.py` budget, prompt-cache env.

### `resolve_model(role)` — role → model (master plan §2)

| role (string) | default model | env override | tier rationale |
|---|---|---|---|
| `enrichment` | `claude-haiku-4-5-20251001` | `ENRICHMENT_MODEL` | high-volume per-node summaries |
| `ask` | `claude-haiku-4-5-20251001` | `ASK_MODEL` | ask-codebase Q&A |
| `equivalence_triage` | `claude-haiku-4-5-20251001` | `EQUIV_TRIAGE_MODEL` | cheap first-pass diff triage |
| `brd` | `claude-sonnet-4-6` | `BRD_AGENT_MODEL` | BRD map workers (synthesis) |
| `seam` | `claude-sonnet-4-6` | `SEAM_MODEL` | seam rationale over Cypher evidence |
| `story` | `claude-sonnet-4-6` | `STORY_MODEL` | story split (INVEST) |
| `codegen` | `claude-sonnet-4-6` | `CODEGEN_MODEL` | code/test gen triage |
| `judge` | `claude-opus-4-8` | `JUDGE_MODEL` | BRD reduce/judge (groundedness gate) |
| `design` | `claude-opus-4-8` | `DESIGN_MODEL` | architecture design (hard) |
| `repair` | `claude-opus-4-8` | `REPAIR_MODEL` | repair-loop hard failures |
| `advisor` | `claude-opus-4-8` | `ADVISOR_MODEL` | budgeted escalation (`ADVISOR_MAX_USES`) |

Precedence (unchanged from partial impl): per-role env override → global `CODE_GRAPH_LLM_MODEL` (renamed to `COBOL_MOD_LLM_MODEL`) → hardcoded default (Sonnet if role unknown).

### Budgets & caching (binding constants)
- `ADVISOR_MAX_USES` — default `3`; advisor budget exhaustion returns `advice=None` (worker proceeds). Per-server shared budget (`build_graph_server(..., advisor_max_uses=...)`).
- Advisor max_tokens: `700` (one short Opus call), system prompt marked `cache_control: ephemeral`.
- Prompt-caching: stable system + tool-definition prefixes are the cache anchor. `CCG_PROMPT_CACHING_1H=1` (renamed env `COBOL_MOD_PROMPT_CACHING_1H`) requests `ENABLE_PROMPT_CACHING_1H=1` for batch runs.
- 4 token buckets tracked everywhere: `input`, `output`, `cache_read`, `cache_creation`, plus `total_cost_usd` (from `ResultMessage.total_cost_usd`).

### Cost-cap + kill-switch policy module API (binding signatures)

`cobol_modernizer/cost/policy.py`:
```python
class BudgetExceeded(Exception): ...

class CostPolicy:
    """Per-workspace AND per-run hard cost caps with a kill-switch.
    Backed by the Postgres `budget` table. Pure-Python core is unit-tested
    without a DB via the in-memory CostLedger."""

    def __init__(self, ledger: "CostLedger") -> None: ...

    def record_usage(self, *, workspace_id: str, run_id: str,
                     token_usage: dict[str, int], cost_usd: float) -> None:
        """Add a ResultMessage's 4-bucket usage + cost to both the run and
        workspace ledgers."""

    def check(self, *, workspace_id: str, run_id: str) -> None:
        """Raise BudgetExceeded if run.spent >= run.cap OR
        workspace.spent >= workspace.cap. Trips the kill-switch (sets
        budget.killed=True) before raising."""

    def is_killed(self, *, workspace_id: str, run_id: str) -> bool: ...

    def remaining_usd(self, *, workspace_id: str) -> float:
        """workspace cap - workspace spent (clamped >= 0); UI surfaces this."""
```
Env defaults: `COBOL_MOD_WORKSPACE_CAP_USD` (default `50.0`), `COBOL_MOD_RUN_CAP_USD` (default `5.0`). Verifier aborts + requests approval on threshold crossing; UI shows the **cap**, not just running total.

### Task 4.1 — resolve_model roles

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/cost/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/cost/tiering.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_tiering.py`

Steps:
- [ ] Write failing test `tests/unit/test_tiering.py`:
  ```python
  import os
  from cobol_modernizer.cost.tiering import resolve_model

  def test_defaults_by_tier():
      assert resolve_model("enrichment").startswith("claude-haiku")
      assert resolve_model("brd") == "claude-sonnet-4-6"
      assert resolve_model("judge") == "claude-opus-4-8"
      assert resolve_model("unknown-role") == "claude-sonnet-4-6"

  def test_per_role_env_override(monkeypatch):
      monkeypatch.setenv("JUDGE_MODEL", "claude-opus-test")
      assert resolve_model("judge") == "claude-opus-test"
  ```
- [ ] Run `uv run pytest tests/unit/test_tiering.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `tiering.py` porting `resolve_model` and extending `_ROLE_ENV`/`_DEFAULTS` with the 11 roles above; global env var `COBOL_MOD_LLM_MODEL`.
- [ ] Run `uv run pytest tests/unit/test_tiering.py` — expected PASS (2 passed).
- [ ] Commit: `feat(cost): resolve_model with 11 tiered roles (haiku/sonnet/opus)`

### Task 4.2 — CostPolicy caps + kill-switch

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/cost/policy.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_cost_policy.py`

Steps:
- [ ] Write failing test `tests/unit/test_cost_policy.py`:
  ```python
  import pytest
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded

  def _ledger():
      l = CostLedger()
      l.set_cap(workspace_id="w1", run_id=None, cap_usd=10.0)
      l.set_cap(workspace_id="w1", run_id="r1", cap_usd=2.0)
      return l

  def test_under_cap_ok():
      p = CostPolicy(_ledger())
      p.record_usage(workspace_id="w1", run_id="r1",
                     token_usage={"input":100,"output":50,"cache_read":0,"cache_creation":0},
                     cost_usd=1.0)
      p.check(workspace_id="w1", run_id="r1")  # no raise
      assert p.remaining_usd(workspace_id="w1") == 9.0

  def test_run_cap_trips_kill_switch():
      p = CostPolicy(_ledger())
      p.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=2.5)
      with pytest.raises(BudgetExceeded):
          p.check(workspace_id="w1", run_id="r1")
      assert p.is_killed(workspace_id="w1", run_id="r1") is True
  ```
- [ ] Run `uv run pytest tests/unit/test_cost_policy.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `policy.py` with an in-memory `CostLedger` (dict of caps/spend/killed) and `CostPolicy` per the signatures above. `check` trips `killed=True` then raises `BudgetExceeded` if either run or workspace spend ≥ cap.
- [ ] Run `uv run pytest tests/unit/test_cost_policy.py` — expected PASS (2 passed).
- [ ] Commit: `feat(cost): per-workspace/per-run cost caps + kill-switch policy`

### Task 4.3 — .env.example

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/.env.example`

Steps:
- [ ] Create `.env.example` documenting all env: `ANTHROPIC_API_KEY`, `COBOL_MOD_LLM_MODEL`, per-role `*_MODEL`, `ADVISOR_MAX_USES=3`, `COBOL_MOD_PROMPT_CACHING_1H=0`, `COBOL_MOD_WORKSPACE_CAP_USD=50.0`, `COBOL_MOD_RUN_CAP_USD=5.0`, `NEO4J_URI=bolt://localhost:7687`, `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=...`, `POSTGRES_URL=postgresql+psycopg://...`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `COBOL_EXTRACTOR_JAR=tools/cobol-extractor/target/cobol-extractor.jar`.
- [ ] Commit: `chore: .env.example with model/cost/neo4j/postgres/minio config`

---

## 5. The MCP graph server tool surface (read-only)

Grounded in `agent/graph_tools.py`. Server name `graph`; FQNs `mcp__graph__<tool>`. All tools `ToolAnnotations(readOnlyHint=True)`; the harness runs `tools=[]` (built-ins removed) + `setting_sources=[]`, so the agent can ONLY use these. Cypher behind each tool is **read-only** (downstream graph_ops must reject any write clause).

### v1 tool surface (PORT-AS-IS — names/signatures other plans reference)
- `list_subsystems(max_clusters: int = 12) -> {clusters:[{name, members:[id]}]}`
- `get_entity(name: str) -> entity`
- `find_entities(kind?: str, prefix?: str, limit: int = 50) -> [entity]`
- `neighbors(name: str, edge: str, direction: "out"|"in"|"both" = "out", depth: int = 1, limit: int = 50) -> [entity]`
- `get_source_slice(name: str) -> {source}` — returns ONLY `start_line..end_line` from the object store (the token-economy core; raw source never dumped).
- `entry_points(limit: int = 50) -> [entity]`
- `integration_points(markers?: list, limit: int = 50) -> [entity]`
- `graph_summary() -> {entity_counts, rel_counts}`
- `consult_advisor(question: str, context?: str)` — added only when `advisor` is passed; shared `advisor_max_uses` budget.

### v2 tool additions (Phase 1 — exposed once v2 edges exist; seam math stays in Cypher)
- `data_accesses(name: str, intent?: "read"|"write", limit: int = 50) -> [{resource, kind, mode, intent}]` — READS/WRITES/EXECUTES_CICS/EXECUTES_SQL for a program.
- `reader_writer_classification(resource: str) -> {readers:[program], writers:[program]}` — pivotal Fowler reader-vs-writer split, computed in Cypher.
- `seam_candidates(limit: int = 20) -> [{program, fan_in, fan_out, reader_only: bool, score}]` — ranked, **zero LLM in the scoring path**.

`GRAPH_TOOL_NAMES` (the allowed_tools allow-list) extends to include the v2 tool FQNs. `neighbors` edge enum extends with `READS|WRITES|EXECUTES_CICS|EXECUTES_SQL|MOVES_TO|GO_TO|CONTAINS`.

Downstream phase plans MUST NOT add a tool that performs writes, MUST NOT bypass `get_source_slice` to read whole files, and MUST keep all seam scoring in Cypher/GDS (the LLM only writes rationale over precomputed evidence).

---

## 6. Infra — docker-compose (Neo4j+GDS, Postgres, MinIO)

### Task 6.1 — docker-compose

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/docker-compose.yml`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_compose_config.py`

Steps:
- [ ] Write failing test `tests/integration/test_compose_config.py` (validates the compose file declares the three services + GDS plugin, no Docker needed):
  ```python
  from pathlib import Path
  ROOT = Path(__file__).parents[2]

  def test_compose_has_three_backends_and_gds():
      text = (ROOT / "docker-compose.yml").read_text()
      assert "neo4j:" in text and "postgres:" in text and "minio:" in text
      assert "graph-data-science" in text  # GDS plugin enabled
      assert "NEO4J_PLUGINS" in text or "gds" in text.lower()
  ```
- [ ] Run `uv run pytest tests/integration/test_compose_config.py` — expected FAIL: file missing.
- [ ] Create `docker-compose.yml`:
  ```yaml
  services:
    neo4j:
      image: neo4j:5.24-enterprise
      environment:
        NEO4J_AUTH: neo4j/devpassword
        NEO4J_ACCEPT_LICENSE_AGREEMENT: "yes"
        NEO4J_PLUGINS: '["graph-data-science"]'
        NEO4J_dbms_security_procedures_unrestricted: gds.*
      ports: ["7474:7474", "7687:7687"]
      volumes: ["neo4j_data:/data"]
    postgres:
      image: postgres:16
      environment:
        POSTGRES_USER: cobol
        POSTGRES_PASSWORD: devpassword
        POSTGRES_DB: cobol_modernizer
      ports: ["5432:5432"]
      volumes: ["pg_data:/var/lib/postgresql/data"]
    minio:
      image: minio/minio:latest
      command: server /data --console-address ":9001"
      environment:
        MINIO_ROOT_USER: minio
        MINIO_ROOT_PASSWORD: devpassword
      ports: ["9000:9000", "9001:9001"]
      volumes: ["minio_data:/data"]
  volumes:
    neo4j_data: {}
    pg_data: {}
    minio_data: {}
  ```
- [ ] Run `uv run pytest tests/integration/test_compose_config.py` — expected PASS (1 passed).
- [ ] Commit: `chore(infra): docker-compose neo4j(+GDS)/postgres/minio`

---

## 7. Conventions (binding across all phases)

### Test framework & layout
- Python: **pytest** + `pytest-asyncio` (`asyncio_mode = "auto"`). Layout `tests/unit/`, `tests/integration/`, `tests/fixtures/`. Fast unit tests use in-memory SQLite / fake `AgentRunner`; integration tests use `testcontainers` for Neo4j/Postgres. One assertion-focused test per behavior; TDD red→green→commit.
- Java: **JUnit 5** under `tools/cobol-extractor/src/test/java/...` (mirror the existing `JsonShapeTest`/`CobolWalkerTest` pattern).
- Web: **Vitest** (unit) + **Playwright** (e2e).

### Commit style
- Conventional commits: `feat(scope): ...`, `fix(scope): ...`, `chore(scope): ...`, `test(scope): ...`. Frequent, bite-sized commits (one per task step group). Branch first if on default branch.

### Lineage / evidence_map contract (binding)
- `EvidenceMap = dict[str, list[str]]` — `requirement_id -> [graph entity ids and/or source refs]` (from `brd/schema.py`). Every generated artifact (BRD, seam set, story, design, test, code) carries an `evidence_map`. Stored on `artifact.evidence_map` (JSONB).
- **Groundedness gate (from `brd_judge.py`):** any ref not in `graph_ops.known_refs(deps)` is a `groundedness_failure`; if failures exist and `accuracy > 2`, accuracy is **forced to 2** with a `[forced to 2 by hallucinated refs: ...]` rationale. Weighted score = `0.25·completeness + 0.30·accuracy + 0.15·clarity + 0.15·consistency + 0.15·actionability`. Rating: `high` if weighted ≥ 4.2 and all dims ≥ 3; `medium` if ≥ 3.2 and all ≥ 2; else `low`. This contract extends verbatim to seams/stories/designs/tests/code.

### COBOL graceful-degradation rule (binding)
- The extractor never crashes the run on a bad file: a parse failure yields `FileResultJson(filePath, parseStatus="error", error=<ExceptionClass: msg>, entities=[], relationships=[])` (from `CobolWalker.walk`). A file that parses but yields no `Program` entity is `parseStatus="error"` with `"no COBOL program found"`. Copybook resolution failures are swallowed (`catch (Exception ignored)`) — partial graph beats no graph. Ingestion tolerates ≥10 injected parse errors without aborting (Phase 0 exit criterion). `parser.py` stays COBOL-agnostic; all COBOL specifics live under `cobol/` and in the JSON contract.

### Working-core invariants (do not regress)
- `tools=[]`, `setting_sources=[]`, `output_format={"type":"json_schema",...}` on every agent run (`SdkAgentRunner`).
- Read-only Cypher enforced in `graph_ops`; the single versioned JSON contract is the ONLY Python↔Java coupling; Neo4j = code graph only, Postgres = run/audit only.

---

## 8. Port-map (every key `source_graphs_v1.0` file)

Source root: `/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0`. Target root: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`. Do NOT edit the source tree; copy/adapt into the target. All Python ports rewrite `code_context_graph` → `cobol_modernizer`; all Java ports rewrite `com.codecontextgraph.cobol` → `com.cobolmodernizer.cobol`.

| Source file | Class | Target path |
|---|---|---|
| `src/code_context_graph/parser.py` | PORT-AS-IS | `src/cobol_modernizer/parser.py` |
| `src/code_context_graph/models.py` | ADAPT (add DataItem kind, v2 RelKinds, v2 CodeEntity columns) | `src/cobol_modernizer/models.py` |
| `src/code_context_graph/schema.py` | ADAPT (add DataItem label, v2 rel MERGE, seam indexes) | `src/cobol_modernizer/schema.py` |
| `src/code_context_graph/neo4j_client.py` | PORT-AS-IS | `src/cobol_modernizer/neo4j_client.py` |
| `src/code_context_graph/ingestion.py` | ADAPT (content-hash incremental, contract v2) | `src/cobol_modernizer/ingestion.py` |
| `src/code_context_graph/queries.py` | ADAPT (add seam/reader-writer Cypher) | `src/cobol_modernizer/queries.py` |
| `src/code_context_graph/api.py` | ADAPT (stages, approvals, cost, SSE, Postgres) | `src/cobol_modernizer/api.py` |
| `src/code_context_graph/cobol/parser.py` | PORT-AS-IS | `src/cobol_modernizer/cobol/parser.py` |
| `src/code_context_graph/cobol/mapping.py` | REBUILD → contract loader (v2, mismatch-raises) | `src/cobol_modernizer/contract/cobol_contract.py` (thin `cobol/mapping.py` delegates) |
| `src/code_context_graph/agent/harness.py` | PORT-AS-IS (tools=[]/setting_sources=[]/json_schema) | `src/cobol_modernizer/agent/harness.py` |
| `src/code_context_graph/agent/models.py` | REBUILD → tiering (11 roles) | `src/cobol_modernizer/cost/tiering.py` |
| `src/code_context_graph/agent/deps.py` | PORT-AS-IS | `src/cobol_modernizer/agent/deps.py` |
| `src/code_context_graph/agent/graph_ops.py` | ADAPT (v2 ops + read-only guard) | `src/cobol_modernizer/agent/graph_ops.py` |
| `src/code_context_graph/agent/graph_tools.py` | ADAPT (add v2 tools, FQN allow-list) | `src/cobol_modernizer/agent/graph_tools.py` |
| `src/code_context_graph/agent/advisor.py` | PORT-AS-IS (advisor budget) | `src/cobol_modernizer/agent/advisor.py` |
| `src/code_context_graph/agent/brd_judge.py` | PORT-AS-IS (groundedness gate) | `src/cobol_modernizer/agent/brd_judge.py` |
| `src/code_context_graph/agent/enricher.py` | ADAPT (content-hash cache key) | `src/cobol_modernizer/agent/enricher.py` |
| `src/code_context_graph/brd/schema.py` | PORT-AS-IS (BRD/EvidenceMap/JudgeReport) | `src/cobol_modernizer/brd/schema.py` |
| `src/code_context_graph/brd/pipeline.py` | PORT-AS-IS (map/reduce) | `src/cobol_modernizer/brd/pipeline.py` |
| `src/code_context_graph/brd/renderer.py` | PORT-AS-IS | `src/cobol_modernizer/brd/renderer.py` |
| `src/code_context_graph/brd/storage.py` | ADAPT (→ Postgres Artifact + MinIO) | `src/cobol_modernizer/brd/storage.py` |
| `tools/.../cobol/CobolWalker.java` | ADAPT (v1 PORT; v2 edges in Phase 1) | `tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/CobolWalker.java` |
| `tools/.../cobol/ExternalResolver.java` | PORT-AS-IS | `.../com/cobolmodernizer/cobol/ExternalResolver.java` |
| `tools/.../cobol/json/*.java` (Entity/Relationship/FileResult/Extraction) | ADAPT (bump v2, add DataItemJson) | `.../com/cobolmodernizer/cobol/json/*.java` |
| `web/src/components/GraphView.tsx` | ADAPT (COBOL filters, seam overlay) | `web/src/components/GraphView.tsx` |
| `src/code_context_graph/cli.py` | ADAPT | `src/cobol_modernizer/cli.py` |
| `src/code_context_graph/git_analyzer.py` | PORT-AS-IS (co-change churn overlay) | `src/cobol_modernizer/git_analyzer.py` |
| `src/code_context_graph/llm_query.py` | IGNORE (superseded by agent harness) | — |
| `src/code_context_graph/language_registry.py` | IGNORE (non-COBOL languages out of scope) | — |
| `src/code_context_graph/github_client.py` / `repo_manager.py` | ADAPT-LATER (intake; optional) | `src/cobol_modernizer/intake/*` |
| `agent/brd_orchestrator.py` / `clustering.py` / `ask_agent.py` / `enrich_schema.py` / `brd_schema.py` | ADAPT (fold into brd/ + agent/) | `src/cobol_modernizer/{brd,agent}/...` |

---

## Acceptance criteria

This foundation plan is the barrier for plans 01–08. It is complete when:

1. **Layout & stack pinned** — `pyproject.toml` declares package `cobol_modernizer`, Python 3.12, the pinned deps incl. `claude-agent-sdk==0.2.87`; `tests/unit/test_package_imports.py` passes. (§1)
2. **Single versioned contract at v2** — `cobol_modernizer/contract/cobol_contract.py` defines `SUPPORTED_SCHEMA_VERSION = 2`, loads v1 nodes/edges (Program/Section/Paragraph/Copybook + CALLS/CONTAINS/IMPORTS) AND v2 additions (DataItem; READS/WRITES with mode; EXECUTES_CICS/EXECUTES_SQL with resource+intent; MOVES_TO; GO_TO), and **raises on version mismatch**; `test_cobol_contract.py` proves all three. (§2)
3. **Postgres schema exists** — `persistence/tables.py` defines Workspace/JourneyStage/AgentRun/Artifact/Gate/Approval/Budget with the exact columns, FKs, and RBAC fields (`approver_email`, `approver_role`, `risk_accepted`); `test_persistence_tables.py` round-trips a gate→approval. Neo4j carries zero run/audit state. (§3)
4. **Model tiering + cost policy** — `cost/tiering.py:resolve_model` returns Haiku/Sonnet/Opus per role with env overrides; `cost/policy.py:CostPolicy` enforces per-workspace AND per-run caps and trips the kill-switch (`BudgetExceeded`); tracks the 4 token buckets + `total_cost_usd`; `ADVISOR_MAX_USES` documented. Tests `test_tiering.py`, `test_cost_policy.py` pass. (§4)
5. **MCP graph tool surface frozen** — the v1 read-only tool names/signatures and the v2 additions are documented as the contract downstream plans reference; all tools `readOnlyHint=True`; harness invariants (`tools=[]`, `setting_sources=[]`, `json_schema`) preserved. (§5)
6. **Infra reproducible** — `docker-compose.yml` stands up Neo4j+GDS, Postgres, MinIO; `test_compose_config.py` passes. (§6)
7. **Conventions documented** — test framework/layout, conventional-commit style, lineage/evidence_map + groundedness-gate contract, and COBOL graceful-degradation rule are all stated and binding. (§7)
8. **Port-map complete** — every key `source_graphs_v1.0` file is classified PORT-AS-IS / ADAPT / REBUILD / IGNORE with a concrete target path under the greenfield tree. (§8)

These map 1:1 to the master plan's §1 non-negotiables (Neo4j source-of-truth, lineage/groundedness, strangler-fig, seam-math-in-Cypher, outcome parity, hard attributed gates, token economy with caps+kill-switch, working-core invariants) and unblock Phase 0's persistence/cost deliverables.
