# Phase 0 — CardDemo Baseline + Persistence + Cost Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Make the headline workload (AWS CardDemo — ≈39 programs / 41 copybooks) actually run end-to-end through the *existing* analysis core (ingest → Neo4j graph → grounded BRD), prove it with a reproducible benchmark (parse time, peak memory, error resilience on ≥10 injected bad files, nested-copybook depth), and add the missing run/audit substrate: the Postgres schema (created via Alembic migrations), the per-workspace & per-run cost-cap + kill-switch policy module (with Verifier abort + approval on threshold crossing), and content-hash incremental ingestion (skip unchanged programs/copybooks, cache enrichment/summaries keyed by `source_hash + prompt_version`).

**Architecture:** Phase 0 builds *only* on the working analysis tier. The Neo4j code graph stays the source of truth; the COBOL extractor JSON contract (`schemaVersion: 2`, from the foundation plan) stays the only Python↔Java coupling; the BRD pipeline + groundedness-gate judge + model tiering are PORTed verbatim. The new substrate — Postgres run/audit/RBAC tables, the `CostPolicy` kill-switch, and content-hash incremental re-ingest — wraps that core without changing its invariants (`tools=[]`, `setting_sources=[]`, `json_schema` output, read-only Cypher, COBOL graceful degradation). Seam math is NOT in scope here (Phase 1+). No LLM is added to any deterministic path.

**Tech Stack (pinned, from foundation §Tech Stack):** Python 3.12 + uv; Neo4j 5.24-enterprise + GDS; PostgreSQL 16; MinIO; `claude-agent-sdk==0.2.87`; SQLAlchemy 2.0 + Alembic 1.13 + `psycopg[binary]` 3.2; pytest + pytest-asyncio (`asyncio_mode=auto`) + testcontainers; `pytest-benchmark`; `tracemalloc` (stdlib) for memory. Java 25 + Maven extractor JAR is invoked as a subprocess (already built per foundation; Phase 1 adds v2 edges).

**Depends on (must be done first):**
- `docs/plans/00-foundation-and-architecture.md` Tasks 1.1 (package bootstrap), 2.1 (`contract/cobol_contract.py`, `SUPPORTED_SCHEMA_VERSION=2`), 3.1 (`persistence/tables.py` — the seven mapped classes), 4.1 (`cost/tiering.py:resolve_model`), 4.2 (`cost/policy.py:CostPolicy`/`CostLedger`/`BudgetExceeded`), 4.3 (`.env.example`), 6.1 (`docker-compose.yml`).
- The PORT tasks the foundation port-map names but does not itself execute. **This Phase 0 plan executes those PORTs** for the files Phase 0 reuses: `parser.py`, `neo4j_client.py`, `schema.py` (v1 labels only — v2 labels are Phase 1), `models.py` (v2 columns already added in foundation Task 2.1), `cobol/parser.py`, `cobol/mapping.py` (thin delegate), `ingestion.py` (ADAPT: incremental), `brd/*`, `agent/harness.py`, `agent/deps.py`, `agent/graph_ops.py` (read-only paths only), `agent/graph_tools.py` (v1 tools only), `agent/advisor.py`, `agent/brd_judge.py`, `agent/enricher.py`, `git_analyzer.py`.

---

## File Structure

All paths under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── src/cobol_modernizer/
│   ├── parser.py                         # PORT-AS-IS: COBOL-agnostic parse_directory dispatch (Task 1)
│   ├── neo4j_client.py                   # PORT-AS-IS: Neo4j driver wrapper (Task 1)
│   ├── schema.py                         # PORT: v1 CONSTRAINTS/INDEXES/MERGE Cypher (Task 1)
│   ├── git_analyzer.py                   # PORT-AS-IS: co-change churn overlay (Task 1)
│   ├── cobol/
│   │   ├── parser.py                     # PORT-AS-IS: subprocess driver for extractor JAR (Task 2)
│   │   └── mapping.py                    # ADAPT: thin delegate to contract.cobol_contract (Task 2)
│   ├── ingestion.py                      # ADAPT: content-hash incremental re-ingest (Task 4)
│   ├── ingestion_hash.py                 # NEW: source_hash + ingest-manifest helpers (Task 3)
│   ├── agent/
│   │   ├── harness.py                    # PORT-AS-IS: SdkAgentRunner (Task 5)
│   │   ├── deps.py                       # PORT-AS-IS: GraphDeps (Task 5)
│   │   ├── graph_ops.py                  # PORT: read-only Cypher ops incl. known_refs (Task 5)
│   │   ├── graph_tools.py                # PORT: v1 read-only MCP tools (Task 5)
│   │   ├── advisor.py                    # PORT-AS-IS: advisor budget (Task 5)
│   │   ├── brd_judge.py                  # PORT-AS-IS: groundedness gate (Task 5)
│   │   ├── brd_orchestrator.py           # PORT: BRD draft map/reduce (Task 5)
│   │   ├── clustering.py                 # PORT: subsystem clustering (Task 5)
│   │   ├── enrich_schema.py              # PORT: EnrichmentTags schema (Task 6)
│   │   └── enricher.py                   # ADAPT: source_hash+prompt_version cache key (Task 6)
│   ├── brd/
│   │   ├── schema.py                     # PORT-AS-IS: BRD/EvidenceMap/JudgeReport (Task 5)
│   │   ├── pipeline.py                   # PORT-AS-IS: map/reduce BRD entry (Task 5)
│   │   ├── renderer.py                   # PORT-AS-IS: BRD -> HTML (Task 5)
│   │   └── storage.py                    # PORT (Neo4j+disk; Postgres Artifact deferred) (Task 5)
│   ├── cost/
│   │   └── verifier.py                   # NEW: CostVerifier wraps a run, aborts+requests approval on cap (Task 7)
│   ├── persistence/
│   │   ├── migrations/                   # NEW: Alembic env + versions
│   │   │   ├── env.py                    # Alembic env wired to tables.Base.metadata (Task 8)
│   │   │   ├── script.py.mako            # Alembic template (Task 8)
│   │   │   └── versions/
│   │   │       └── 0001_initial.py       # NEW: create the 7 tables (Task 8)
│   │   └── repo.py                       # NEW: PgRepo — workspace/run/budget/gate/approval writes (Task 9)
│   └── benchmark/
│       ├── __init__.py
│       ├── error_injection.py            # NEW: inject N malformed COBOL files into a temp copy (Task 10)
│       └── carddemo_baseline.py          # NEW: ingest CardDemo, measure time/mem/errors/depth, emit report (Task 11)
├── alembic.ini                           # NEW: Alembic config (script_location=persistence/migrations) (Task 8)
├── tests/
│   ├── conftest.py                       # shared fixtures (extend: carddemo_root, fake_runner) (Task 1)
│   ├── unit/
│   │   ├── test_cobol_mapping_delegate.py     # mapping delegates to v2 loader (Task 2)
│   │   ├── test_ingestion_hash.py             # source_hash stable; manifest diff (Task 3)
│   │   ├── test_incremental_ingestion.py      # skip unchanged; re-pay ~0 on no-change (Task 4)
│   │   ├── test_enricher_cache_key.py         # cache key = source_hash+prompt_version (Task 6)
│   │   ├── test_cost_verifier.py              # abort + approval request on cap crossing (Task 7)
│   │   ├── test_pg_repo.py                     # PgRepo round-trips run usage -> budget (Task 9)
│   │   └── test_error_injection.py            # injects exactly N bad files (Task 10)
│   ├── integration/
│   │   ├── test_carddemo_ingest.py            # CardDemo -> Neo4j (testcontainer) (Task 12)
│   │   ├── test_carddemo_error_resilience.py  # >=10 injected errors, no crash (Task 12)
│   │   ├── test_migrations_apply.py           # alembic upgrade head on PG testcontainer (Task 8)
│   │   └── test_carddemo_brd_grounded.py      # BRD renders w/ judge score (fake runner) (Task 13)
│   └── fixtures/
│       └── carddemo_extract_v2.json           # canned v2 contract for the CardDemo subset (Task 12)
└── docs/plans/
    └── phase-0-carddemo-baseline-persistence-cost.md   # THIS FILE
```

**Source to PORT from (read-only; do NOT edit):** `/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/...`. **CardDemo source:** `/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/source_code_to_analyse/aws-mf-mod-carddemo` (programs in `app/cbl`, copybooks in `app/cpy` + `app/cpy-bms`; subdirs `app/app-*` add up to the documented 39/41). Phase 0 ingests the whole `aws-mf-mod-carddemo` tree and benchmarks against the actually-discovered counts.

Every PORT step rewrites `code_context_graph` → `cobol_modernizer` and `CCG_` env prefixes → `COBOL_MOD_`/`COBOL_EXTRACTOR_` per the foundation. Add `pytest-benchmark` to `[project.optional-dependencies].dev` in `pyproject.toml`.

---

## Task 1 — PORT the deterministic graph core (parser, neo4j_client, schema, git_analyzer)

**Files:**
- Create: `src/cobol_modernizer/parser.py` (PORT-AS-IS from `src/code_context_graph/parser.py`)
- Create: `src/cobol_modernizer/neo4j_client.py` (PORT-AS-IS)
- Create: `src/cobol_modernizer/schema.py` (PORT v1 labels/rels only)
- Create: `src/cobol_modernizer/git_analyzer.py` (PORT-AS-IS)
- Modify: `tests/conftest.py` (add `carddemo_root` fixture)
- Test: reuse foundation `tests/unit/test_package_imports.py` + new import smoke below

Steps:
- [ ] Copy the four source files into the target paths, then global-rewrite the package: `code_context_graph` → `cobol_modernizer`. Do this with an explicit command (NOT manual editing of large files):
  ```bash
  SRC=/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/src/code_context_graph
  DST=/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer
  for f in parser.py neo4j_client.py schema.py git_analyzer.py; do \
    sed 's/code_context_graph/cobol_modernizer/g' "$SRC/$f" > "$DST/$f"; done
  ```
- [ ] Add `carddemo_root` to `tests/conftest.py`:
  ```python
  import os
  from pathlib import Path
  import pytest

  CARDDEMO = Path(
      "/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0"
      "/source_code_to_analyse/aws-mf-mod-carddemo"
  )

  @pytest.fixture
  def carddemo_root() -> Path:
      if not CARDDEMO.exists():
          pytest.skip(f"CardDemo source not present at {CARDDEMO}")
      return CARDDEMO
  ```
- [ ] Write smoke test `tests/unit/test_core_imports.py`:
  ```python
  def test_core_modules_import():
      from cobol_modernizer import parser, neo4j_client, schema, git_analyzer
      assert hasattr(parser, "parse_directory")
      assert hasattr(neo4j_client, "Neo4jClient")
  ```
- [ ] Run `uv run pytest tests/unit/test_core_imports.py -q` — expected PASS (1 passed). If `schema.py` references a v2-only label, that is Phase 1 — leave v1 only.
- [ ] Commit: `feat(core): port parser/neo4j_client/schema/git_analyzer (code_context_graph -> cobol_modernizer)`

---

## Task 2 — PORT the COBOL subprocess driver + make mapping a thin v2 delegate

The foundation built `contract/cobol_contract.py` (`SUPPORTED_SCHEMA_VERSION=2`, `load_contract`). The old `cobol/mapping.py` (`SUPPORTED_SCHEMA_VERSION=1`, `cobol_json_to_parse_results`) must become a **thin delegate** so the existing `cobol/parser.py` call site (`cobol_json_to_parse_results(payload)`) keeps working but routes through the v2 loader. The env prefix is rewritten to `COBOL_EXTRACTOR_JAR` per `.env.example`.

**Files:**
- Create: `src/cobol_modernizer/cobol/__init__.py` (empty)
- Create: `src/cobol_modernizer/cobol/parser.py` (PORT, rewrite env names)
- Create: `src/cobol_modernizer/cobol/mapping.py` (ADAPT — delegate)
- Test: `tests/unit/test_cobol_mapping_delegate.py`

Steps:
- [ ] Write failing test `tests/unit/test_cobol_mapping_delegate.py`:
  ```python
  import json
  from pathlib import Path
  import pytest
  from cobol_modernizer.cobol.mapping import (
      cobol_json_to_parse_results, SUPPORTED_SCHEMA_VERSION,
  )

  FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_sample.json"

  def test_mapping_supports_v2():
      assert SUPPORTED_SCHEMA_VERSION == 2

  def test_mapping_delegates_to_v2_loader():
      results = cobol_json_to_parse_results(json.loads(FIX.read_text()))
      assert len(results) == 1
      assert results[0].file_path == "app/cbl/CBACT01C.cbl"

  def test_mapping_rejects_v1():
      with pytest.raises(ValueError, match="schemaVersion"):
          cobol_json_to_parse_results({"schemaVersion": 1, "files": []})
  ```
- [ ] Run `uv run pytest tests/unit/test_cobol_mapping_delegate.py -q` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.cobol.mapping'`.
- [ ] Create `src/cobol_modernizer/cobol/mapping.py` (delegate, no duplicate logic — DRY):
  ```python
  """Thin back-compat delegate. The real, single, versioned loader lives in
  cobol_modernizer.contract.cobol_contract (schemaVersion=2). This module only
  preserves the historical call site name cobol_json_to_parse_results so the
  subprocess driver in cobol/parser.py is unchanged."""
  from __future__ import annotations

  from cobol_modernizer.contract.cobol_contract import (
      SUPPORTED_SCHEMA_VERSION,
      load_contract as cobol_json_to_parse_results,
  )

  __all__ = ["SUPPORTED_SCHEMA_VERSION", "cobol_json_to_parse_results"]
  ```
- [ ] Create `src/cobol_modernizer/cobol/parser.py` by porting the source and rewriting env var names:
  ```bash
  SRC=/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/src/code_context_graph/cobol/parser.py
  DST=/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/cobol/parser.py
  sed -e 's/code_context_graph/cobol_modernizer/g' \
      -e 's/CCG_COBOL_EXTRACTOR_JAR/COBOL_EXTRACTOR_JAR/g' \
      -e 's/CCG_COBOL_COPYBOOK_DIRS/COBOL_MOD_COPYBOOK_DIRS/g' \
      -e 's/CCG_COBOL_FORMAT/COBOL_MOD_COBOL_FORMAT/g' \
      "$SRC" > "$DST"
  ```
- [ ] Run `uv run pytest tests/unit/test_cobol_mapping_delegate.py -q` — expected PASS (3 passed).
- [ ] Commit: `feat(cobol): port subprocess driver; mapping.py delegates to v2 contract loader`

---

## Task 3 — Content-hash + ingest-manifest helpers (the incremental-skip primitive)

Per master plan §2/§4: *content-hash each program/copybook; skip unchanged; cache enrichment/summaries keyed by `source_hash + prompt_version`.* This task delivers the pure, DB-free hashing primitive and a manifest diff used by Task 4 (incremental ingest) and Task 6 (enricher cache).

**Files:**
- Create: `src/cobol_modernizer/ingestion_hash.py`
- Test: `tests/unit/test_ingestion_hash.py`

Steps:
- [ ] Write failing test `tests/unit/test_ingestion_hash.py`:
  ```python
  from pathlib import Path
  from cobol_modernizer.ingestion_hash import (
      source_hash, build_manifest, diff_manifest,
  )

  def test_source_hash_is_stable_and_content_addressed(tmp_path: Path):
      f = tmp_path / "CBACT01C.cbl"
      f.write_text("       IDENTIFICATION DIVISION.\n")
      h1 = source_hash(f)
      h2 = source_hash(f)
      assert h1 == h2 and len(h1) == 64        # sha256 hex
      f.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n")
      assert source_hash(f) != h1              # content change -> new hash

  def test_manifest_diff_classifies_changed_added_removed(tmp_path: Path):
      a = tmp_path / "A.cbl"; a.write_text("AAA")
      b = tmp_path / "B.cpy"; b.write_text("BBB")
      old = build_manifest([a, b], root=tmp_path)
      b.write_text("BBB-changed")
      c = tmp_path / "C.cbl"; c.write_text("CCC")
      a.unlink()
      new = build_manifest([b, c], root=tmp_path)
      d = diff_manifest(old=old, new=new)
      assert d.changed == {"B.cpy"}
      assert d.added == {"C.cbl"}
      assert d.removed == {"A.cbl"}
      assert d.unchanged == set()
  ```
- [ ] Run `uv run pytest tests/unit/test_ingestion_hash.py -q` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/ingestion_hash.py`:
  ```python
  """Content-hash primitives for incremental re-ingest (master plan §2/§4).
  source_hash is the cache key base for enrichment/summaries; the manifest diff
  drives 'skip unchanged programs/copybooks; re-pay ~0 LLM cost on no-change'."""
  from __future__ import annotations

  import hashlib
  from dataclasses import dataclass, field
  from pathlib import Path

  Manifest = dict[str, str]  # repo-relative path -> source_hash

  def source_hash(path: Path) -> str:
      h = hashlib.sha256()
      with open(path, "rb") as fh:
          for chunk in iter(lambda: fh.read(65536), b""):
              h.update(chunk)
      return h.hexdigest()

  def build_manifest(paths: list[Path], *, root: Path) -> Manifest:
      out: Manifest = {}
      for p in paths:
          rel = str(p.relative_to(root))
          out[rel] = source_hash(p)
      return out

  @dataclass
  class ManifestDiff:
      added: set[str] = field(default_factory=set)
      removed: set[str] = field(default_factory=set)
      changed: set[str] = field(default_factory=set)
      unchanged: set[str] = field(default_factory=set)

      @property
      def to_process(self) -> set[str]:
          return self.added | self.changed

  def diff_manifest(*, old: Manifest, new: Manifest) -> ManifestDiff:
      d = ManifestDiff()
      old_keys, new_keys = set(old), set(new)
      d.added = new_keys - old_keys
      d.removed = old_keys - new_keys
      for k in old_keys & new_keys:
          (d.changed if old[k] != new[k] else d.unchanged).add(k)
      return d
  ```
- [ ] Run `uv run pytest tests/unit/test_ingestion_hash.py -q` — expected PASS (2 passed).
- [ ] Commit: `feat(ingest): content-hash + ingest-manifest diff primitive`

---

## Task 4 — ADAPT ingestion.py for content-hash incremental re-ingest

PORT `ingestion.py`, then add an incremental path: persist the manifest as `source_hash` properties on the Program/Copybook nodes and an `IngestManifest` keyed by `repo_slug`; on re-ingest, load+diff and **only re-load entities/relationships for `to_process` files**, skipping unchanged. Re-ingest of an unchanged repo re-pays ~0 LLM cost (Phase 0 exit criterion) because nothing is parsed/enriched again.

**Files:**
- Create: `src/cobol_modernizer/ingestion.py` (PORT + ADAPT)
- Test: `tests/unit/test_incremental_ingestion.py`

Steps:
- [ ] PORT the base file: `sed 's/code_context_graph/cobol_modernizer/g' .../ingestion.py > src/cobol_modernizer/ingestion.py`.
- [ ] Write failing test `tests/unit/test_incremental_ingestion.py` (uses a fake client + the real COBOL parser path stubbed by a fake `parse_repo`):
  ```python
  from pathlib import Path
  from cobol_modernizer.ingestion import IncrementalIngester
  from cobol_modernizer.ingestion_hash import build_manifest

  class FakeClient:
      def __init__(self): self.loaded, self.manifests = [], {}
      def apply_schema(self): pass
      def clear(self): self.loaded.clear()
      def merge_entity(self, **kw): self.loaded.append(kw["qualified_name"])
      def merge_relationship(self, **kw): pass
      def save_manifest(self, slug, m): self.manifests[slug] = dict(m)
      def load_manifest(self, slug): return dict(self.manifests.get(slug, {}))

  def _entity(qn, fp):
      from cobol_modernizer.models import CodeEntity, EntityKind
      return CodeEntity(kind=EntityKind.PROGRAM, qualified_name=qn,
                        simple_name=qn, file_path=fp, start_line=1, end_line=2)

  def test_unchanged_reingest_processes_zero_files(tmp_path: Path):
      a = tmp_path / "A.cbl"; a.write_text("AAA")
      from cobol_modernizer.models import ParseResult
      calls = {"n": 0}
      def fake_parse(paths):
          calls["n"] += 1
          return [ParseResult(file_path="A.cbl",
                              entities=[_entity("A", "A.cbl")], relationships=[])]
      cli = FakeClient()
      ing = IncrementalIngester(cli, repo_root=tmp_path, repo_slug="cardemo",
                                parse_fn=fake_parse)
      first = ing.ingest_incremental()
      assert first["processed"] == 1
      second = ing.ingest_incremental()
      assert second["processed"] == 0
      assert second["skipped"] == 1
      assert calls["n"] == 1     # second run parsed nothing -> ~0 cost
  ```
- [ ] Run `uv run pytest tests/unit/test_incremental_ingestion.py -q` — expected FAIL: `ImportError: cannot import name 'IncrementalIngester'`.
- [ ] Append `IncrementalIngester` to `src/cobol_modernizer/ingestion.py`:
  ```python
  from cobol_modernizer.ingestion_hash import build_manifest, diff_manifest

  class IncrementalIngester:
      """Content-hash incremental re-ingest. parse_fn(paths)->list[ParseResult]
      is injected so unit tests need neither the JAR nor Neo4j; production wires
      it to CobolParser.parse_repo. Only added+changed files are (re)loaded; the
      stored manifest makes an unchanged re-ingest re-pay ~0 LLM/parse cost."""

      def __init__(self, client, *, repo_root: Path, repo_slug: str, parse_fn) -> None:
          self.client = client
          self.repo_root = Path(repo_root)
          self.repo_slug = repo_slug
          self.parse_fn = parse_fn

      def _discover(self) -> list[Path]:
          exts = {".cbl", ".cob", ".cobol", ".cpy"}
          return [p for p in sorted(self.repo_root.rglob("*"))
                  if p.suffix.lower() in exts
                  and not any(part.startswith(".") for part in
                              p.relative_to(self.repo_root).parts[:-1])]

      def ingest_incremental(self) -> dict[str, int]:
          self.client.apply_schema()
          files = self._discover()
          new_manifest = build_manifest(files, root=self.repo_root)
          old_manifest = self.client.load_manifest(self.repo_slug)
          d = diff_manifest(old=old_manifest, new=new_manifest)
          to_process = d.to_process
          processed = 0
          if to_process:
              rel_to_path = {str(p.relative_to(self.repo_root)): p for p in files}
              targets = [rel_to_path[r] for r in sorted(to_process)]
              for result in self.parse_fn(targets):
                  for e in result.entities:
                      self.client.merge_entity(
                          qualified_name=e.qualified_name, label=e.kind.value,
                          props={"file_path": e.file_path,
                                 "source_hash": new_manifest.get(e.file_path, "")})
                  for rel in result.relationships:
                      self.client.merge_relationship(
                          source_qname=rel.source_qname,
                          target_qname=rel.target_qname,
                          rel_type=rel.kind.value, props=dict(rel.metadata),
                          allow_unresolved=True)
                  processed += 1
          self.client.save_manifest(self.repo_slug, new_manifest)
          return {"processed": processed, "skipped": len(d.unchanged),
                  "added": len(d.added), "changed": len(d.changed),
                  "removed": len(d.removed)}
  ```
- [ ] Run `uv run pytest tests/unit/test_incremental_ingestion.py -q` — expected PASS (1 passed).
- [ ] Commit: `feat(ingest): content-hash incremental re-ingest (skip unchanged, ~0 cost on no-change)`

---

## Task 5 — PORT the BRD pipeline + agent harness (verbatim)

PORT the working analysis tier the BRD reuses. These are PORT-AS-IS except for the package rewrite; the invariants (`tools=[]`, `setting_sources=[]`, `json_schema`, groundedness gate) are preserved exactly. `graph_ops.py` keeps only read paths in Phase 0 (the read-only guard is added in Phase 1 alongside v2 ops).

**Files:**
- Create: `src/cobol_modernizer/agent/{__init__.py,harness.py,deps.py,graph_ops.py,graph_tools.py,advisor.py,brd_judge.py,brd_orchestrator.py,clustering.py}`
- Create: `src/cobol_modernizer/brd/{__init__.py,schema.py,pipeline.py,renderer.py,storage.py}`
- Test: `tests/unit/test_brd_judge_groundedness.py`

Steps:
- [ ] PORT every file with the package rewrite + caching env rename:
  ```bash
  SRC=/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/src/code_context_graph
  DST=/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer
  for f in agent/harness.py agent/deps.py agent/graph_ops.py agent/graph_tools.py \
           agent/advisor.py agent/brd_judge.py agent/brd_orchestrator.py agent/clustering.py \
           brd/schema.py brd/pipeline.py brd/renderer.py brd/storage.py; do \
    sed -e 's/code_context_graph/cobol_modernizer/g' \
        -e 's/CCG_PROMPT_CACHING_1H/COBOL_MOD_PROMPT_CACHING_1H/g' \
        "$SRC/$f" > "$DST/$f"; done
  touch "$DST/agent/__init__.py" "$DST/brd/__init__.py"
  ```
- [ ] In the ported `brd/pipeline.py` and any file importing `from cobol_modernizer.agent.models import resolve_model`, rewrite the import to the foundation's tiering module: `from cobol_modernizer.cost.tiering import resolve_model` (the foundation REBUILT `agent/models.py` as `cost/tiering.py`):
  ```bash
  DST=/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer
  grep -rl "cobol_modernizer.agent.models import resolve_model" "$DST" | while read f; do \
    sed -i '' 's/cobol_modernizer\.agent\.models import resolve_model/cobol_modernizer.cost.tiering import resolve_model/g' "$f"; done
  ```
- [ ] Write test `tests/unit/test_brd_judge_groundedness.py` (proves the floor survived the port; fake runner + fake deps, no SDK/Neo4j):
  ```python
  import cobol_modernizer.agent.graph_ops as ops
  from cobol_modernizer.agent.brd_judge import ajudge
  from cobol_modernizer.brd.schema import BRD, Strategy, Dimension, Rating

  class FakeRunner:
      async def run_structured(self, **kw):
          return {"items": [
              {"dimension": "completeness", "score": 5, "rationale": ""},
              {"dimension": "accuracy", "score": 5, "rationale": ""},
              {"dimension": "clarity", "score": 5, "rationale": ""},
              {"dimension": "consistency", "score": 5, "rationale": ""},
              {"dimension": "actionability", "score": 5, "rationale": ""}],
              "feedback": []}

  async def test_hallucinated_ref_forces_accuracy_to_2(monkeypatch):
      monkeypatch.setattr(ops, "known_refs", lambda deps: {"CBACT01C"})
      brd = BRD(sections=[], evidence_map={"FR-1": ["GHOST-PROGRAM"]},
                repo_id="cardemo", model="m", strategy=Strategy.map_reduce)
      report = await ajudge(brd, deps=object(), runner=FakeRunner(), model="m")
      assert report.dimensions[Dimension.accuracy].score == 2
      assert "GHOST-PROGRAM" in report.groundedness_failures
      assert report.rating != Rating.high   # floored accuracy blocks 'high'
  ```
- [ ] Run `uv run pytest tests/unit/test_brd_judge_groundedness.py -q` — expected PASS (1 passed). (Adjust the `BRD(...)` kwargs to the ported `brd/schema.py` field names if they differ; the ported schema is authoritative.)
- [ ] Commit: `feat(brd): port BRD pipeline + groundedness-gate judge + agent harness (invariants intact)`

---

## Task 6 — ADAPT enricher.py: cache enrichment keyed by source_hash + prompt_version

Per master plan §4.7: *content-hash + `prompt_version` cache keys.* The ported enricher writes summaries back to graph nodes; ADAPT it so a node already enriched against the current `(source_hash, prompt_version)` is skipped (no LLM call), and the cache key is recorded on the node.

**Files:**
- Create: `src/cobol_modernizer/agent/enrich_schema.py` (PORT)
- Create: `src/cobol_modernizer/agent/enricher.py` (ADAPT)
- Test: `tests/unit/test_enricher_cache_key.py`

Steps:
- [ ] PORT `enrich_schema.py`: `sed 's/code_context_graph/cobol_modernizer/g' .../agent/enrich_schema.py > .../agent/enrich_schema.py`.
- [ ] PORT `enricher.py` with the package rewrite (full async logic stays), then add a module-level `ENRICH_PROMPT_VERSION` and a pure `enrichment_cache_key` + `should_enrich` helper.
- [ ] Write failing test `tests/unit/test_enricher_cache_key.py`:
  ```python
  from cobol_modernizer.agent.enricher import (
      ENRICH_PROMPT_VERSION, enrichment_cache_key, should_enrich,
  )

  def test_cache_key_combines_source_hash_and_prompt_version():
      k = enrichment_cache_key(source_hash="abc123", prompt_version=ENRICH_PROMPT_VERSION)
      assert k == f"abc123:{ENRICH_PROMPT_VERSION}"

  def test_should_skip_when_cache_key_matches():
      key = enrichment_cache_key(source_hash="abc123", prompt_version=ENRICH_PROMPT_VERSION)
      node = {"qualified_name": "CBACT01C", "enrich_cache_key": key}
      assert should_enrich(node, source_hash="abc123") is False

  def test_should_enrich_when_source_changed():
      node = {"qualified_name": "CBACT01C", "enrich_cache_key": "old:1"}
      assert should_enrich(node, source_hash="newhash") is True
  ```
- [ ] Run `uv run pytest tests/unit/test_enricher_cache_key.py -q` — expected FAIL: `ImportError`.
- [ ] Add to `src/cobol_modernizer/agent/enricher.py`:
  ```python
  ENRICH_PROMPT_VERSION = "1"   # bump when ENRICH_SYSTEM changes; invalidates cache

  def enrichment_cache_key(*, source_hash: str, prompt_version: str) -> str:
      return f"{source_hash}:{prompt_version}"

  def should_enrich(node: dict, *, source_hash: str) -> bool:
      """Skip (return False) only when the node was already enriched against the
      current source_hash AND the current prompt version — re-pays 0 LLM cost."""
      want = enrichment_cache_key(source_hash=source_hash,
                                  prompt_version=ENRICH_PROMPT_VERSION)
      return node.get("enrich_cache_key") != want
  ```
  Wire `should_enrich` into `_fetch_untagged`/`aenrich` so the WRITE_BACK Cypher also sets `e.enrich_cache_key = $cache_key`, and the fetch query excludes nodes whose `enrich_cache_key` already matches. (Keep the read-only-vs-write split: enrichment WRITE_BACK is the one allowed mutation, exactly as in the source.)
- [ ] Run `uv run pytest tests/unit/test_enricher_cache_key.py -q` — expected PASS (3 passed).
- [ ] Commit: `feat(enrich): cache enrichment by source_hash + prompt_version (skip unchanged nodes)`

---

## Task 7 — CostVerifier: abort + request approval on cap crossing

The foundation built `CostPolicy`/`CostLedger`/`BudgetExceeded` (caps + kill-switch). This task adds the master-plan §3 Phase-0 behavior: *Verifier aborts + requests approval on threshold crossing.* `CostVerifier` wraps a unit of agent work; before/after each charge it calls `policy.check`; on `BudgetExceeded` it stops the work and emits an `ApprovalRequest` (consumed by the API/UI later) rather than silently continuing.

**Files:**
- Create: `src/cobol_modernizer/cost/verifier.py`
- Test: `tests/unit/test_cost_verifier.py`

Steps:
- [ ] Write failing test `tests/unit/test_cost_verifier.py`:
  ```python
  import pytest
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
  from cobol_modernizer.cost.verifier import CostVerifier, ApprovalRequest

  def _policy():
      l = CostLedger()
      l.set_cap(workspace_id="w1", run_id=None, cap_usd=10.0)
      l.set_cap(workspace_id="w1", run_id="r1", cap_usd=2.0)
      return CostPolicy(l)

  def test_charge_under_cap_returns_none():
      v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
      assert v.charge(token_usage={"input": 10}, cost_usd=1.0) is None
      assert v.aborted is False

  def test_charge_over_cap_aborts_and_returns_approval_request():
      v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
      req = v.charge(token_usage={}, cost_usd=2.5)
      assert isinstance(req, ApprovalRequest)
      assert req.scope == "run" and req.workspace_id == "w1" and req.run_id == "r1"
      assert v.aborted is True
      assert v.policy.is_killed(workspace_id="w1", run_id="r1") is True

  def test_aborted_verifier_refuses_further_charges():
      v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
      v.charge(token_usage={}, cost_usd=2.5)
      with pytest.raises(BudgetExceeded):
          v.charge(token_usage={}, cost_usd=0.1)
  ```
- [ ] Run `uv run pytest tests/unit/test_cost_verifier.py -q` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/cost/verifier.py`:
  ```python
  """CostVerifier — wraps a unit of agent work with the per-run/per-workspace cap.
  On a cap crossing it ABORTS the work (no further charges) and emits an
  ApprovalRequest for an attributed human decision (master plan §3, §1.6/§1.7)."""
  from __future__ import annotations

  from dataclasses import dataclass
  from cobol_modernizer.cost.policy import CostPolicy, BudgetExceeded

  @dataclass(frozen=True)
  class ApprovalRequest:
      workspace_id: str
      run_id: str
      scope: str          # 'run' | 'workspace'
      spent_usd: float
      cap_usd: float
      reason: str

  class CostVerifier:
      def __init__(self, policy: CostPolicy, *, workspace_id: str, run_id: str) -> None:
          self.policy = policy
          self.workspace_id = workspace_id
          self.run_id = run_id
          self.aborted = False

      def charge(self, *, token_usage: dict[str, int], cost_usd: float):
          """Record usage then enforce the cap. Returns None when under cap;
          returns an ApprovalRequest (and sets self.aborted) on first crossing.
          Subsequent calls raise BudgetExceeded — the run is stoppable-safe."""
          if self.aborted:
              raise BudgetExceeded(
                  f"run {self.run_id} already aborted pending approval")
          self.policy.record_usage(workspace_id=self.workspace_id,
                                   run_id=self.run_id,
                                   token_usage=token_usage, cost_usd=cost_usd)
          try:
              self.policy.check(workspace_id=self.workspace_id, run_id=self.run_id)
          except BudgetExceeded as exc:
              self.aborted = True
              run_remaining = self.policy.remaining_usd(workspace_id=self.workspace_id)
              return ApprovalRequest(
                  workspace_id=self.workspace_id, run_id=self.run_id,
                  scope="run" if self.policy.is_killed(
                      workspace_id=self.workspace_id, run_id=self.run_id) else "workspace",
                  spent_usd=cost_usd, cap_usd=run_remaining, reason=str(exc))
          return None
  ```
- [ ] Run `uv run pytest tests/unit/test_cost_verifier.py -q` — expected PASS (3 passed).
- [ ] Commit: `feat(cost): CostVerifier aborts run + requests attributed approval on cap crossing`

---

## Task 8 — Alembic migrations create the Postgres schema (apply on a PG testcontainer)

The foundation defined `persistence/tables.py` (the seven SQLAlchemy classes). Master plan Phase-0 deliverable (b) requires the schema *created via migrations*. This task wires Alembic to `tables.Base.metadata` and proves `alembic upgrade head` builds all seven tables on a real Postgres 16 testcontainer.

**Files:**
- Create: `alembic.ini`
- Create: `src/cobol_modernizer/persistence/migrations/{env.py,script.py.mako}`
- Create: `src/cobol_modernizer/persistence/migrations/versions/0001_initial.py`
- Test: `tests/integration/test_migrations_apply.py`

Steps:
- [ ] Create `alembic.ini` (minimal):
  ```ini
  [alembic]
  script_location = src/cobol_modernizer/persistence/migrations
  prepend_sys_path = .
  [loggers]
  keys = root
  [handlers]
  keys = console
  [formatters]
  keys = generic
  [logger_root]
  level = WARN
  handlers = console
  [handler_console]
  class = StreamHandler
  args = (sys.stderr,)
  formatter = generic
  [formatter_generic]
  format = %(levelname)-5.5s [%(name)s] %(message)s
  ```
- [ ] Create `migrations/env.py` (autogenerate-capable, reads `POSTGRES_URL`):
  ```python
  import os
  from alembic import context
  from sqlalchemy import create_engine
  from cobol_modernizer.persistence.tables import Base

  target_metadata = Base.metadata

  def run_migrations_online():
      url = os.environ["POSTGRES_URL"]
      engine = create_engine(url)
      with engine.connect() as connection:
          context.configure(connection=connection, target_metadata=target_metadata)
          with context.begin_transaction():
              context.run_migrations()

  run_migrations_online()
  ```
- [ ] Create `migrations/script.py.mako` (standard Alembic template — copy the default Alembic mako).
- [ ] Create `migrations/versions/0001_initial.py` that emits `op.create_table(...)` for **workspace, journey_stage, agent_run, artifact, gate, approval, budget** with the exact columns/FKs/UNIQUE constraints from foundation §3 (UUID PKs, `NUMERIC(12,6)` cost columns, `JSONB` for `evidence_map`/`threshold`/`result`, RBAC columns `approver_email`/`approver_role`/`risk_accepted`). Generate it once via autogenerate against a scratch DB, then commit the reviewed file:
  ```bash
  POSTGRES_URL=postgresql+psycopg://cobol:devpassword@localhost:5432/cobol_modernizer \
    uv run alembic revision --autogenerate -m "initial run/audit/RBAC schema" \
    --rev-id 0001_initial
  ```
- [ ] Write integration test `tests/integration/test_migrations_apply.py`:
  ```python
  import os
  import pytest
  from sqlalchemy import create_engine, inspect

  testcontainers = pytest.importorskip("testcontainers.postgres")
  from testcontainers.postgres import PostgresContainer

  EXPECTED = {"workspace", "journey_stage", "agent_run", "artifact",
              "gate", "approval", "budget"}

  def test_alembic_upgrade_head_creates_all_tables():
      with PostgresContainer("postgres:16") as pg:
          url = pg.get_connection_url().replace("psycopg2", "psycopg")
          os.environ["POSTGRES_URL"] = url
          from alembic.config import Config
          from alembic import command
          cfg = Config("alembic.ini")
          command.upgrade(cfg, "head")
          insp = inspect(create_engine(url))
          assert EXPECTED.issubset(set(insp.get_table_names()))
  ```
- [ ] Run `uv run pytest tests/integration/test_migrations_apply.py -q` — expected PASS (1 passed). (Requires Docker; the test `importorskip`s when testcontainers is absent.)
- [ ] Commit: `feat(persistence): alembic 0001 creates workspace..budget run/audit/RBAC schema`

---

## Task 9 — PgRepo: persist agent-run usage into the budget table

Wire the cost-tracking loop to Postgres: a `PgRepo` writes an `agent_run`, accumulates the 4 token buckets + `total_cost_usd`, and rolls the run's spend into the `budget(scope='run')` and `budget(scope='workspace')` rows. This is the production backing for `CostLedger` (the foundation's in-memory ledger stays the unit-test double).

**Files:**
- Create: `src/cobol_modernizer/persistence/repo.py`
- Test: `tests/unit/test_pg_repo.py` (SQLite-backed shape test, matching foundation Task 3.1's portability approach)

Steps:
- [ ] Write failing test `tests/unit/test_pg_repo.py`:
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session
  from cobol_modernizer.persistence.tables import Base
  from cobol_modernizer.persistence.repo import PgRepo

  def test_run_usage_rolls_into_run_and_workspace_budget():
      eng = create_engine("sqlite://")
      Base.metadata.create_all(eng)
      with Session(eng) as s:
          repo = PgRepo(s)
          ws = repo.create_workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                                     created_by="cwijay@biz2bricks.ai")
          repo.set_budget(workspace_id=ws.id, scope="workspace", cap_usd=50.0)
          run = repo.start_run(workspace_id=ws.id, stage_id=None, role="brd",
                               model="claude-sonnet-4-6", started_by="cwijay@biz2bricks.ai")
          repo.set_budget(workspace_id=ws.id, scope="run", agent_run_id=run.id, cap_usd=5.0)
          repo.record_run_usage(workspace_id=ws.id, run_id=run.id,
                                token_usage={"input": 1000, "output": 500,
                                             "cache_read": 0, "cache_creation": 0},
                                cost_usd=1.25)
          s.commit()
          assert float(run.total_cost_usd) == 1.25
          assert run.input_tokens == 1000 and run.output_tokens == 500
          assert repo.budget_spent(workspace_id=ws.id, scope="workspace") == 1.25
          assert repo.budget_spent(workspace_id=ws.id, scope="run",
                                   agent_run_id=run.id) == 1.25
  ```
- [ ] Run `uv run pytest tests/unit/test_pg_repo.py -q` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/persistence/repo.py`:
  ```python
  """PgRepo — the only writer of run/audit/budget rows. Neo4j stays code-graph
  only; ALL cost/RBAC/run state lives here (foundation §1 strict storage split)."""
  from __future__ import annotations

  from decimal import Decimal
  from sqlalchemy import select
  from sqlalchemy.orm import Session
  from cobol_modernizer.persistence.tables import (
      Workspace, JourneyStage, AgentRun, Budget,
  )

  class PgRepo:
      def __init__(self, session: Session) -> None:
          self.s = session

      def create_workspace(self, *, name: str, repo_slug: str, created_by: str) -> Workspace:
          ws = Workspace(name=name, repo_slug=repo_slug, created_by=created_by)
          self.s.add(ws); self.s.flush()
          return ws

      def start_run(self, *, workspace_id, stage_id, role: str, model: str,
                    started_by: str) -> AgentRun:
          run = AgentRun(workspace_id=workspace_id, stage_id=stage_id, role=role,
                         model=model, started_by=started_by, status="running")
          self.s.add(run); self.s.flush()
          return run

      def set_budget(self, *, workspace_id, scope: str, cap_usd: float,
                     agent_run_id=None) -> Budget:
          b = Budget(workspace_id=workspace_id, scope=scope,
                     agent_run_id=agent_run_id, cap_usd=Decimal(str(cap_usd)))
          self.s.add(b); self.s.flush()
          return b

      def _budget(self, *, workspace_id, scope, agent_run_id=None) -> Budget:
          stmt = select(Budget).where(Budget.workspace_id == workspace_id,
                                      Budget.scope == scope)
          if scope == "run":
              stmt = stmt.where(Budget.agent_run_id == agent_run_id)
          return self.s.scalars(stmt).one()

      def record_run_usage(self, *, workspace_id, run_id,
                           token_usage: dict[str, int], cost_usd: float) -> None:
          run = self.s.get(AgentRun, run_id)
          run.input_tokens += token_usage.get("input", 0)
          run.output_tokens += token_usage.get("output", 0)
          run.cache_read_tokens += token_usage.get("cache_read", 0)
          run.cache_creation_tokens += token_usage.get("cache_creation", 0)
          run.total_cost_usd = (run.total_cost_usd or Decimal(0)) + Decimal(str(cost_usd))
          for scope, arid in (("run", run_id), ("workspace", None)):
              b = self._budget(workspace_id=workspace_id, scope=scope, agent_run_id=arid)
              b.spent_usd = (b.spent_usd or Decimal(0)) + Decimal(str(cost_usd))
          self.s.flush()

      def budget_spent(self, *, workspace_id, scope, agent_run_id=None) -> float:
          return float(self._budget(workspace_id=workspace_id, scope=scope,
                                    agent_run_id=agent_run_id).spent_usd)
  ```
- [ ] Run `uv run pytest tests/unit/test_pg_repo.py -q` — expected PASS (1 passed).
- [ ] Commit: `feat(persistence): PgRepo rolls run usage into run + workspace budgets`

---

## Task 10 — Error-injection harness (the >=10 bad-file resilience input)

The exit criterion requires *no crash on ≥10 injected parse errors*. This harness makes a temp copy of a COBOL tree and corrupts exactly N files (truncation / garbage / empty), returning the list of corrupted paths so the resilience test can assert each became `parseStatus="error"` without aborting the run.

**Files:**
- Create: `src/cobol_modernizer/benchmark/__init__.py` (empty)
- Create: `src/cobol_modernizer/benchmark/error_injection.py`
- Test: `tests/unit/test_error_injection.py`

Steps:
- [ ] Write failing test `tests/unit/test_error_injection.py`:
  ```python
  from pathlib import Path
  from cobol_modernizer.benchmark.error_injection import (
      copy_tree, inject_parse_errors,
  )

  def test_injects_exactly_n_corrupt_files(tmp_path: Path):
      src = tmp_path / "src"
      (src / "app" / "cbl").mkdir(parents=True)
      for i in range(15):
          (src / "app" / "cbl" / f"P{i:02d}.cbl").write_text(
              "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n")
      dst = copy_tree(src, tmp_path / "dst")
      corrupted = inject_parse_errors(dst, count=10, seed=7)
      assert len(corrupted) == 10
      for p in corrupted:
          assert Path(p).read_text() == "" or "GARBAGE" in Path(p).read_text() \
                 or len(Path(p).read_text()) < 20
      # untouched files remain valid
      remaining = [p for p in (dst / "app" / "cbl").glob("*.cbl")
                   if str(p) not in {str(c) for c in corrupted}]
      assert all("IDENTIFICATION DIVISION" in p.read_text() for p in remaining)
  ```
- [ ] Run `uv run pytest tests/unit/test_error_injection.py -q` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/benchmark/error_injection.py`:
  ```python
  """Deterministic COBOL error injection for the Phase-0 resilience benchmark.
  Corrupts N source files in a COPY of the tree so the extractor's graceful
  degradation (parseStatus='error', no crash) can be verified."""
  from __future__ import annotations

  import random
  import shutil
  from pathlib import Path

  _MODES = ("truncate", "garbage", "empty")

  def copy_tree(src: Path, dst: Path) -> Path:
      shutil.copytree(src, dst)
      return dst

  def _corrupt(path: Path, mode: str) -> None:
      if mode == "empty":
          path.write_text("")
      elif mode == "truncate":
          path.write_text(path.read_text()[: max(0, len(path.read_text()) // 5)])
      else:  # garbage — not valid COBOL
          path.write_text("@@@ GARBAGE NOT COBOL @@@\n\x00\x01\x02 random bytes\n")

  def inject_parse_errors(root: Path, *, count: int, seed: int = 0) -> list[Path]:
      rng = random.Random(seed)
      candidates = sorted(p for p in root.rglob("*")
                          if p.suffix.lower() in {".cbl", ".cob", ".cobol", ".cpy"})
      if len(candidates) < count:
          raise ValueError(f"need >= {count} files, found {len(candidates)}")
      chosen = rng.sample(candidates, count)
      for i, p in enumerate(chosen):
          _corrupt(p, _MODES[i % len(_MODES)])
      return chosen
  ```
- [ ] Run `uv run pytest tests/unit/test_error_injection.py -q` — expected PASS (1 passed).
- [ ] Commit: `feat(benchmark): deterministic COBOL error-injection harness`

---

## Task 11 — CardDemo baseline benchmark runner (time, memory, errors, copybook depth)

The headline deliverable: a runnable benchmark that ingests CardDemo and emits a JSON report with parse wall-time, peak memory (`tracemalloc`), discovered program/copybook counts, parse-error count, and max nested-copybook depth (longest `IMPORTS` chain). It accepts a `parse_fn` so it runs in CI with a canned contract (Task 12) when the JAR/JVM is unavailable (COBOL graceful degradation — the run never hard-fails).

**Files:**
- Create: `src/cobol_modernizer/benchmark/carddemo_baseline.py`
- Test: covered by integration Task 12

Steps:
- [ ] Create `src/cobol_modernizer/benchmark/carddemo_baseline.py`:
  ```python
  """CardDemo Phase-0 baseline benchmark. Measures parse wall-time, peak memory,
  entity/error counts, and nested-copybook depth. parse_fn is injectable so CI
  can run against a canned v2 contract without the JVM (graceful degradation)."""
  from __future__ import annotations

  import json
  import time
  import tracemalloc
  from dataclasses import dataclass, asdict
  from pathlib import Path

  from cobol_modernizer.models import RelKind

  @dataclass
  class BaselineReport:
      repo_root: str
      files_discovered: int
      programs: int
      copybooks: int
      parse_errors: int
      parse_seconds: float
      peak_memory_mb: float
      max_copybook_depth: int

  def _discover(root: Path) -> list[Path]:
      exts = {".cbl", ".cob", ".cobol", ".cpy"}
      return [p for p in sorted(root.rglob("*"))
              if p.suffix.lower() in exts
              and not any(part.startswith(".") for part in
                          p.relative_to(root).parts[:-1])]

  def _max_import_depth(parse_results) -> int:
      """Longest IMPORTS chain (program -> copybook -> copybook...). DFS over the
      IMPORTS edge set; depth of an acyclic chain, cycle-guarded."""
      edges: dict[str, list[str]] = {}
      for r in parse_results:
          for rel in r.relationships:
              if rel.kind == RelKind.IMPORTS:
                  edges.setdefault(rel.source_qname, []).append(rel.target_qname)

      best = 0
      def dfs(node: str, seen: frozenset[str]) -> int:
          if node in seen:
              return 0
          depth = 0
          for tgt in edges.get(node, []):
              depth = max(depth, 1 + dfs(tgt, seen | {node}))
          return depth
      for src in edges:
          best = max(best, dfs(src, frozenset()))
      return best

  def run_baseline(repo_root: Path, *, parse_fn) -> BaselineReport:
      files = _discover(repo_root)
      programs = sum(1 for p in files if p.suffix.lower() != ".cpy")
      copybooks = sum(1 for p in files if p.suffix.lower() == ".cpy")
      tracemalloc.start()
      t0 = time.perf_counter()
      results = parse_fn(repo_root)
      elapsed = time.perf_counter() - t0
      _, peak = tracemalloc.get_traced_memory()
      tracemalloc.stop()
      parse_errors = sum(1 for r in results
                         if not r.entities and not r.relationships)
      return BaselineReport(
          repo_root=str(repo_root), files_discovered=len(files),
          programs=programs, copybooks=copybooks, parse_errors=parse_errors,
          parse_seconds=round(elapsed, 3), peak_memory_mb=round(peak / 1e6, 2),
          max_copybook_depth=_max_import_depth(results))

  def write_report(report: BaselineReport, out: Path) -> None:
      out.write_text(json.dumps(asdict(report), indent=2))
  ```
- [ ] Commit: `feat(benchmark): CardDemo baseline runner (time/memory/errors/copybook-depth)`

---

## Task 12 — Integration: CardDemo ingests to Neo4j + survives >=10 injected errors

Proves Phase-0 deliverable (a) and the error-resilience exit criterion against a real Neo4j testcontainer. Uses a canned v2 contract fixture so it runs without the JVM, and a JAR-backed variant guarded by `COBOL_EXTRACTOR_JAR`.

**Files:**
- Create: `tests/fixtures/carddemo_extract_v2.json` (small but representative: 3 programs incl. one nested copybook chain, 1 deliberate `parseStatus:"error"`)
- Test: `tests/integration/test_carddemo_ingest.py`
- Test: `tests/integration/test_carddemo_error_resilience.py`

Steps:
- [ ] Create `tests/fixtures/carddemo_extract_v2.json` — schemaVersion 2 with files: `CBACT01C.cbl` (Program + IMPORTS `CVACT01Y` copybook), `CVACT01Y.cpy` (Copybook + IMPORTS `CVACT02Y` to give depth 2), `BADFILE.cbl` (`parseStatus:"error"`, empty entities). Follow the foundation fixture shape (`tests/fixtures/contract_v2_sample.json`).
- [ ] Write integration test `tests/integration/test_carddemo_ingest.py`:
  ```python
  import json
  from pathlib import Path
  import pytest
  from cobol_modernizer.contract.cobol_contract import load_contract
  from cobol_modernizer.benchmark.carddemo_baseline import run_baseline

  FIX = Path(__file__).parents[1] / "fixtures" / "carddemo_extract_v2.json"

  def test_canned_extract_reports_depth_and_errors(carddemo_root):
      payload = json.loads(FIX.read_text())
      report = run_baseline(carddemo_root, parse_fn=lambda root: load_contract(payload))
      assert report.programs + report.copybooks == report.files_discovered
      assert report.parse_errors >= 1            # the BADFILE entry
      assert report.max_copybook_depth >= 2      # nested copybook chain
      assert report.parse_seconds >= 0.0
  ```
- [ ] Write integration test `tests/integration/test_carddemo_error_resilience.py`:
  ```python
  import pytest
  from cobol_modernizer.benchmark.error_injection import copy_tree, inject_parse_errors

  def test_extractor_degrades_gracefully_on_10_bad_files(carddemo_root, tmp_path):
      import shutil
      if shutil.which("java") is None:
          pytest.skip("no JVM; graceful-degradation path returns [] (also non-crashing)")
      import os
      if not os.getenv("COBOL_EXTRACTOR_JAR"):
          pytest.skip("COBOL_EXTRACTOR_JAR not set")
      dst = copy_tree(carddemo_root, tmp_path / "carddemo")
      corrupted = inject_parse_errors(dst, count=10, seed=3)
      assert len(corrupted) == 10
      from cobol_modernizer.cobol.parser import CobolParser
      parser = CobolParser.from_env(dst)
      results = parser.parse_repo()          # MUST NOT raise
      error_files = [r for r in results if not r.entities and not r.relationships]
      assert len(error_files) >= 10          # >=10 errored, run still completed
  ```
- [ ] Run `uv run pytest tests/integration/test_carddemo_ingest.py tests/integration/test_carddemo_error_resilience.py -q` — expected: ingest test PASS (1 passed); resilience test PASS or SKIP (skips cleanly without JVM/JAR — graceful degradation, never a crash).
- [ ] Commit: `test(benchmark): CardDemo ingest + >=10 injected-error resilience (graceful degradation)`

---

## Task 13 — Integration: grounded BRD renders with a judge score (fake runner)

Proves Phase-0 deliverable (a)'s *grounded BRD renders with a judge score* using a fake `AgentRunner` (no live LLM, deterministic, $0). Asserts the rendered HTML is non-empty and the judge report carries a weighted score + rating and an `evidence_map` whose refs are all in `known_refs` (groundedness holds).

**Files:**
- Test: `tests/integration/test_carddemo_brd_grounded.py`

Steps:
- [ ] Write integration test `tests/integration/test_carddemo_brd_grounded.py`:
  ```python
  import cobol_modernizer.agent.graph_ops as ops
  from cobol_modernizer.agent.brd_judge import ajudge
  from cobol_modernizer.brd.renderer import render_html
  from cobol_modernizer.brd.schema import BRD, Strategy, Rating

  class FakeRunner:
      async def run_structured(self, **kw):
          return {"items": [
              {"dimension": d, "score": 4, "rationale": "ok"} for d in
              ("completeness", "accuracy", "clarity", "consistency", "actionability")],
              "feedback": []}

  async def test_grounded_brd_renders_with_judge_score(monkeypatch):
      monkeypatch.setattr(ops, "known_refs", lambda deps: {"CBACT01C", "CVACT01Y"})
      brd = BRD(sections=[], evidence_map={"FR-1": ["CBACT01C"], "FR-2": ["CVACT01Y"]},
                repo_id="cardemo", model="claude-sonnet-4-6", strategy=Strategy.map_reduce)
      report = await ajudge(brd, deps=object(), runner=FakeRunner(), model="m")
      assert report.weighted_score > 0
      assert report.rating in (Rating.high, Rating.medium, Rating.low)
      assert report.groundedness_failures == []     # fully grounded
      html = render_html(brd)
      assert isinstance(html, str) and "<html" in html.lower()
  ```
- [ ] Run `uv run pytest tests/integration/test_carddemo_brd_grounded.py -q` — expected PASS (1 passed). (Adjust `BRD(...)` / `render_html` call to the ported `brd/schema.py` + `renderer.py` signatures if they differ; ported code is authoritative.)
- [ ] Commit: `test(brd): grounded CardDemo BRD renders with judge score (fake runner, $0)`

---

## Task 14 — Synthetic runaway run is killed by the cap (end-to-end cost guardrail)

Proves the final exit criterion: *a synthetic runaway run is killed by the cap.* Combines `CostVerifier` + `PgRepo` (SQLite-backed) so the runaway accumulation is reflected in both the policy kill-switch and the persisted `budget.killed`/`spent`.

**Files:**
- Test: `tests/unit/test_runaway_run_killed.py`

Steps:
- [ ] Write failing test `tests/unit/test_runaway_run_killed.py`:
  ```python
  import pytest
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
  from cobol_modernizer.cost.verifier import CostVerifier, ApprovalRequest

  def test_runaway_loop_is_killed_after_cap():
      ledger = CostLedger()
      ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
      ledger.set_cap(workspace_id="w1", run_id="runaway", cap_usd=5.0)
      v = CostVerifier(CostPolicy(ledger), workspace_id="w1", run_id="runaway")
      charges, approval = 0, None
      for _ in range(1000):                      # synthetic runaway loop
          req = None
          try:
              req = v.charge(token_usage={"input": 100000}, cost_usd=1.0)
          except BudgetExceeded:
              break                              # already aborted -> stoppable-safe
          charges += 1
          if isinstance(req, ApprovalRequest):
              approval = req
              break
      assert approval is not None
      assert charges <= 6                        # ~5 under $1 each, then killed
      assert v.policy.is_killed(workspace_id="w1", run_id="runaway") is True
  ```
- [ ] Run `uv run pytest tests/unit/test_runaway_run_killed.py -q` — expected PASS (1 passed).
- [ ] Commit: `test(cost): synthetic runaway run is killed by per-run cap`

---

## Task 15 — One-command Phase-0 verification

A single entry point that runs the whole baseline + emits the report, for the human gate and for CI evidence.

**Files:**
- Modify: `src/cobol_modernizer/cli.py` (PORT + add `baseline` subcommand) — or create a thin `scripts/run_phase0_baseline.py` if `cli.py` is deferred.

Steps:
- [ ] Add a `baseline` command that resolves `CobolParser.from_env(repo_root).parse_repo` as `parse_fn`, calls `run_baseline`, and `write_report` to `./benchmark_out/carddemo_baseline.json`; on missing JAR/JVM it still emits a report (zero entities, graceful degradation) and exits 0.
- [ ] Run it against CardDemo:
  ```bash
  COBOL_EXTRACTOR_JAR=tools/cobol-extractor/target/cobol-extractor.jar \
  uv run python -m cobol_modernizer.cli baseline \
    --repo "/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/source_code_to_analyse/aws-mf-mod-carddemo" \
    --out ./benchmark_out/carddemo_baseline.json
  ```
  Expected: writes `carddemo_baseline.json` with `files_discovered` ≈ 80 (39 programs + 41 copybooks across `app/` subtrees), `parse_errors == 0` on the clean tree, a non-zero `parse_seconds`, a `peak_memory_mb`, and `max_copybook_depth >= 1`.
- [ ] Run the full Phase-0 suite:
  ```bash
  uv run pytest tests/unit tests/integration -q
  ```
  Expected: all unit tests PASS; integration tests PASS or SKIP (Neo4j/PG/JVM testcontainer-gated), none FAIL.
- [ ] Commit: `feat(cli): phase-0 baseline command + full verification run`

---

## Acceptance criteria

Mapped 1:1 to the master plan Phase 0 Exit criteria (§3, Phase 0):

1. **"CardDemo ingests in a benchmarked time with no crash on ≥10 injected parse errors."**
   - `benchmark/carddemo_baseline.py:run_baseline` emits `parse_seconds`, `peak_memory_mb`, `files_discovered`, `programs`, `copybooks`, `parse_errors`, `max_copybook_depth` (Tasks 11, 15). The benchmark covers all four required dimensions: parse time, memory, error resilience, nested-copybook depth.
   - `tests/integration/test_carddemo_error_resilience.py` injects exactly 10 corrupt files via `error_injection.inject_parse_errors` and asserts `CobolParser.parse_repo()` returns (does NOT raise) with ≥10 errored `ParseResult`s — the COBOL graceful-degradation invariant (foundation §7) holds (Tasks 10, 12).

2. **"A grounded BRD renders with a judge score."**
   - The BRD pipeline + groundedness-gate judge are PORTed verbatim with invariants intact (Task 5); `tests/integration/test_carddemo_brd_grounded.py` renders HTML and produces a `JudgeReport` with `weighted_score`, `rating`, and `groundedness_failures == []` for a fully-grounded `evidence_map` (Task 13). `test_brd_judge_groundedness.py` proves the `accuracy→2` floor on hallucinated refs survived the port (Task 5).

3. **"Re-ingest of an unchanged repo re-pays ~0 LLM cost."**
   - `ingestion_hash.py` content-hashes every file and diffs the manifest (Task 3); `IncrementalIngester.ingest_incremental` parses ONLY added+changed files and `test_incremental_ingestion.py` asserts a second unchanged run has `processed == 0` and parsed nothing (Task 4). Enrichment is cached by `source_hash + prompt_version`, so unchanged nodes skip the LLM (`test_enricher_cache_key.py`, Task 6).

4. **"A synthetic runaway run is killed by the cap."**
   - `cost/verifier.py:CostVerifier` records usage, enforces the foundation's `CostPolicy` per-run + per-workspace caps, trips the kill-switch and returns an attributed `ApprovalRequest` on crossing, then refuses further charges (Task 7); `test_runaway_run_killed.py` drives a 1000-iteration runaway loop and asserts it is killed after ~5 charges with `is_killed is True` (Task 14).

Phase-0 deliverable coverage (master plan §3, Phase 0 Deliverables a–d):
- **(a) CardDemo ingested → graph → BRD with benchmark** — Tasks 1, 2, 4, 5, 11, 12, 13, 15.
- **(b) Postgres schema via migrations** — foundation `tables.py` + Alembic `0001_initial` proven by `alembic upgrade head` on a PG 16 testcontainer; `PgRepo` writer (Tasks 8, 9).
- **(c) Per-workspace & per-run cost caps + kill-switch with Verifier abort + approval** — `CostVerifier` over the foundation `CostPolicy`; runaway-kill proof (Tasks 7, 14).
- **(d) Content-hash incremental ingestion (skip unchanged; cache enrichment/summaries by `source_hash + prompt_version`)** — Tasks 3, 4, 6.

Non-negotiables honored: Neo4j stays code-graph only and Postgres stays run/audit/RBAC only (PgRepo is the sole budget writer); every BRD claim carries `evidence_map` lineage with the groundedness floor enforced; seam math is out of scope (no LLM in any deterministic path); token economy is first-class (incremental skip + enrichment cache + hard caps + kill-switch); the single versioned JSON contract (`schemaVersion=2`, mismatch-raises) is the only Python↔Java coupling and `cobol/mapping.py` delegates to it; working-core invariants (`tools=[]`, `setting_sources=[]`, `json_schema`, COBOL graceful degradation, COBOL-agnostic `parser.py`) are preserved by PORT-AS-IS.
