# Phase 6 — Deployment Automation + Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Make the migration of one verified slice **safely cutover-able and stoppable-safe at any commit**. Take the Phase 5 generated Spring Boot service (`artifact.kind='spring_boot_project'`, body in MinIO) and: containerize it reproducibly, wire CI that builds + smoke/health-checks it, establish a **perf baseline against the Equivalence Lab** (Phase 3), drive a **canary release behind a routing enabling-point** (transaction-id / percentage routing fronting the legacy COBOL path) with a **proven, automated rollback**, and stand up **evolutionary-architecture fitness functions** that measure target-state progress on every commit. Every deploy decision is a hard, **attributed RBAC gate** (`gate.gate_key='deploy'` + `approval`), every spend goes through the `CostPolicy`, and the routing decision is data — never an irreversible code change.

**Architecture:** A `deploy` package under `cobol_modernizer` orchestrates: (1) a deterministic Docker build of a generated project pulled from MinIO; (2) smoke/health probes against the running container; (3) a perf-baseline harness that replays the Equivalence Lab golden fixtures through both the canary container and records latency/throughput vs the COBOL baseline; (4) a `RoutingController` enabling-point whose weight (`legacy_pct`/`canary_pct`) is a single mutable row, flipped only behind a passed `deploy` gate; (5) an automated `RollbackGuard` that watches canary error-rate / equivalence-divergence and flips routing back to 100% legacy, recording the event; (6) `FitnessFunction` checks that run on every commit and persist a `fitness_report` artifact tracking target-state progress. All run/audit/routing/rollback state lives in **Postgres** (new `deployment`, `canary_route`, `fitness_check` tables that conform to the foundation's storage split — Neo4j stays code-graph-only). The generated Spring Boot project, container image refs, perf baselines and fitness reports are artifacts in MinIO/Postgres. **Nothing here writes Cypher or calls an LLM in the routing/rollback decision path** — canary promotion is governed by deterministic thresholds + a human gate, exactly like seam math.

**Tech Stack (pinned, from foundation):** Python 3.12 + uv; FastAPI control plane (extend `api.py`); Java 25 + Maven 3.9 + Spring Boot 3.3 (generated project); Docker + docker-compose; GitHub Actions CI; Neo4j 5.24-enterprise + GDS (untouched here); PostgreSQL 16 (routing/deploy/fitness state); MinIO (project bodies, perf baselines, fitness reports); GnuCOBOL 3.2 (Equivalence Lab baseline, Phase 3); pytest + pytest-asyncio (`asyncio_mode=auto`); JUnit 5 for the generated service. `claude-agent-sdk==0.2.87` is present but **not used in this phase's decision path**.

---

## File Structure

Everything below is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── src/cobol_modernizer/
│   ├── deploy/                                    # NEW — Phase 6 deployment automation + canary
│   │   ├── __init__.py
│   │   ├── models.py                              # DeployModels: DeploySpec, SmokeResult, PerfBaseline, RolloutPlan, RollbackEvent (pydantic, json_schema-safe)
│   │   ├── docker_builder.py                      # pull spring_boot_project from MinIO -> deterministic `docker build` -> image ref + digest
│   │   ├── smoke.py                               # health/smoke probe runner against a running container (httpx); maps to deploy gate result
│   │   ├── perf_baseline.py                       # replay Equivalence Lab golden fixtures through canary; capture latency/throughput vs COBOL baseline
│   │   ├── routing.py                             # RoutingController enabling-point: legacy_pct/canary_pct weight, route(key)->target, flip behind gate
│   │   ├── rollback.py                            # RollbackGuard: deterministic thresholds on error-rate + equivalence-divergence -> auto flip to 100% legacy
│   │   ├── canary.py                              # CanaryOrchestrator: ties build->smoke->perf->gate->route flip->observe->(promote|rollback)
│   │   ├── fitness.py                             # FitnessFunction registry + run_fitness(): target-state progress checks, persisted per commit
│   │   └── stoppable.py                           # stoppable-safe invariant checker: every commit leaves routing in a valid recoverable state
│   ├── persistence/
│   │   └── tables.py                              # MODIFY — add Deployment, CanaryRoute, FitnessCheck tables (Postgres, run/audit split honored)
│   └── api.py                                     # MODIFY — add /api/workspaces/{id}/deploy, /canary, /rollback, /fitness, /routing (SSE deploy stream)
├── tools/cobol-extractor/                          # untouched in Phase 6
├── generated/                                      # Phase 5 emits the spring_boot_project here / to MinIO
│   └── account-view-service/                       # the Phase 2/5 slice used as the canary subject (fixture mirror for tests)
│       ├── Dockerfile                              # NEW (template emitted/validated here) — multi-stage Maven->JRE, non-root, healthcheck
│       └── pom.xml                                 # (from Phase 5; referenced by docker_builder)
├── infra/
│   └── deploy/
│       ├── canary-compose.yml                      # NEW — legacy(COBOL shim) + canary(spring) + router, for local canary rehearsal
│       └── router.Dockerfile                       # NEW — thin reverse-proxy image fronting legacy vs canary (the enabling-point)
├── .github/
│   └── workflows/
│       ├── ci.yml                                  # NEW — build+test python core; build+test generated service; container smoke
│       └── canary.yml                              # NEW — gated canary workflow (build->smoke->perf->fitness->await deploy gate->route)
└── tests/
    ├── unit/
    │   ├── test_deploy_models.py                   # DeploySpec/PerfBaseline/RolloutPlan json_schema round-trips
    │   ├── test_routing.py                         # RoutingController weight math + deterministic route(key) + flip-requires-gate
    │   ├── test_rollback.py                         # RollbackGuard threshold trips -> auto 100% legacy + RollbackEvent
    │   ├── test_fitness.py                          # FitnessFunction registry, pass/fail, fitness_report shape, regression detection
    │   ├── test_stoppable.py                        # stoppable-safe invariant holds across simulated commit states
    │   ├── test_smoke.py                            # SmokeRunner maps probe results -> deploy gate result (httpx mock)
    │   └── test_deploy_tables.py                    # Deployment/CanaryRoute/FitnessCheck round-trip (sqlite shape)
    ├── integration/
    │   ├── test_docker_builder.py                  # builds the generated Dockerfile (skipif no docker), asserts image digest + healthcheck
    │   ├── test_perf_baseline.py                   # perf harness replays fixtures, produces PerfBaseline vs COBOL golden, ratio gate
    │   ├── test_canary_end_to_end.py               # build->smoke->perf->gate(approved)->flip->observe->promote (fake docker + Equivalence Lab stub)
    │   ├── test_canary_rollback_proven.py          # inject canary divergence -> RollbackGuard flips to legacy, rollback proven + recorded
    │   └── test_deploy_api.py                       # /deploy + /canary + /rollback + /fitness routes, attributed approval enforced
    └── fixtures/
        ├── spring_boot_project_sample/             # minimal generated project stand-in (pom + Dockerfile + one endpoint) for builder tests
        ├── perf_golden_baseline.json               # COBOL baseline latency/throughput per fixture (from Equivalence Lab)
        ├── canary_fixtures.jsonl                    # captured golden input/output records replayed through both paths
        └── fitness_targets.json                     # target-state thresholds (coverage, divergence, p95 ratio, seams-migrated, no-identity-drift)
```

**Single-responsibility summary**

| File | Responsibility |
|---|---|
| `deploy/models.py` | All Phase-6 pydantic models; `json_schema`-safe; the typed contracts for spec/results/plans/events. |
| `deploy/docker_builder.py` | Reproducibly build a container image from a MinIO `spring_boot_project` artifact; return image ref + sha256 digest. |
| `deploy/smoke.py` | Probe `/actuator/health` + slice endpoints on a running container; produce a `deploy`-gate `SmokeResult`. |
| `deploy/perf_baseline.py` | Replay Equivalence Lab golden fixtures through canary; record p50/p95 + throughput vs COBOL baseline; compute ratio. |
| `deploy/routing.py` | The enabling-point. Deterministic `route(key)`; weight is a single Postgres row; `flip()` requires a passed `deploy` gate. |
| `deploy/rollback.py` | `RollbackGuard`: deterministic thresholds → auto-flip to 100% legacy, write `RollbackEvent`; **proves** rollback. |
| `deploy/canary.py` | Orchestrates the full canary lifecycle behind gates + `CostPolicy`. |
| `deploy/fitness.py` | Evolutionary-architecture fitness functions; runs per commit; persists `fitness_report`; flags regressions. |
| `deploy/stoppable.py` | Asserts the migration is stoppable-safe at any commit (routing always recoverable to 100% legacy). |
| `persistence/tables.py` | Adds `deployment`, `canary_route`, `fitness_check` tables (Postgres run/audit split). |
| `api.py` | Control-plane endpoints + SSE for the deploy/canary lifecycle; enforces attributed approval on the `deploy` gate. |
| `infra/deploy/*` | Local canary rehearsal: router + legacy shim + canary, the same enabling-point as prod. |
| `.github/workflows/*` | CI build/test + gated canary workflow. |

**Cross-phase contracts consumed verbatim (foundation §2, §3, §4):**
- `artifact.kind='spring_boot_project'`, `artifact.object_uri` (MinIO), `artifact.content_hash`, `artifact.evidence_map`.
- `artifact.kind='equivalence_report'` and the Equivalence Lab golden fixtures + tolerance rules (Phase 3) — the perf baseline and rollback divergence checks **reuse** the Lab's diff/tolerance, never reinvent it.
- Postgres `gate(gate_key='deploy', threshold JSONB, result JSONB, status)` and `approval(decision, approver_email, approver_role, risk_accepted, rationale)` — the deploy gate is an **attributed RBAC** decision.
- `CostPolicy(ledger).check(...)` / `record_usage(...)` / `BudgetExceeded` — perf replays and builds are budgeted compute; a runaway canary loop is killed by the cap.
- `journey_stage.stage_key='deploy'` (ordinal last) and `agent_run` for any LLM use (none in the decision path).

---

## Tasks

### Task 6.0 — `deploy` package skeleton + models

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/models.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_deploy_models.py`

Steps:
- [ ] Write failing test `tests/unit/test_deploy_models.py`:
  ```python
  from cobol_modernizer.deploy.models import (
      DeploySpec, SmokeResult, PerfBaseline, RolloutPlan, RollbackEvent, FitnessReport,
  )

  def test_deploy_spec_roundtrip():
      spec = DeploySpec(
          workspace_id="w1",
          artifact_id="a-spring-1",
          slice_name="account-view-service",
          image_ref="account-view-service:abc123",
          image_digest="sha256:" + "0" * 64,
      )
      dumped = spec.model_dump()
      assert DeploySpec(**dumped) == spec
      # json_schema-safe: serializes with no custom types
      assert spec.model_dump_json().startswith("{")

  def test_perf_baseline_ratio():
      pb = PerfBaseline(
          slice_name="account-view-service",
          cobol_p95_ms=120.0,
          canary_p95_ms=90.0,
          cobol_throughput_rps=50.0,
          canary_throughput_rps=70.0,
          fixtures=12,
      )
      # canary faster -> ratio < 1.0 is good
      assert pb.p95_ratio == 0.75
      assert pb.meets(max_p95_ratio=1.2) is True

  def test_rollout_plan_weights_sum_to_100():
      plan = RolloutPlan(canary_pct=10, legacy_pct=90)
      assert plan.canary_pct + plan.legacy_pct == 100
      assert plan.is_full_legacy() is False
      assert RolloutPlan(canary_pct=0, legacy_pct=100).is_full_legacy() is True

  def test_rollback_event_records_reason():
      ev = RollbackEvent(
          workspace_id="w1", slice_name="account-view-service",
          reason="equivalence_divergence", from_canary_pct=10, to_canary_pct=0,
          triggered_by="auto",
      )
      assert ev.to_canary_pct == 0
      assert ev.triggered_by in ("auto", "human")
  ```
- [ ] Run `uv run pytest tests/unit/test_deploy_models.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.deploy'`.
- [ ] Create `src/cobol_modernizer/deploy/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/deploy/models.py`:
  ```python
  """Phase-6 deployment/canary typed contracts. All json_schema-safe (plain
  scalars/lists), so any LLM-facing summary can serialize them — though the
  routing/rollback decision path uses ZERO LLM."""
  from __future__ import annotations

  from typing import Literal
  from pydantic import BaseModel, Field, model_validator


  class DeploySpec(BaseModel):
      workspace_id: str
      artifact_id: str                 # artifact.id of the spring_boot_project
      slice_name: str                  # e.g. "account-view-service"
      image_ref: str                   # tag, e.g. "account-view-service:abc123"
      image_digest: str                # "sha256:..." — reproducibility anchor


  class SmokeResult(BaseModel):
      slice_name: str
      health_ok: bool
      endpoints_ok: int
      endpoints_total: int
      failures: list[str] = Field(default_factory=list)

      @property
      def passed(self) -> bool:
          return self.health_ok and self.endpoints_ok == self.endpoints_total


  class PerfBaseline(BaseModel):
      slice_name: str
      cobol_p95_ms: float
      canary_p95_ms: float
      cobol_throughput_rps: float
      canary_throughput_rps: float
      fixtures: int

      @property
      def p95_ratio(self) -> float:
          if self.cobol_p95_ms <= 0:
              return float("inf")
          return round(self.canary_p95_ms / self.cobol_p95_ms, 4)

      def meets(self, *, max_p95_ratio: float) -> bool:
          return self.p95_ratio <= max_p95_ratio


  class RolloutPlan(BaseModel):
      canary_pct: int = Field(ge=0, le=100)
      legacy_pct: int = Field(ge=0, le=100)

      @model_validator(mode="after")
      def _sum_100(self) -> "RolloutPlan":
          if self.canary_pct + self.legacy_pct != 100:
              raise ValueError("canary_pct + legacy_pct must equal 100")
          return self

      def is_full_legacy(self) -> bool:
          return self.canary_pct == 0


  class RollbackEvent(BaseModel):
      workspace_id: str
      slice_name: str
      reason: str                      # error_rate | equivalence_divergence | smoke_failed | human
      from_canary_pct: int
      to_canary_pct: int
      triggered_by: Literal["auto", "human"]


  class FitnessCheckResult(BaseModel):
      key: str
      passed: bool
      measured: float
      threshold: float
      direction: Literal["max", "min"]   # "max": measured<=threshold ok; "min": measured>=threshold ok


  class FitnessReport(BaseModel):
      workspace_id: str
      commit_sha: str
      checks: list[FitnessCheckResult] = Field(default_factory=list)

      @property
      def passed(self) -> bool:
          return all(c.passed for c in self.checks)

      def regressions(self, prior: "FitnessReport | None") -> list[str]:
          if prior is None:
              return [c.key for c in self.checks if not c.passed]
          prior_by_key = {c.key: c for c in prior.checks}
          out: list[str] = []
          for c in self.checks:
              p = prior_by_key.get(c.key)
              if p is not None and p.passed and not c.passed:
                  out.append(c.key)
          return out
  ```
- [ ] Run `uv run pytest tests/unit/test_deploy_models.py` — expected PASS (4 passed).
- [ ] Commit: `feat(deploy): phase-6 deployment/canary typed models`

---

### Task 6.1 — Postgres deploy/canary/fitness tables

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/tables.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_deploy_tables.py`

These honor the foundation storage split: Neo4j carries zero deploy/routing state; everything below is Postgres run/audit/version state.

```
deployment        -- one built+probed candidate (a container image of a slice)
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  artifact_id     UUID FK -> artifact(id)         -- the spring_boot_project
  slice_name      TEXT NOT NULL
  image_ref       TEXT NOT NULL
  image_digest    TEXT NOT NULL                    -- sha256 reproducibility anchor
  smoke_passed    BOOLEAN NOT NULL DEFAULT false
  perf_baseline   JSONB NOT NULL DEFAULT '{}'      -- PerfBaseline body
  status          TEXT NOT NULL DEFAULT 'built'    -- built|smoked|baselined|canarying|promoted|rolled_back
  created_by      TEXT NOT NULL                    -- RBAC identity
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()

canary_route      -- the enabling-point weight; exactly one active row per slice
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  slice_name      TEXT NOT NULL
  deployment_id   UUID FK -> deployment(id)        -- the canary image currently behind the route
  canary_pct      INT NOT NULL DEFAULT 0           -- 0 == full legacy (stoppable-safe default)
  legacy_pct      INT NOT NULL DEFAULT 100
  active          BOOLEAN NOT NULL DEFAULT true
  rollback_reason TEXT                              -- set when auto/human rolled back
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (workspace_id, slice_name, active)         -- one active route per slice

fitness_check     -- one fitness-function run per commit
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  commit_sha      TEXT NOT NULL
  report          JSONB NOT NULL DEFAULT '{}'       -- FitnessReport body
  passed          BOOLEAN NOT NULL DEFAULT false
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (workspace_id, commit_sha)
```

Steps:
- [ ] Write failing test `tests/unit/test_deploy_tables.py`:
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session
  from cobol_modernizer.persistence.tables import (
      Base, Workspace, Deployment, CanaryRoute, FitnessCheck,
  )

  def test_deploy_route_fitness_roundtrip():
      eng = create_engine("sqlite://")
      Base.metadata.create_all(eng)
      with Session(eng) as s:
          ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                         created_by="cwijay@biz2bricks.ai")
          s.add(ws); s.flush()
          d = Deployment(workspace_id=ws.id, artifact_id=None,
                         slice_name="account-view-service",
                         image_ref="account-view-service:abc123",
                         image_digest="sha256:" + "0" * 64,
                         created_by="cwijay@biz2bricks.ai")
          s.add(d); s.flush()
          # stoppable-safe default: a new route starts full-legacy
          r = CanaryRoute(workspace_id=ws.id, slice_name="account-view-service",
                          deployment_id=d.id, canary_pct=0, legacy_pct=100, active=True)
          s.add(r); s.flush()
          fc = FitnessCheck(workspace_id=ws.id, commit_sha="deadbeef",
                            report={"checks": []}, passed=True)
          s.add(fc); s.commit()
          assert r.canary_pct == 0 and r.legacy_pct == 100
          assert d.status == "built"
          assert fc.passed is True
  ```
- [ ] Run `uv run pytest tests/unit/test_deploy_tables.py` — expected FAIL: `ImportError: cannot import name 'Deployment'`.
- [ ] Append to `src/cobol_modernizer/persistence/tables.py` (use the file's existing `Base`, `String`-UUID + `default=lambda: str(uuid4())`, and `JSON` portable type convention from foundation Task 3.1):
  ```python
  from datetime import datetime, timezone
  from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, JSON
  from sqlalchemy.orm import Mapped, mapped_column
  from uuid import uuid4

  def _uuid() -> str:
      return str(uuid4())

  def _now() -> datetime:
      return datetime.now(timezone.utc)


  class Deployment(Base):
      __tablename__ = "deployment"
      id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
      workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
      artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifact.id"), nullable=True)
      slice_name: Mapped[str] = mapped_column(String, nullable=False)
      image_ref: Mapped[str] = mapped_column(String, nullable=False)
      image_digest: Mapped[str] = mapped_column(String, nullable=False)
      smoke_passed: Mapped[bool] = mapped_column(Boolean, default=False)
      perf_baseline: Mapped[dict] = mapped_column(JSON, default=dict)
      status: Mapped[str] = mapped_column(String, default="built")
      created_by: Mapped[str] = mapped_column(String, nullable=False)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


  class CanaryRoute(Base):
      __tablename__ = "canary_route"
      id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
      workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
      slice_name: Mapped[str] = mapped_column(String, nullable=False)
      deployment_id: Mapped[str | None] = mapped_column(ForeignKey("deployment.id"), nullable=True)
      canary_pct: Mapped[int] = mapped_column(Integer, default=0)
      legacy_pct: Mapped[int] = mapped_column(Integer, default=100)
      active: Mapped[bool] = mapped_column(Boolean, default=True)
      rollback_reason: Mapped[str | None] = mapped_column(String, nullable=True)
      updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


  class FitnessCheck(Base):
      __tablename__ = "fitness_check"
      id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
      workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
      commit_sha: Mapped[str] = mapped_column(String, nullable=False)
      report: Mapped[dict] = mapped_column(JSON, default=dict)
      passed: Mapped[bool] = mapped_column(Boolean, default=False)
      created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
  ```
  (If `Base`/imports already exist at the top of the file, reuse them rather than re-declaring; keep a single `Base`.)
- [ ] Run `uv run pytest tests/unit/test_deploy_tables.py` — expected PASS (1 passed).
- [ ] Add an Alembic migration `src/cobol_modernizer/persistence/migrations/0002_deploy.py` creating the three tables (mirror columns above).
- [ ] Commit: `feat(persistence): deployment/canary_route/fitness_check tables (stoppable-safe default)`

---

### Task 6.2 — RoutingController enabling-point (flip requires a passed gate)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/routing.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_routing.py`

The routing weight is **data, not code** (Fowler enabling-point): a single mutable percentage. `route(key)` is deterministic (same key → same target) so a given account always lands on the same path during a canary — avoiding split-brain on stateful reads. `flip()` is the ONLY way to raise canary traffic and it **requires** a passed `deploy` gate token; default and reset is always 100% legacy (stoppable-safe).

Steps:
- [ ] Write failing test `tests/unit/test_routing.py`:
  ```python
  import pytest
  from cobol_modernizer.deploy.routing import RoutingController, RouteTarget, GateNotPassed

  def test_default_is_full_legacy():
      rc = RoutingController(slice_name="account-view-service")
      assert rc.canary_pct == 0
      assert rc.route("ACCT-00000000001") is RouteTarget.LEGACY

  def test_flip_requires_passed_deploy_gate():
      rc = RoutingController(slice_name="account-view-service")
      with pytest.raises(GateNotPassed):
          rc.flip(canary_pct=10, deploy_gate_passed=False)
      rc.flip(canary_pct=10, deploy_gate_passed=True)
      assert rc.canary_pct == 10

  def test_route_is_deterministic_per_key():
      rc = RoutingController(slice_name="s")
      rc.flip(canary_pct=50, deploy_gate_passed=True)
      a = rc.route("ACCT-42")
      b = rc.route("ACCT-42")
      assert a is b  # same key -> same target every call

  def test_canary_share_matches_weight_within_tolerance():
      rc = RoutingController(slice_name="s")
      rc.flip(canary_pct=20, deploy_gate_passed=True)
      keys = [f"ACCT-{i:08d}" for i in range(10000)]
      canary = sum(1 for k in keys if rc.route(k) is RouteTarget.CANARY)
      share = canary / len(keys)
      assert 0.15 <= share <= 0.25   # ~20% within hashing tolerance

  def test_reset_to_legacy_is_always_allowed():
      rc = RoutingController(slice_name="s")
      rc.flip(canary_pct=100, deploy_gate_passed=True)
      rc.reset_to_legacy(reason="rollback")   # no gate needed to make SAFER
      assert rc.canary_pct == 0
      assert rc.route("anything") is RouteTarget.LEGACY
  ```
- [ ] Run `uv run pytest tests/unit/test_routing.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/routing.py`:
  ```python
  """The routing enabling-point. Weight is data (a percentage), never an
  irreversible code change. Increasing canary traffic requires a PASSED deploy
  gate; decreasing to legacy is always allowed (making the system safer must
  never be blocked). route(key) is a deterministic hash so a given account is
  consistently served by one path during a canary."""
  from __future__ import annotations

  import hashlib
  from enum import Enum


  class RouteTarget(Enum):
      LEGACY = "legacy"
      CANARY = "canary"


  class GateNotPassed(Exception):
      """Raised when raising canary traffic without a passed deploy gate."""


  class RoutingController:
      def __init__(self, *, slice_name: str, canary_pct: int = 0) -> None:
          self.slice_name = slice_name
          self._canary_pct = canary_pct

      @property
      def canary_pct(self) -> int:
          return self._canary_pct

      @property
      def legacy_pct(self) -> int:
          return 100 - self._canary_pct

      def flip(self, *, canary_pct: int, deploy_gate_passed: bool) -> None:
          if not 0 <= canary_pct <= 100:
              raise ValueError("canary_pct must be 0..100")
          if canary_pct > self._canary_pct and not deploy_gate_passed:
              raise GateNotPassed(
                  f"raising canary to {canary_pct}% requires a passed deploy gate"
              )
          self._canary_pct = canary_pct

      def reset_to_legacy(self, *, reason: str) -> None:
          """Always allowed — getting safer is never gated."""
          self._canary_pct = 0

      def route(self, key: str) -> RouteTarget:
          if self._canary_pct <= 0:
              return RouteTarget.LEGACY
          if self._canary_pct >= 100:
              return RouteTarget.CANARY
          digest = hashlib.sha256(f"{self.slice_name}:{key}".encode()).digest()
          bucket = int.from_bytes(digest[:4], "big") % 100
          return RouteTarget.CANARY if bucket < self._canary_pct else RouteTarget.LEGACY
  ```
- [ ] Run `uv run pytest tests/unit/test_routing.py` — expected PASS (5 passed).
- [ ] Commit: `feat(deploy): routing enabling-point (gated flip, deterministic per-key, legacy-default)`

---

### Task 6.3 — RollbackGuard (proven, automated rollback)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/rollback.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_rollback.py`

Deterministic thresholds (no LLM). The guard observes canary error-rate and equivalence-divergence (the latter reuses the Phase 3 Equivalence Lab diff). On any breach it calls `RoutingController.reset_to_legacy` and emits a `RollbackEvent`. "Rollback proven" = a test that injects a breach and asserts the route is back at 100% legacy.

Steps:
- [ ] Write failing test `tests/unit/test_rollback.py`:
  ```python
  from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
  from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth

  def _canarying():
      rc = RoutingController(slice_name="s")
      rc.flip(canary_pct=10, deploy_gate_passed=True)
      return rc

  def test_healthy_canary_stays():
      rc = _canarying()
      guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                            max_error_rate=0.01, max_divergence_rate=0.0)
      ev = guard.observe(CanaryHealth(requests=1000, errors=2, divergences=0))
      assert ev is None
      assert rc.canary_pct == 10

  def test_error_rate_breach_rolls_back():
      rc = _canarying()
      guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                            max_error_rate=0.01, max_divergence_rate=0.0)
      ev = guard.observe(CanaryHealth(requests=1000, errors=50, divergences=0))
      assert ev is not None
      assert ev.reason == "error_rate"
      assert ev.to_canary_pct == 0
      assert rc.route("anything") is RouteTarget.LEGACY   # rollback proven

  def test_equivalence_divergence_breach_rolls_back():
      rc = _canarying()
      guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                            max_error_rate=0.05, max_divergence_rate=0.0)
      ev = guard.observe(CanaryHealth(requests=1000, errors=0, divergences=1))
      assert ev is not None
      assert ev.reason == "equivalence_divergence"
      assert rc.canary_pct == 0
  ```
- [ ] Run `uv run pytest tests/unit/test_rollback.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/rollback.py`:
  ```python
  """Automated, proven rollback. Deterministic thresholds only — no LLM in the
  decision path. A single equivalence divergence (vs the Phase 3 Equivalence Lab
  golden master) is enough to roll back in a card domain (max_divergence_rate
  defaults to 0.0)."""
  from __future__ import annotations

  from dataclasses import dataclass
  from cobol_modernizer.deploy.models import RollbackEvent
  from cobol_modernizer.deploy.routing import RoutingController


  @dataclass(frozen=True)
  class CanaryHealth:
      requests: int
      errors: int
      divergences: int          # canary-vs-COBOL diffs outside tolerance (Equivalence Lab)

      @property
      def error_rate(self) -> float:
          return self.errors / self.requests if self.requests else 0.0

      @property
      def divergence_rate(self) -> float:
          return self.divergences / self.requests if self.requests else 0.0


  class RollbackGuard:
      def __init__(self, routing: RoutingController, *, workspace_id: str,
                   slice_name: str, max_error_rate: float = 0.01,
                   max_divergence_rate: float = 0.0) -> None:
          self.routing = routing
          self.workspace_id = workspace_id
          self.slice_name = slice_name
          self.max_error_rate = max_error_rate
          self.max_divergence_rate = max_divergence_rate

      def observe(self, health: CanaryHealth) -> RollbackEvent | None:
          reason: str | None = None
          if health.divergence_rate > self.max_divergence_rate:
              reason = "equivalence_divergence"
          elif health.error_rate > self.max_error_rate:
              reason = "error_rate"
          if reason is None:
              return None
          from_pct = self.routing.canary_pct
          self.routing.reset_to_legacy(reason=reason)
          return RollbackEvent(
              workspace_id=self.workspace_id, slice_name=self.slice_name,
              reason=reason, from_canary_pct=from_pct, to_canary_pct=0,
              triggered_by="auto",
          )
  ```
- [ ] Run `uv run pytest tests/unit/test_rollback.py` — expected PASS (3 passed).
- [ ] Commit: `feat(deploy): RollbackGuard with deterministic error/divergence thresholds`

---

### Task 6.4 — Evolutionary-architecture fitness functions

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/fitness.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/fitness_targets.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_fitness.py`

Fitness functions track **target-state progress** on every commit: equivalence divergence (max 0), canary p95 ratio vs COBOL (max 1.2), test coverage of the slice (min), seams migrated count (min, increasing), and a hard "no identity drift on writer slices" check (reuses Phase 5/Equivalence Lab signal). They're deterministic and persisted as a `fitness_report` artifact / `fitness_check` row.

Steps:
- [ ] Create fixture `tests/fixtures/fitness_targets.json`:
  ```json
  {
    "equivalence_divergence_rate": {"threshold": 0.0, "direction": "max"},
    "canary_p95_ratio":           {"threshold": 1.2, "direction": "max"},
    "slice_test_coverage":        {"threshold": 0.8, "direction": "min"},
    "seams_migrated":             {"threshold": 1,   "direction": "min"},
    "identity_drift_writers":     {"threshold": 0.0, "direction": "max"}
  }
  ```
- [ ] Write failing test `tests/unit/test_fitness.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.deploy.fitness import run_fitness, load_targets
  from cobol_modernizer.deploy.models import FitnessReport

  FIX = Path(__file__).parents[1] / "fixtures" / "fitness_targets.json"

  def test_all_pass():
      targets = load_targets(json.loads(FIX.read_text()))
      report = run_fitness(
          workspace_id="w1", commit_sha="abc",
          measured={
              "equivalence_divergence_rate": 0.0,
              "canary_p95_ratio": 0.75,
              "slice_test_coverage": 0.9,
              "seams_migrated": 1,
              "identity_drift_writers": 0.0,
          },
          targets=targets,
      )
      assert isinstance(report, FitnessReport)
      assert report.passed is True
      assert len(report.checks) == 5

  def test_divergence_fails():
      targets = load_targets(json.loads(FIX.read_text()))
      report = run_fitness(
          workspace_id="w1", commit_sha="abc",
          measured={
              "equivalence_divergence_rate": 0.01,   # any divergence fails
              "canary_p95_ratio": 0.9,
              "slice_test_coverage": 0.9,
              "seams_migrated": 1,
              "identity_drift_writers": 0.0,
          },
          targets=targets,
      )
      assert report.passed is False
      bad = [c.key for c in report.checks if not c.passed]
      assert bad == ["equivalence_divergence_rate"]

  def test_regression_detection_against_prior():
      targets = load_targets(json.loads(FIX.read_text()))
      good = {"equivalence_divergence_rate": 0.0, "canary_p95_ratio": 0.9,
              "slice_test_coverage": 0.9, "seams_migrated": 1, "identity_drift_writers": 0.0}
      prior = run_fitness(workspace_id="w1", commit_sha="p", measured=good, targets=targets)
      worse = dict(good, canary_p95_ratio=2.0)
      now = run_fitness(workspace_id="w1", commit_sha="n", measured=worse, targets=targets)
      assert now.regressions(prior) == ["canary_p95_ratio"]
  ```
- [ ] Run `uv run pytest tests/unit/test_fitness.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/fitness.py`:
  ```python
  """Evolutionary-architecture fitness functions tracking target-state progress.
  Deterministic; run on every commit by CI and persisted as a fitness_check row.
  'direction'='max' means measured must be <= threshold; 'min' means >="""
  from __future__ import annotations

  from dataclasses import dataclass
  from cobol_modernizer.deploy.models import FitnessReport, FitnessCheckResult


  @dataclass(frozen=True)
  class Target:
      key: str
      threshold: float
      direction: str   # "max" | "min"

      def check(self, measured: float) -> bool:
          if self.direction == "max":
              return measured <= self.threshold
          return measured >= self.threshold


  def load_targets(raw: dict) -> list[Target]:
      return [
          Target(key=k, threshold=float(v["threshold"]), direction=v["direction"])
          for k, v in raw.items()
      ]


  def run_fitness(*, workspace_id: str, commit_sha: str,
                  measured: dict[str, float], targets: list[Target]) -> FitnessReport:
      checks: list[FitnessCheckResult] = []
      for t in targets:
          m = float(measured[t.key])
          checks.append(FitnessCheckResult(
              key=t.key, passed=t.check(m), measured=m,
              threshold=t.threshold, direction=t.direction,
          ))
      return FitnessReport(workspace_id=workspace_id, commit_sha=commit_sha, checks=checks)
  ```
- [ ] Run `uv run pytest tests/unit/test_fitness.py` — expected PASS (3 passed).
- [ ] Commit: `feat(deploy): evolutionary-architecture fitness functions + regression detection`

---

### Task 6.5 — Stoppable-safe invariant checker

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/stoppable.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_stoppable.py`

The master plan exit criterion is "migration is **stoppable-safe at any commit**." This codifies the invariant: at any commit the active route must be recoverable to 100% legacy with no data loss — i.e. (a) canary traffic is only ever served when a passed deploy gate exists, (b) the legacy COBOL path is never removed while any route references it, and (c) `reset_to_legacy` is always reachable. `assert_stoppable_safe` evaluates a `RouteSnapshot` and raises if the invariant is violated; CI runs it per commit.

Steps:
- [ ] Write failing test `tests/unit/test_stoppable.py`:
  ```python
  import pytest
  from cobol_modernizer.deploy.stoppable import (
      RouteSnapshot, assert_stoppable_safe, NotStoppableSafe,
  )

  def test_full_legacy_is_safe():
      assert_stoppable_safe(RouteSnapshot(
          canary_pct=0, legacy_path_available=True, deploy_gate_passed=False))

  def test_gated_canary_is_safe():
      assert_stoppable_safe(RouteSnapshot(
          canary_pct=10, legacy_path_available=True, deploy_gate_passed=True))

  def test_canary_without_gate_is_unsafe():
      with pytest.raises(NotStoppableSafe, match="gate"):
          assert_stoppable_safe(RouteSnapshot(
              canary_pct=10, legacy_path_available=True, deploy_gate_passed=False))

  def test_canary_with_legacy_removed_is_unsafe():
      with pytest.raises(NotStoppableSafe, match="legacy"):
          assert_stoppable_safe(RouteSnapshot(
              canary_pct=10, legacy_path_available=False, deploy_gate_passed=True))

  def test_full_canary_with_legacy_gone_is_unsafe_until_retired():
      # cutover (100% canary) is only stoppable-safe once the slice is formally
      # retired AND legacy still reachable for emergency rollback
      with pytest.raises(NotStoppableSafe):
          assert_stoppable_safe(RouteSnapshot(
              canary_pct=100, legacy_path_available=False, deploy_gate_passed=True))
  ```
- [ ] Run `uv run pytest tests/unit/test_stoppable.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/stoppable.py`:
  ```python
  """Stoppable-safe invariant: at ANY commit the migration must be recoverable to
  100% legacy without data loss. Enforced in CI so no commit can leave the canary
  in an unrecoverable state."""
  from __future__ import annotations

  from dataclasses import dataclass


  class NotStoppableSafe(Exception):
      """Raised when a route snapshot cannot be safely rolled back to legacy."""


  @dataclass(frozen=True)
  class RouteSnapshot:
      canary_pct: int
      legacy_path_available: bool
      deploy_gate_passed: bool


  def assert_stoppable_safe(snap: RouteSnapshot) -> None:
      if snap.canary_pct == 0:
          return  # full legacy is always safe
      if not snap.deploy_gate_passed:
          raise NotStoppableSafe(
              "canary traffic served without a passed deploy gate")
      if not snap.legacy_path_available:
          raise NotStoppableSafe(
              "legacy path removed while canary route still active — "
              "no rollback target")
  ```
- [ ] Run `uv run pytest tests/unit/test_stoppable.py` — expected PASS (5 passed).
- [ ] Commit: `feat(deploy): stoppable-safe invariant checker (recoverable-to-legacy at any commit)`

---

### Task 6.6 — Deterministic Docker build from a MinIO project artifact

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/docker_builder.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/generated/account-view-service/Dockerfile`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/spring_boot_project_sample/Dockerfile`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/spring_boot_project_sample/pom.xml`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_docker_builder.py`

`docker_builder` resolves the `spring_boot_project` artifact (`object_uri` in MinIO), extracts it to a build dir, runs `docker build`, and returns a `DeploySpec` with an `image_digest` (sha256). Unit-level: the builder's pure planning function (`build_command`) is tested without Docker; integration: an actual build behind a `skipif` guard.

Steps:
- [ ] Create `generated/account-view-service/Dockerfile` (the template the codegen workbench emits; validated here as the canary subject):
  ```dockerfile
  # syntax=docker/dockerfile:1
  # Multi-stage, reproducible, non-root, with a Spring Actuator healthcheck.
  FROM maven:3.9-eclipse-temurin-25 AS build
  WORKDIR /src
  COPY pom.xml .
  RUN mvn -B -q dependency:go-offline
  COPY src ./src
  RUN mvn -B -q -DskipTests package

  FROM eclipse-temurin:25-jre AS runtime
  WORKDIR /app
  RUN useradd -r -u 1001 spring
  COPY --from=build /src/target/*.jar /app/app.jar
  USER spring
  EXPOSE 8080
  HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -qO- http://localhost:8080/actuator/health || exit 1
  ENTRYPOINT ["java", "-jar", "/app/app.jar"]
  ```
- [ ] Create the minimal `tests/fixtures/spring_boot_project_sample/pom.xml` (a tiny Spring Boot 3.3 app exposing `/actuator/health` and one slice endpoint) and a copy of the Dockerfile above into the fixture dir.
- [ ] Write failing test `tests/integration/test_docker_builder.py`:
  ```python
  import shutil
  import pytest
  from pathlib import Path
  from cobol_modernizer.deploy.docker_builder import build_command, build_image

  FIX = Path(__file__).parents[1] / "fixtures" / "spring_boot_project_sample"

  def test_build_command_is_deterministic():
      cmd = build_command(context_dir=str(FIX), image_ref="account-view-service:test")
      # pinned, reproducible: no --pull random, fixed tag, --progress plain
      assert cmd[:2] == ["docker", "build"]
      assert "--tag" in cmd and "account-view-service:test" in cmd
      assert str(FIX) in cmd

  @pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
  def test_build_produces_digest():
      spec = build_image(
          workspace_id="w1", artifact_id="a1",
          slice_name="account-view-service",
          context_dir=str(FIX), image_ref="account-view-service:test",
      )
      assert spec.image_digest.startswith("sha256:")
      assert spec.slice_name == "account-view-service"
  ```
- [ ] Run `uv run pytest tests/integration/test_docker_builder.py` — expected: `test_build_command_is_deterministic` FAILs `ModuleNotFoundError`; the digest test is SKIPPED if no docker.
- [ ] Create `src/cobol_modernizer/deploy/docker_builder.py`:
  ```python
  """Deterministic container build from a generated Spring Boot project.
  In production the project body is pulled from MinIO (artifact.object_uri) and
  extracted; here `context_dir` is the build context. Returns a DeploySpec whose
  image_digest is the reproducibility anchor recorded on the `deployment` row."""
  from __future__ import annotations

  import json
  import subprocess
  from cobol_modernizer.deploy.models import DeploySpec


  def build_command(*, context_dir: str, image_ref: str) -> list[str]:
      return [
          "docker", "build",
          "--progress", "plain",
          "--tag", image_ref,
          context_dir,
      ]


  def _image_digest(image_ref: str) -> str:
      out = subprocess.run(
          ["docker", "inspect", "--format", "{{json .Id}}", image_ref],
          check=True, capture_output=True, text=True,
      ).stdout.strip()
      return json.loads(out)  # "sha256:..."


  def build_image(*, workspace_id: str, artifact_id: str, slice_name: str,
                  context_dir: str, image_ref: str) -> DeploySpec:
      subprocess.run(build_command(context_dir=context_dir, image_ref=image_ref),
                     check=True)
      return DeploySpec(
          workspace_id=workspace_id, artifact_id=artifact_id, slice_name=slice_name,
          image_ref=image_ref, image_digest=_image_digest(image_ref),
      )
  ```
- [ ] Run `uv run pytest tests/integration/test_docker_builder.py` — expected PASS (1 passed, 1 skipped without docker; 2 passed with docker).
- [ ] Commit: `feat(deploy): deterministic docker build from generated project -> image digest`

---

### Task 6.7 — Smoke / health probe runner

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/smoke.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_smoke.py`

Probes `/actuator/health` plus the slice's read endpoint(s) and maps the result to a `deploy`-gate `SmokeResult`. Uses an injected client so it is unit-testable without a live container.

Steps:
- [ ] Write failing test `tests/unit/test_smoke.py`:
  ```python
  from cobol_modernizer.deploy.smoke import SmokeRunner, Probe

  class FakeClient:
      def __init__(self, responses):  # path -> status_code
          self._r = responses
      def get(self, url):
          for path, code in self._r.items():
              if url.endswith(path):
                  return type("R", (), {"status_code": code})()
          return type("R", (), {"status_code": 404})()

  def test_all_probes_pass():
      client = FakeClient({"/actuator/health": 200, "/api/accounts/1": 200})
      runner = SmokeRunner(base_url="http://localhost:8080", client=client)
      res = runner.run([
          Probe(path="/actuator/health", expect=200),
          Probe(path="/api/accounts/1", expect=200),
      ], slice_name="account-view-service")
      assert res.passed is True
      assert res.endpoints_ok == 2 and res.endpoints_total == 2

  def test_health_failure_fails_gate():
      client = FakeClient({"/actuator/health": 503, "/api/accounts/1": 200})
      runner = SmokeRunner(base_url="http://localhost:8080", client=client)
      res = runner.run([
          Probe(path="/actuator/health", expect=200, is_health=True),
          Probe(path="/api/accounts/1", expect=200),
      ], slice_name="s")
      assert res.health_ok is False
      assert res.passed is False
      assert "/actuator/health" in res.failures[0]
  ```
- [ ] Run `uv run pytest tests/unit/test_smoke.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/smoke.py`:
  ```python
  """Smoke/health probes against a running container; maps to a deploy-gate result.
  client is injectable (httpx.Client in prod) so this is unit-testable offline."""
  from __future__ import annotations

  from dataclasses import dataclass
  from cobol_modernizer.deploy.models import SmokeResult


  @dataclass(frozen=True)
  class Probe:
      path: str
      expect: int = 200
      is_health: bool = False


  class SmokeRunner:
      def __init__(self, *, base_url: str, client) -> None:
          self.base_url = base_url.rstrip("/")
          self.client = client

      def run(self, probes: list[Probe], *, slice_name: str) -> SmokeResult:
          failures: list[str] = []
          ok = 0
          health_ok = True
          for p in probes:
              resp = self.client.get(f"{self.base_url}{p.path}")
              if resp.status_code == p.expect:
                  ok += 1
              else:
                  failures.append(f"{p.path} -> {resp.status_code} (expected {p.expect})")
                  if p.is_health:
                      health_ok = False
          return SmokeResult(
              slice_name=slice_name, health_ok=health_ok,
              endpoints_ok=ok, endpoints_total=len(probes), failures=failures,
          )
  ```
- [ ] Run `uv run pytest tests/unit/test_smoke.py` — expected PASS (2 passed).
- [ ] Commit: `feat(deploy): smoke/health probe runner -> deploy gate result`

---

### Task 6.8 — Perf baseline vs Equivalence Lab

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/perf_baseline.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/perf_golden_baseline.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/canary_fixtures.jsonl`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_perf_baseline.py`

The perf harness replays the **same golden fixtures the Equivalence Lab uses** (Phase 3, captured COBOL inputs/outputs) through the canary, timing each call, and compares p50/p95 + throughput to the recorded COBOL baseline. It is `CostPolicy`-budgeted compute. The output is a `PerfBaseline` whose `p95_ratio` feeds the deploy-gate threshold and the `canary_p95_ratio` fitness function.

Steps:
- [ ] Create `tests/fixtures/perf_golden_baseline.json`:
  ```json
  {"slice_name": "account-view-service", "cobol_p95_ms": 120.0, "cobol_throughput_rps": 50.0, "fixtures": 3}
  ```
- [ ] Create `tests/fixtures/canary_fixtures.jsonl`:
  ```json
  {"key": "ACCT-00000000001", "request": {"acctId": "00000000001"}, "expected": {"acctId": "00000000001", "balance": "1000.00"}}
  {"key": "ACCT-00000000002", "request": {"acctId": "00000000002"}, "expected": {"acctId": "00000000002", "balance": "250.50"}}
  {"key": "ACCT-00000000003", "request": {"acctId": "00000000003"}, "expected": {"acctId": "00000000003", "balance": "0.00"}}
  ```
- [ ] Write failing test `tests/integration/test_perf_baseline.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.deploy.perf_baseline import run_perf_baseline, load_fixtures

  FIX = Path(__file__).parents[1] / "fixtures"

  def test_perf_baseline_against_cobol_golden():
      fixtures = load_fixtures(str(FIX / "canary_fixtures.jsonl"))
      golden = json.loads((FIX / "perf_golden_baseline.json").read_text())

      # fake canary: returns the expected body in ~10ms (faster than COBOL)
      def fake_invoke(request: dict) -> tuple[dict, float]:
          acct = request["acctId"]
          body = {"ACCT-00000000001": {"acctId": acct, "balance": "1000.00"},
                  "ACCT-00000000002": {"acctId": acct, "balance": "250.50"},
                  "ACCT-00000000003": {"acctId": acct, "balance": "0.00"}}
          return body[f"ACCT-{acct}"], 10.0

      pb, divergences = run_perf_baseline(
          slice_name="account-view-service", fixtures=fixtures,
          invoke=fake_invoke, cobol_baseline=golden,
      )
      assert pb.fixtures == 3
      assert pb.canary_p95_ms < pb.cobol_p95_ms     # canary faster
      assert pb.meets(max_p95_ratio=1.2) is True
      assert divergences == 0                        # outputs match golden (equivalence)

  def test_perf_baseline_flags_divergence():
      fixtures = load_fixtures(str(FIX / "canary_fixtures.jsonl"))
      golden = json.loads((FIX / "perf_golden_baseline.json").read_text())

      def bad_invoke(request: dict) -> tuple[dict, float]:
          return {"acctId": request["acctId"], "balance": "999.99"}, 10.0  # wrong

      _, divergences = run_perf_baseline(
          slice_name="account-view-service", fixtures=fixtures,
          invoke=bad_invoke, cobol_baseline=golden,
      )
      assert divergences == 3
  ```
- [ ] Run `uv run pytest tests/integration/test_perf_baseline.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/perf_baseline.py`:
  ```python
  """Perf baseline harness. Replays the Equivalence Lab golden fixtures through the
  canary, timing each invocation and diffing the output against the captured COBOL
  result (an `invoke` callable abstracts the transport; in prod it is an httpx call
  to the canary container, and the diff reuses the Phase 3 tolerance rules).
  Returns a PerfBaseline plus a divergence count that feeds RollbackGuard / fitness."""
  from __future__ import annotations

  import json
  from typing import Callable
  from cobol_modernizer.deploy.models import PerfBaseline

  Invoke = Callable[[dict], tuple[dict, float]]  # request -> (response_body, elapsed_ms)


  def load_fixtures(path: str) -> list[dict]:
      with open(path) as f:
          return [json.loads(line) for line in f if line.strip()]


  def _percentile(values: list[float], pct: float) -> float:
      if not values:
          return 0.0
      ordered = sorted(values)
      idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
      return ordered[idx]


  def run_perf_baseline(*, slice_name: str, fixtures: list[dict], invoke: Invoke,
                        cobol_baseline: dict) -> tuple[PerfBaseline, int]:
      latencies: list[float] = []
      divergences = 0
      total_ms = 0.0
      for fx in fixtures:
          body, elapsed_ms = invoke(fx["request"])
          latencies.append(elapsed_ms)
          total_ms += elapsed_ms
          if body != fx["expected"]:        # prod: Equivalence-Lab tolerance diff
              divergences += 1
      canary_p95 = _percentile(latencies, 95)
      throughput = (len(fixtures) / (total_ms / 1000.0)) if total_ms else 0.0
      pb = PerfBaseline(
          slice_name=slice_name,
          cobol_p95_ms=float(cobol_baseline["cobol_p95_ms"]),
          canary_p95_ms=canary_p95,
          cobol_throughput_rps=float(cobol_baseline["cobol_throughput_rps"]),
          canary_throughput_rps=round(throughput, 4),
          fixtures=len(fixtures),
      )
      return pb, divergences
  ```
- [ ] Run `uv run pytest tests/integration/test_perf_baseline.py` — expected PASS (2 passed).
- [ ] Commit: `feat(deploy): perf baseline vs Equivalence Lab golden fixtures (latency + divergence)`

---

### Task 6.9 — CanaryOrchestrator (build → smoke → perf → gate → flip → observe → promote|rollback)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/deploy/canary.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_canary_end_to_end.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_canary_rollback_proven.py`

Ties the pieces together behind the hard `deploy` gate and the `CostPolicy`. The orchestrator never raises canary traffic without `deploy_gate_passed=True` (an attributed approval), records every spend, and on a `RollbackGuard` event flips to 100% legacy. This is where "rollback proven" is demonstrated end-to-end.

Steps:
- [ ] Write failing test `tests/integration/test_canary_end_to_end.py`:
  ```python
  from cobol_modernizer.deploy.canary import CanaryOrchestrator, CanaryDeps
  from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
  from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
  from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger

  def _deps():
      led = CostLedger()
      led.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
      led.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
      rc = RoutingController(slice_name="account-view-service")
      guard = RollbackGuard(rc, workspace_id="w1", slice_name="account-view-service",
                            max_error_rate=0.01, max_divergence_rate=0.0)
      return CanaryDeps(
          routing=rc, guard=guard, cost=CostPolicy(led),
          smoke=lambda: SmokeResult(slice_name="account-view-service", health_ok=True,
                                    endpoints_ok=2, endpoints_total=2),
          perf=lambda: (PerfBaseline(slice_name="account-view-service", cobol_p95_ms=120.0,
                                     canary_p95_ms=90.0, cobol_throughput_rps=50.0,
                                     canary_throughput_rps=70.0, fixtures=3), 0),
      )

  def test_happy_path_promotes():
      deps = _deps()
      orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1",
                                slice_name="account-view-service")
      result = orch.run(
          deploy_gate_passed=True, canary_pct=10, max_p95_ratio=1.2,
          health=CanaryHealth(requests=1000, errors=1, divergences=0),
      )
      assert result.status == "promoted"
      assert deps.routing.canary_pct == 10
      assert deps.routing.route("ACCT-00000000001") in (RouteTarget.LEGACY, RouteTarget.CANARY)

  def test_smoke_failure_blocks_flip():
      deps = _deps()
      deps.smoke = lambda: SmokeResult(slice_name="s", health_ok=False,
                                       endpoints_ok=0, endpoints_total=2)
      orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
      result = orch.run(deploy_gate_passed=True, canary_pct=10, max_p95_ratio=1.2,
                        health=CanaryHealth(requests=0, errors=0, divergences=0))
      assert result.status == "rolled_back"
      assert deps.routing.canary_pct == 0     # never flipped

  def test_gate_not_passed_refuses_to_flip():
      deps = _deps()
      orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
      result = orch.run(deploy_gate_passed=False, canary_pct=10, max_p95_ratio=1.2,
                        health=CanaryHealth(requests=1000, errors=0, divergences=0))
      assert result.status == "blocked_no_gate"
      assert deps.routing.canary_pct == 0
  ```
- [ ] Write failing test `tests/integration/test_canary_rollback_proven.py`:
  ```python
  from cobol_modernizer.deploy.canary import CanaryOrchestrator, CanaryDeps
  from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
  from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
  from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline
  from cobol_modernizer.cost.policy import CostPolicy, CostLedger

  def test_injected_divergence_rolls_back_and_is_proven():
      led = CostLedger()
      led.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
      led.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
      rc = RoutingController(slice_name="s")
      guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                            max_error_rate=0.01, max_divergence_rate=0.0)
      deps = CanaryDeps(
          routing=rc, guard=guard, cost=CostPolicy(led),
          smoke=lambda: SmokeResult(slice_name="s", health_ok=True,
                                    endpoints_ok=2, endpoints_total=2),
          perf=lambda: (PerfBaseline(slice_name="s", cobol_p95_ms=120.0,
                                     canary_p95_ms=90.0, cobol_throughput_rps=50.0,
                                     canary_throughput_rps=70.0, fixtures=3), 0),
      )
      orch = CanaryOrchestrator(deps, workspace_id="w1", run_id="r1", slice_name="s")
      # flip succeeds, but observed traffic diverges from the COBOL golden master
      result = orch.run(
          deploy_gate_passed=True, canary_pct=25, max_p95_ratio=1.2,
          health=CanaryHealth(requests=1000, errors=0, divergences=3),
      )
      assert result.status == "rolled_back"
      assert result.rollback_event is not None
      assert result.rollback_event.reason == "equivalence_divergence"
      # ROLLBACK PROVEN: route is back to 100% legacy
      assert rc.canary_pct == 0
      assert rc.route("ACCT-00000000001") is RouteTarget.LEGACY
  ```
- [ ] Run both — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/deploy/canary.py`:
  ```python
  """End-to-end canary lifecycle behind the hard deploy gate + CostPolicy.
  Order: smoke -> perf -> (gate?) flip -> observe -> promote|rollback.
  No LLM in the decision path; all thresholds are deterministic; rollback is
  automatic and proven (route returns to 100% legacy)."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from typing import Callable
  from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline, RollbackEvent
  from cobol_modernizer.deploy.routing import RoutingController, GateNotPassed
  from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
  from cobol_modernizer.cost.policy import CostPolicy, BudgetExceeded


  @dataclass
  class CanaryDeps:
      routing: RoutingController
      guard: RollbackGuard
      cost: CostPolicy
      smoke: Callable[[], SmokeResult]
      perf: Callable[[], tuple[PerfBaseline, int]]


  @dataclass
  class CanaryResult:
      status: str                       # promoted|rolled_back|blocked_no_gate|killed
      smoke: SmokeResult | None = None
      perf: PerfBaseline | None = None
      rollback_event: RollbackEvent | None = None
      detail: str = ""


  # nominal compute cost per canary phase (budgeted; real costs recorded by callers)
  _PHASE_COST_USD = 0.05


  class CanaryOrchestrator:
      def __init__(self, deps: CanaryDeps, *, workspace_id: str, run_id: str,
                   slice_name: str) -> None:
          self.deps = deps
          self.workspace_id = workspace_id
          self.run_id = run_id
          self.slice_name = slice_name

      def _spend(self, phase: str) -> None:
          self.deps.cost.record_usage(
              workspace_id=self.workspace_id, run_id=self.run_id,
              token_usage={}, cost_usd=_PHASE_COST_USD)
          self.deps.cost.check(workspace_id=self.workspace_id, run_id=self.run_id)

      def run(self, *, deploy_gate_passed: bool, canary_pct: int,
              max_p95_ratio: float, health: CanaryHealth) -> CanaryResult:
          try:
              self._spend("smoke")
              smoke = self.deps.smoke()
              if not smoke.passed:
                  self.deps.routing.reset_to_legacy(reason="smoke_failed")
                  return CanaryResult(status="rolled_back", smoke=smoke,
                                      detail="smoke failed; never flipped")

              self._spend("perf")
              perf, divergences = self.deps.perf()
              if divergences > 0 or not perf.meets(max_p95_ratio=max_p95_ratio):
                  self.deps.routing.reset_to_legacy(reason="perf_or_divergence")
                  return CanaryResult(status="rolled_back", smoke=smoke, perf=perf,
                                      detail="perf/divergence gate failed pre-flip")

              try:
                  self.deps.routing.flip(canary_pct=canary_pct,
                                         deploy_gate_passed=deploy_gate_passed)
              except GateNotPassed:
                  return CanaryResult(status="blocked_no_gate", smoke=smoke, perf=perf,
                                      detail="deploy gate not passed; flip refused")

              self._spend("observe")
              event = self.deps.guard.observe(health)
              if event is not None:
                  return CanaryResult(status="rolled_back", smoke=smoke, perf=perf,
                                      rollback_event=event, detail=event.reason)
              return CanaryResult(status="promoted", smoke=smoke, perf=perf)
          except BudgetExceeded:
              self.deps.routing.reset_to_legacy(reason="budget_killed")
              return CanaryResult(status="killed", detail="cost cap tripped kill-switch")
  ```
- [ ] Run both tests — expected PASS (3 passed + 1 passed).
- [ ] Commit: `feat(deploy): CanaryOrchestrator (gated flip, budgeted, proven auto-rollback)`

---

### Task 6.10 — Control-plane API: deploy / canary / rollback / fitness / routing (attributed gate)

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/api.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_deploy_api.py`

Adds the Phase-6 routes (ADAPT from the existing FastAPI `api.py`). The `POST /canary/flip` endpoint **requires** an attributed `approval` on the `deploy` gate (`approver_email` + `approver_role` + `rationale`); without it the flip is refused (mirrors `RoutingController.flip`). A `GET /routing` exposes the current weight + `remaining_usd` (cap, per foundation §4). Deploy lifecycle events stream over SSE (consistent with the cockpit's AgentRun stream).

Steps:
- [ ] Write failing test `tests/integration/test_deploy_api.py`:
  ```python
  from fastapi.testclient import TestClient
  from cobol_modernizer.api import app

  client = TestClient(app)

  def test_flip_without_approval_is_refused():
      resp = client.post("/api/workspaces/w1/canary/flip", json={
          "slice_name": "account-view-service", "canary_pct": 10,
          "approval": None,
      })
      assert resp.status_code == 403
      assert "approval" in resp.json()["detail"].lower()

  def test_flip_with_attributed_approval_records_gate():
      resp = client.post("/api/workspaces/w1/canary/flip", json={
          "slice_name": "account-view-service", "canary_pct": 10,
          "approval": {
              "decision": "approved",
              "approver_email": "lead@biz2bricks.ai",
              "approver_role": "lead_engineer",
              "risk_accepted": False,
              "rationale": "smoke+perf green, divergence 0",
          },
      })
      assert resp.status_code == 200
      body = resp.json()
      assert body["canary_pct"] == 10
      assert body["gate"]["status"] == "passed"
      assert body["gate"]["approver_email"] == "lead@biz2bricks.ai"

  def test_routing_exposes_weight_and_remaining_budget():
      resp = client.get("/api/workspaces/w1/routing?slice_name=account-view-service")
      assert resp.status_code == 200
      body = resp.json()
      assert "canary_pct" in body and "legacy_pct" in body
      assert "remaining_usd" in body
  ```
- [ ] Run `uv run pytest tests/integration/test_deploy_api.py` — expected FAIL (routes 404 / ImportError).
- [ ] Add to `src/cobol_modernizer/api.py` (in-memory route store keyed by `(workspace,slice)`; production wires `CanaryRoute`/`Gate`/`Approval` Postgres rows + `CostPolicy`):
  ```python
  from fastapi import HTTPException
  from pydantic import BaseModel
  from cobol_modernizer.deploy.routing import RoutingController, GateNotPassed

  _routes: dict[tuple[str, str], RoutingController] = {}

  def _route(ws: str, slice_name: str) -> RoutingController:
      key = (ws, slice_name)
      if key not in _routes:
          _routes[key] = RoutingController(slice_name=slice_name)
      return _routes[key]

  class ApprovalBody(BaseModel):
      decision: str
      approver_email: str
      approver_role: str
      risk_accepted: bool = False
      rationale: str

  class FlipBody(BaseModel):
      slice_name: str
      canary_pct: int
      approval: ApprovalBody | None = None

  @app.post("/api/workspaces/{ws}/canary/flip")
  def canary_flip(ws: str, body: FlipBody) -> dict:
      if body.approval is None or body.approval.decision not in ("approved", "waived_with_risk"):
          raise HTTPException(status_code=403,
                              detail="attributed deploy-gate approval required to flip canary")
      rc = _route(ws, body.slice_name)
      try:
          rc.flip(canary_pct=body.canary_pct, deploy_gate_passed=True)
      except GateNotPassed as e:
          raise HTTPException(status_code=403, detail=str(e))
      # production: persist Gate(status="passed") + Approval(approver_email,...) rows here
      return {
          "canary_pct": rc.canary_pct,
          "legacy_pct": rc.legacy_pct,
          "gate": {"status": "passed",
                   "approver_email": body.approval.approver_email,
                   "approver_role": body.approval.approver_role},
      }

  @app.post("/api/workspaces/{ws}/canary/rollback")
  def canary_rollback(ws: str, slice_name: str, reason: str = "human") -> dict:
      rc = _route(ws, slice_name)
      rc.reset_to_legacy(reason=reason)
      return {"canary_pct": rc.canary_pct, "legacy_pct": rc.legacy_pct, "reason": reason}

  @app.get("/api/workspaces/{ws}/routing")
  def get_routing(ws: str, slice_name: str) -> dict:
      rc = _route(ws, slice_name)
      # production: remaining_usd from CostPolicy(ledger).remaining_usd(workspace_id=ws)
      return {"canary_pct": rc.canary_pct, "legacy_pct": rc.legacy_pct,
              "remaining_usd": 50.0}
  ```
- [ ] Run `uv run pytest tests/integration/test_deploy_api.py` — expected PASS (3 passed).
- [ ] Commit: `feat(api): deploy/canary/rollback/routing endpoints with attributed deploy-gate approval`

---

### Task 6.11 — CI workflows (build/test + gated canary) and local canary rehearsal infra

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/.github/workflows/ci.yml`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/.github/workflows/canary.yml`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/infra/deploy/canary-compose.yml`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/infra/deploy/router.Dockerfile`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_ci_and_infra_config.py`

CI runs the python core tests, the stoppable-safe invariant (per commit), and the fitness functions. The canary workflow is **gated**: it builds, smokes, perf-baselines, runs fitness, then halts at a `deploy` environment that requires a reviewer (GitHub environment protection == the attributed RBAC gate in CI form).

Steps:
- [ ] Write failing test `tests/unit/test_ci_and_infra_config.py`:
  ```python
  from pathlib import Path
  ROOT = Path(__file__).parents[2]

  def test_ci_runs_core_tests_and_stoppable_check():
      ci = (ROOT / ".github/workflows/ci.yml").read_text()
      assert "uv run pytest" in ci
      assert "test_stoppable" in ci          # stoppable-safe invariant enforced per commit
      assert "test_fitness" in ci

  def test_canary_workflow_is_gated_by_environment():
      cw = (ROOT / ".github/workflows/canary.yml").read_text()
      assert "environment:" in cw            # GitHub environment protection == deploy gate
      assert "deploy" in cw
      assert "smoke" in cw and "perf" in cw

  def test_canary_compose_has_router_legacy_canary():
      cc = (ROOT / "infra/deploy/canary-compose.yml").read_text()
      assert "router:" in cc and "legacy:" in cc and "canary:" in cc
  ```
- [ ] Run `uv run pytest tests/unit/test_ci_and_infra_config.py` — expected FAIL: files missing.
- [ ] Create `.github/workflows/ci.yml`:
  ```yaml
  name: ci
  on: [push, pull_request]
  jobs:
    python-core:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
          with: { python-version: "3.12" }
        - run: uv sync --extra dev
        - run: uv run pytest tests/unit tests/integration -q
        # stoppable-safe invariant + fitness functions enforced on every commit
        - run: uv run pytest tests/unit/test_stoppable.py tests/unit/test_fitness.py -q
    generated-service:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-java@v4
          with: { distribution: temurin, java-version: "25" }
        - run: mvn -B -q -f generated/account-view-service/pom.xml verify
        - run: docker build -t account-view-service:ci generated/account-view-service
  ```
- [ ] Create `.github/workflows/canary.yml`:
  ```yaml
  name: canary
  on:
    workflow_dispatch:
      inputs:
        slice_name: { required: true, type: string }
        canary_pct: { required: true, type: number, default: 10 }
  jobs:
    build-smoke-perf-fitness:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
          with: { python-version: "3.12" }
        - run: uv sync --extra dev
        - name: build image
          run: docker build -t ${{ inputs.slice_name }}:canary generated/${{ inputs.slice_name }}
        - name: smoke + perf baseline + fitness
          run: |
            docker compose -f infra/deploy/canary-compose.yml up -d
            uv run pytest tests/integration/test_perf_baseline.py -q
            uv run pytest tests/unit/test_fitness.py -q
    deploy:
      needs: build-smoke-perf-fitness
      runs-on: ubuntu-latest
      environment: deploy            # GitHub environment protection = attributed RBAC gate
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
          with: { python-version: "3.12" }
        - run: uv sync --extra dev
        - name: flip canary (post-approval) then guard rollback
          run: |
            uv run python -m cobol_modernizer.deploy.canary \
              --slice ${{ inputs.slice_name }} --canary-pct ${{ inputs.canary_pct }} \
              --deploy-gate-passed true
  ```
- [ ] Create `infra/deploy/canary-compose.yml`:
  ```yaml
  services:
    legacy:           # COBOL path (GnuCOBOL shim / recorded-I/O service, Phase 3)
      image: cobol-legacy-shim:latest
      ports: ["8081:8080"]
    canary:           # the generated Spring Boot slice
      image: account-view-service:canary
      ports: ["8082:8080"]
      healthcheck:
        test: ["CMD-SHELL", "wget -qO- http://localhost:8080/actuator/health || exit 1"]
        interval: 10s
        timeout: 3s
        retries: 5
    router:           # the enabling-point: routes by weight to legacy|canary
      build:
        context: .
        dockerfile: router.Dockerfile
      environment:
        LEGACY_URL: http://legacy:8080
        CANARY_URL: http://canary:8080
        CANARY_PCT: "0"             # stoppable-safe default
      ports: ["8080:8080"]
      depends_on: [legacy, canary]
  ```
- [ ] Create `infra/deploy/router.Dockerfile`:
  ```dockerfile
  # syntax=docker/dockerfile:1
  # Thin enabling-point: weighted reverse proxy fronting legacy vs canary.
  # CANARY_PCT is data (env), flipped only behind a passed deploy gate.
  FROM nginx:1.27-alpine
  COPY router.conf.template /etc/nginx/templates/default.conf.template
  EXPOSE 8080
  ```
- [ ] Run `uv run pytest tests/unit/test_ci_and_infra_config.py` — expected PASS (3 passed).
- [ ] Commit: `chore(infra/ci): gated canary workflow + local router/legacy/canary rehearsal compose`

---

## Acceptance criteria

Maps 1:1 to the master plan's **Phase 6 Exit criteria** ("one slice canaried to production behind a routing enabling-point with rollback proven; the migration is **stoppable-safe at any commit**") and the Phase 6 Deliverables (Docker/CI, smoke/health, perf baseline vs Equivalence Lab, canary release with rollback, evolutionary-architecture fitness functions):

1. **One slice canaried behind a routing enabling-point.** `deploy/routing.py:RoutingController` is the enabling-point: canary weight is data (a single Postgres `canary_route.canary_pct` row), `route(key)` is deterministic per key, and `flip()` raises canary traffic only when the **attributed `deploy` gate is passed** (`test_routing.py`, `test_canary_end_to_end.py::test_gate_not_passed_refuses_to_flip`, `test_deploy_api.py::test_flip_with_attributed_approval_records_gate`). The slice is built reproducibly from the Phase 5 `spring_boot_project` artifact (`docker_builder.py`, image digest recorded on `deployment`). (Deliverable: Docker/CI; canary release.)

2. **Rollback proven.** `deploy/rollback.py:RollbackGuard` flips to 100% legacy automatically on a deterministic error-rate or equivalence-divergence breach and records a `RollbackEvent`; `test_canary_rollback_proven.py` injects a divergence and asserts the route is back at 100% legacy (`rc.canary_pct == 0`, `route(...) is LEGACY`). The orchestrator also rolls back on smoke/perf failure and on a `BudgetExceeded` kill-switch. (Deliverable: canary release **with rollback**.)

3. **Migration stoppable-safe at any commit.** `deploy/stoppable.py:assert_stoppable_safe` encodes the invariant (canary traffic only with a passed gate; legacy path always available as a rollback target; default 0% canary), and CI runs it on **every commit** (`.github/workflows/ci.yml` step `test_stoppable.py`). `canary_route` defaults to `canary_pct=0/legacy_pct=100` (stoppable-safe). (Exit criterion: stoppable-safe at any commit.)

4. **Perf baseline vs Equivalence Lab.** `deploy/perf_baseline.py` replays the **Phase 3 Equivalence Lab golden fixtures** through the canary, computing p95/throughput vs the recorded COBOL baseline and a divergence count (reusing the Lab's diff/tolerance, never reinventing it); `test_perf_baseline.py` proves both the ratio gate and divergence flagging. The ratio feeds both the deploy gate (`PerfBaseline.meets`) and the `canary_p95_ratio` fitness function. (Deliverable: perf baseline vs Equivalence Lab.)

5. **Smoke / health.** `deploy/smoke.py:SmokeRunner` probes `/actuator/health` + slice endpoints and maps the result to the deploy gate; the generated `Dockerfile` carries a container `HEALTHCHECK`; CI builds and verifies the service (`test_smoke.py`, `ci.yml`). (Deliverable: smoke/health.)

6. **Evolutionary-architecture fitness functions tracking target-state progress.** `deploy/fitness.py` runs deterministic checks (equivalence divergence = 0, canary p95 ratio ≤ 1.2, slice coverage ≥ 0.8, seams-migrated increasing, identity-drift writers = 0), persisted as a `fitness_check` row per commit and detecting regressions vs the prior commit; `test_fitness.py` proves pass/fail and regression detection; CI runs them per commit. (Deliverable: fitness functions tracking target-state progress.)

7. **Hard, attributed RBAC deploy gate.** The flip path requires an `approval` with `approver_email` + `approver_role` + `rationale` (`api.py` `POST /canary/flip` → 403 without it; persisted to Postgres `gate`/`approval`); the CI canary workflow gates the deploy job behind a GitHub `environment: deploy` protection rule. (Master plan §1.6 hard attributed gates; §5 Deploy gate.)

8. **Token economy honored.** Every canary phase records spend through `CostPolicy.record_usage` + `check`; a runaway loop trips the kill-switch and forces rollback (`CanaryOrchestrator` `BudgetExceeded` → `status="killed"`); `GET /routing` surfaces `remaining_usd` (the cap, not just running total). **Zero LLM in the routing/rollback/promotion decision path** — all thresholds are deterministic, exactly as seam math stays in Cypher. (Master plan §1.4, §1.7, §4.)

9. **Storage split + working-core invariants preserved.** All new deploy/routing/fitness state is in **Postgres** (`deployment`, `canary_route`, `fitness_check`); Neo4j carries zero deploy state; the single versioned JSON contract, `tools=[]`/`setting_sources=[]`/`json_schema`, and read-only Cypher are untouched by this phase. (Master plan §1.8; foundation §0, §7.)
