# COBOL → Java/Spring Boot Migration Platform

Greenfield implementation of a **generic COBOL → Java/Spring Boot converter**. **Phase 0 (baseline + persistence + cost guardrails) is complete** — see `docs/plans/` for the full roadmap (`INDEX.md` first) and `IMPLEMENTATION_PLAN.md` for the master plan.

This README is the runbook for **executing and verifying Phase 0** against any COBOL workload. Drop your COBOL into `source_code_to_analyse/` (git-ignored, so it stays local); nothing in the toolchain is tied to a specific app. AWS CardDemo is a convenient public test workload.

---

## What Phase 0 delivers

- The deterministic analysis core (ProLeap COBOL → JSON contract → Neo4j graph), ported and wired to a **single versioned `schemaVersion=2` JSON contract** (the only Python↔Java coupling; the loader raises on a version mismatch).
- A **Postgres run/audit/RBAC schema** (7 tables) via Alembic migrations.
- **Model tiering** (`resolve_model`) + **fail-closed cost caps with a kill-switch**.
- **Content-hash incremental re-ingest** (re-ingesting an unchanged repo re-pays ~0 LLM cost).
- A **baseline benchmark** for any COBOL repo (parse time, peak memory, parse-error resilience, copybook depth).
- The map/reduce **BRD pipeline + groundedness-gate judge** (lineage-checked).

**Exit criteria (all verified):** the sample ingests benchmarked & survives ≥10 injected parse errors · a grounded BRD renders with a judge score · unchanged re-ingest ≈ $0 · a runaway run is killed by the cap.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | managed by `uv` |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | package/venv manager |
| JDK | 25 | for the ProLeap extractor (Homebrew `openjdk@25` works; it can stay off-PATH — see below) |
| Maven | 3.9+ | builds the extractor JAR |
| Docker | running | only for the integration tests (Neo4j + Postgres testcontainers) and `docker-compose` infra |

Put the COBOL you want to analyse under `source_code_to_analyse/` at the repo root (this directory is git-ignored). Any layout works — the toolchain discovers `*.cbl/*.cob/*.cobol` programs and `*.cpy` copybooks recursively.

```
source_code_to_analyse/
└── <your-cobol-app>/          # any directory tree of COBOL + copybooks
```

For example, to use AWS CardDemo as a test workload:

```bash
git clone https://github.com/aws-samples/aws-mainframe-modernization-carddemo.git \
  source_code_to_analyse/aws-mf-mod-carddemo
# programs in app/cbl/, copybooks in app/cpy/ and app/cpy-bms/
```

To point at a tree outside the repo, pass `--repo <path>` (CLI) or set `COBOL_SAMPLE_DIR=<path>` (tests).

---

## One-time setup

### 1. Install Python dependencies

```bash
cd /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1
uv sync --extra dev
```

### 2. Build the COBOL extractor JAR

The Phase-0 ingest runs the ProLeap extractor as a subprocess. Build the shaded JAR with JDK 25:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home   # adjust to your JDK 25
cd tools/cobol-extractor && JAVA_HOME=$JAVA_HOME mvn -q clean package && cd -
# produces: tools/cobol-extractor/target/cobol-extractor.jar  (emits schemaVersion=2)
```

> The build output (`target/`) is git-ignored. The first build downloads ProLeap/ANTLR deps and may take a few minutes.

### 3. Configure environment

```bash
cp .env.example .env
```

Then set (or export in your shell) the two variables the extractor subprocess needs. **If these are missing, `CobolParser` silently degrades to zero entities** — a misleading "pass":

```bash
export COBOL_EXTRACTOR_JAR="$PWD/tools/cobol-extractor/target/cobol-extractor.jar"
export JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home
export COBOL_MOD_COPYBOOK_DIRS=app/cpy,app/cpy-bms   # copybook dirs relative to the repo being parsed (these match the bundled sample; set to your own)
```

`.env` also documents the model/cost/Neo4j/Postgres/MinIO settings (see `.env.example`).

---

## Run the test suite

```bash
# Unit tests only (fast, no Docker/JAR needed):
uv run --extra dev pytest tests/unit -q

# Full suite incl. integration (needs Docker running + the JAR built + JAVA_HOME):
COBOL_EXTRACTOR_JAR="$PWD/tools/cobol-extractor/target/cobol-extractor.jar" \
JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home \
uv run --extra dev pytest -q
```

Expected: **42 passed**. Integration tests spin up throwaway Neo4j 5.26 and Postgres 16 containers and run the real extractor; they `skip` (not fail) if Docker/Java/JAR are unavailable.

---

## One-command Phase-0 baseline

Runs the **real** extractor over your COBOL and writes a benchmark report. With no
`--repo`/`--out`, it defaults to `./source_code_to_analyse` → `./benchmark_out/baseline.json`:

```bash
COBOL_EXTRACTOR_JAR="$PWD/tools/cobol-extractor/target/cobol-extractor.jar" \
JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home \
COBOL_MOD_COPYBOOK_DIRS=app/cpy,app/cpy-bms \
PYTHONPATH=src \
uv run python -m cobol_modernizer.cli baseline \
  --repo ./source_code_to_analyse/aws-mf-mod-carddemo \
  --out  ./benchmark_out/baseline.json
```

Sample report:

```json
{
  "files_discovered": 106,
  "programs": 44,
  "copybooks": 62,
  "parse_errors": 5,
  "parse_seconds": 14.8,
  "peak_memory_mb": 4.81,
  "max_copybook_depth": 1
}
```

> `PYTHONPATH=src` is needed for `python -m …` (pytest already sets it). The 5 parse errors are genuine `EXEC DLI`/IMS programs ProLeap can't parse — the graceful-degradation path, not a crash.

---

## Optional: stand up backing services

For a persistent dev environment (the test suite uses throwaway containers and doesn't need this):

```bash
docker compose up -d         # Neo4j(+GDS) :7474/:7687 · Postgres :5432 · MinIO :9000/:9001

# Apply the Postgres schema (7 run/audit/RBAC tables):
POSTGRES_URL='postgresql+psycopg://cobol:devpassword@localhost:5432/cobol_modernizer' \
uv run alembic -c alembic.ini upgrade head
```

(The migration is also applied & verified automatically by `tests/integration/test_migrations_apply.py` against a throwaway Postgres.)

---

## How each exit criterion is proven

| Exit criterion | Verified by |
|---|---|
| COBOL ingests, benchmarked | `cli baseline` + `tests/integration/test_cobol_ingest_neo4j.py` (real extractor → live Neo4j; asserts Program nodes) |
| Survives ≥10 injected parse errors | `tests/integration/test_error_resilience.py` |
| Grounded BRD renders with judge score | `tests/integration/test_brd_grounded.py` + `tests/unit/test_brd_judge_groundedness.py` |
| Unchanged re-ingest ≈ $0 | `tests/unit/test_incremental_ingestion.py`, `tests/unit/test_enricher_cache_key.py` |
| Runaway run killed by cap | `tests/unit/test_runaway_run_killed.py`, `tests/unit/test_cost_policy.py` |

---

## Layout

```
src/cobol_modernizer/
  contract/cobol_contract.py   # the single schemaVersion=2 JSON contract loader (raises on mismatch)
  cobol/parser.py, mapping.py  # extractor subprocess driver + thin v2 delegate
  parser.py, neo4j_client.py, schema.py, ingestion.py, ingestion_hash.py
  cost/tiering.py, policy.py, verifier.py     # model tiering + fail-closed caps/kill-switch
  persistence/tables.py, db.py, repo.py, migrations/   # Postgres run/audit/RBAC + Alembic
  agent/ (harness, graph_ops, graph_tools, brd_judge, enricher, …)   # working core (tools=[], setting_sources=[], json_schema)
  brd/ (pipeline, schema, renderer, storage)  # map/reduce BRD + groundedness gate
  benchmark/ (baseline.py, error_injection.py)
  cli.py
tools/cobol-extractor/         # ProLeap Java extractor (com.cobolmodernizer.cobol), emits schemaVersion=2
docs/plans/                    # the decomposed implementation plans + INDEX.md roadmap
tests/unit/, tests/integration/
```

---

## What's next (Phase 1)

Phase 1 (v2 graph enrichment) is the **critical-path barrier** that unblocks the seam engine (Phases 4+). The final Phase-0 review flagged two wiring gaps to address first: add `Neo4jClient.save_manifest`/`load_manifest` (production incremental re-ingest) and write a `repo` property on ingested entities so repo-scoped reads connect the ingest→enrich→BRD chain end-to-end. See `docs/plans/phase-1-v2-graph-enrichment.md`.
