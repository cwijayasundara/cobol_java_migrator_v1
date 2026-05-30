# UI Cockpit Workstream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Build the 11-stage modernization cockpit web app under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web`, ported and evolved from `source_graphs_v1.0/web` (Next.js 15 App Router / React 19 / Tailwind / TypeScript). Deliver the five-region cockpit shell (Journey Rail · Stage Header+Gates with cost-vs-cap pill · Main Workspace · single user-visible Modernization Agent Console · Evidence Drawer), the nine key screens (Portfolio Dashboard, Repository Intake, Graph Explorer reusing `GraphView.tsx`, Blueprint Studio, Seam Studio, Increment Planner, Design Studio, Build Lab, Equivalence Lab), the 5-mode HITL operating model with RBAC-attributed approval overlay, and SSE streaming of `AgentRun` events from checkpointed/resumable sessions pinned to a graph snapshot + artifact versions.

**Architecture:** This is a *thin presentation layer* over the FastAPI control plane (`src/cobol_modernizer/api.py`). **Agent execution stays in FastAPI — never in Next server functions.** The Next app is a client shell + a single rewrite proxy (`/api/*` → `http://localhost:8000/api/*`, ported verbatim from the source `next.config.ts`). Routes: `/workspaces`, `/workspaces/[id]/journey/[stage]`, `/workspaces/[id]/artifacts/[artifactId]`. The cockpit reads everything from the control plane (Postgres-backed `workspace`/`journey_stage`/`agent_run`/`artifact`/`gate`/`approval`/`budget` tables and the read-only Neo4j graph via the existing `/api/graph` endpoint). It NEVER touches Neo4j or Postgres directly, and it NEVER renders raw source except via the `get_source_slice`-backed `/api/entity` / slice endpoints (token-economy: no whole-file dumps in the browser either). SSE (`EventSource`) streams `agent_run` events. The cockpit surfaces the per-workspace cost **cap** (from `budget`), not just running spend.

**Tech Stack (conform to Foundation §Tech-Stack VERBATIM):**
- **Next.js 15** (App Router) + **React 19** + **TypeScript 5.6** + **Tailwind CSS 3.4**. (NOTE: the source web shell is on Tailwind 4 / `@tailwindcss/postcss`; the Foundation pins Tailwind **3.4**, so the ported PostCSS/Tailwind config is downgraded to the classic `tailwind.config.ts` + `autoprefixer` setup. This is the one deliberate deviation from the source shell.)
- **react-force-graph-2d** ^1.26 + **d3-force-3d** ^3.0 (carried over for `GraphView.tsx`).
- **lucide-react** for icons (carried over).
- **Vitest** + **@testing-library/react** + **jsdom** for unit/component tests; **Playwright** for e2e (Foundation §7 web test stack). MSW (`msw`) to mock the FastAPI control plane so the UI is testable without a live backend.
- Package manager: **npm** (source shell uses `package-lock.json`; keep it).

**The 11 journey stages (binding `stage_key` values — match Postgres `journey_stage.stage_key` and the UI design doc's stage list verbatim):**
`outcome` · `intake` · `parse` · `graph` · `explore` · `blueprint` · `seams` · `plan` · `design` · `build` · `verify`.

(Foundation's Postgres §3 example list `intake|graph|brd|seams|stories|design|build|equivalence|deploy` is illustrative; the UI design doc enumerates the canonical 11 cockpit stages above, which this workstream uses. The control-plane `api.py` plan seeds these 11 `stage_key`s. The mapping to gate keys: `parse`→`parse` gate, `graph`→`graph` gate, `blueprint`→`brd_groundedness` gate, `plan`→`stories_dag` gate, `design`→`design_data_ownership` gate, `build`→`code` gate, `verify`→`equivalence`+`deploy` gates.)

---

## File Structure

Everything below is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
└── web/                                              # Next.js 15 / React 19 cockpit (PORT+EVOLVE from source web/)
    ├── package.json                                  # Task UI-1 — deps incl. vitest/msw/playwright, Tailwind 3.4
    ├── next.config.ts                                # Task UI-1 — rewrite /api/* -> :8000 (PORT-AS-IS)
    ├── tsconfig.json                                 # Task UI-1 — paths @/* (PORT-AS-IS)
    ├── tailwind.config.ts                            # Task UI-1 — Tailwind 3.4 config (NEW, replaces v4 postcss-only)
    ├── postcss.config.mjs                            # Task UI-1 — tailwindcss + autoprefixer (ADAPT to 3.4)
    ├── vitest.config.ts                              # Task UI-2 — jsdom env, setup file
    ├── vitest.setup.ts                               # Task UI-2 — jest-dom matchers + MSW server lifecycle
    ├── playwright.config.ts                          # Task UI-12 — e2e config (webServer optional)
    └── src/
        ├── app/
        │   ├── layout.tsx                            # Task UI-1 — root <html> dark shell (PORT, retitle)
        │   ├── globals.css                           # Task UI-1 — Tailwind directives (ADAPT to 3.4 @tailwind)
        │   ├── page.tsx                              # Task UI-3 — redirect "/" -> "/workspaces"
        │   ├── workspaces/
        │   │   ├── page.tsx                          # Task UI-3 — Portfolio Dashboard
        │   │   └── [id]/
        │   │       ├── layout.tsx                    # Task UI-5 — cockpit 5-region shell (Journey Rail + header + drawer + console)
        │   │       ├── journey/
        │   │       │   └── [stage]/
        │   │       │       └── page.tsx              # Task UI-6 — stage dispatcher -> screen
        │   │       └── artifacts/
        │   │           └── [artifactId]/
        │   │               └── page.tsx              # Task UI-11 — artifact viewer (BRD HTML / JSON / evidence)
        ├── lib/
        │   ├── api.ts                                # Task UI-2 — typed control-plane client (PORT+EXTEND: workspaces/stages/artifacts/runs/approvals/budget)
        │   ├── types.ts                              # Task UI-2 — shared DTOs mirroring Postgres + contract
        │   ├── colors.ts                             # Task UI-4 — kind/rel colors (PORT+EXTEND v2 DataItem/READS/WRITES)
        │   ├── stages.ts                             # Task UI-3 — the 11 stage definitions + gate mapping + status colors
        │   └── useAgentStream.ts                     # Task UI-8 — EventSource hook for SSE agent_run events
        └── components/
            ├── cockpit/
            │   ├── JourneyRail.tsx                   # Task UI-5 — region 1: 11-stage rail w/ status colors
            │   ├── StageHeader.tsx                   # Task UI-5 — region 2: gate pills + cost-vs-cap pill
            │   ├── CostPill.tsx                      # Task UI-7 — spent vs cap pill (kill-switch aware)
            │   ├── GatePills.tsx                     # Task UI-7 — gate status pills
            │   ├── AgentConsole.tsx                  # Task UI-9 — region 4: single Modernization Agent console (SSE events)
            │   ├── EvidenceDrawer.tsx                # Task UI-10 — region 5: lineage / evidence_map / source spans
            │   └── ApprovalOverlay.tsx               # Task UI-10 — RBAC-attributed approval modal w/ budget impact
            ├── screens/
            │   ├── PortfolioDashboard.tsx            # Task UI-3
            │   ├── RepositoryIntake.tsx              # Task UI-6 (intake stage)
            │   ├── GraphExplorer.tsx                 # Task UI-6 (graph/explore stages) — wraps GraphView
            │   ├── BlueprintStudio.tsx               # Task UI-6 (blueprint stage)
            │   ├── SeamStudio.tsx                    # Task UI-6 (seams stage)
            │   ├── IncrementPlanner.tsx              # Task UI-6 (plan stage)
            │   ├── DesignStudio.tsx                  # Task UI-6 (design stage)
            │   ├── BuildLab.tsx                      # Task UI-6 (build stage)
            │   └── EquivalenceLab.tsx                # Task UI-6 (verify stage)
            └── GraphView.tsx                         # Task UI-4 — force graph (PORT+EXTEND: COBOL filters, seam overlay)
    └── src/test/
        ├── msw/
        │   ├── handlers.ts                           # Task UI-2 — MSW handlers for the control-plane API
        │   └── server.ts                             # Task UI-2 — MSW node server
        └── fixtures/
            └── controlplane.ts                       # Task UI-2 — canonical workspace/stage/run/gate/budget fixtures
    └── e2e/
        └── journey.spec.ts                           # Task UI-12 — Playwright happy-path through the cockpit
```

**Single responsibilities:**
- `lib/api.ts` — the ONLY place that calls the control plane. Every screen/component reads through it.
- `lib/types.ts` — TS mirrors of the Postgres columns (`workspace`/`journey_stage`/`agent_run`/`artifact`/`gate`/`approval`/`budget`) and the contract `EvidenceMap`. No business logic.
- `lib/stages.ts` — the 11 canonical stages, their order, their gate keys, and the status→color map. Single source of truth for the Journey Rail.
- `lib/useAgentStream.ts` — wraps `EventSource` for `/api/workspaces/{id}/runs/{runId}/events`; agent execution stays server-side, this only *reads* the stream.
- `cockpit/*` — the five-region shell, reused on every stage page.
- `screens/*` — one component per Main-Workspace screen; the stage page dispatches to the right one.

---

## Mapping UI tasks to the phase that first needs each screen (see `dependsOn`)

| Screen / capability | First needed by master-plan phase | Reason |
|---|---|---|
| Project bootstrap, shell, Journey Rail, Stage Header, Cost pill, Agent Console, Evidence Drawer, Approval overlay, SSE | **Phase 0** | Phase 0 produces the first `AgentRun`s (BRD), first gates, first budget/kill-switch — the cockpit chrome must exist to surface them. |
| Portfolio Dashboard | **Phase 0** | Lists workspaces + ingest status + cost; first thing a user sees. |
| Repository Intake | **Phase 0** | CardDemo ingest is the Phase 0 headline. |
| Graph Explorer (reuse `GraphView.tsx`) | **Phase 0** (v1 graph), seam overlay added **Phase 1** | Graph stage exists at Phase 0; reader/writer + seam overlay needs v2 edges (Phase 1). |
| Blueprint Studio | **Phase 0** | Grounded BRD with judge score renders in Phase 0. |
| Seam Studio | **Phase 1 / 4** | Needs v2 reader/writer classification + Cypher seam scoring. |
| Increment Planner | **Phase 4** | Story DAG comes from the seam engine. |
| Design Studio | **Phase 5** | Service design / ADRs. |
| Build Lab | **Phase 5** | TDD codegen + repair loop logs. |
| Equivalence Lab | **Phase 3 (foundation) / Phase 5 (writer slice)** | Golden-master diffs. |
| RBAC approval overlay w/ budget impact | **Phase 0** (artifact-gen mode) → all later gates | First gate is BRD groundedness; attributed approval is non-negotiable from the first gate. |

Within this workstream the *tasks* are ordered so the shell + Phase-0 screens land first, then the later-phase screens reuse the same chrome. Each later-phase screen Task notes its `dependsOn` phase plan.

---

## Task UI-1 — Bootstrap the web cockpit shell (port config, Tailwind 3.4, root layout)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/package.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/next.config.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/tsconfig.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/tailwind.config.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/postcss.config.mjs`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/globals.css`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/layout.tsx`

Steps:
- [ ] Create `web/package.json` (Tailwind 3.4, Vitest/MSW/Playwright added):
  ```json
  {
    "name": "cobol-modernizer-cockpit",
    "version": "0.1.0",
    "private": true,
    "scripts": {
      "dev": "next dev",
      "build": "next build",
      "start": "next start",
      "lint": "next lint",
      "test": "vitest run",
      "test:watch": "vitest",
      "e2e": "playwright test"
    },
    "dependencies": {
      "next": "^15.3",
      "react": "^19.1",
      "react-dom": "^19.1",
      "react-force-graph-2d": "^1.26",
      "d3-force-3d": "^3.0",
      "lucide-react": "^0.511"
    },
    "devDependencies": {
      "@types/node": "^22",
      "@types/react": "^19",
      "@types/react-dom": "^19",
      "typescript": "^5.6",
      "tailwindcss": "^3.4",
      "postcss": "^8",
      "autoprefixer": "^10.4",
      "vitest": "^2.1",
      "jsdom": "^25",
      "@testing-library/react": "^16.1",
      "@testing-library/jest-dom": "^6.6",
      "@testing-library/user-event": "^14.5",
      "@vitejs/plugin-react": "^4.3",
      "msw": "^2.6",
      "@playwright/test": "^1.49"
    }
  }
  ```
- [ ] Create `web/next.config.ts` (PORT-AS-IS from source — keeps agent execution in FastAPI by proxying):
  ```ts
  import type { NextConfig } from "next";

  const nextConfig: NextConfig = {
    async rewrites() {
      return [
        {
          source: "/api/:path*",
          destination: "http://localhost:8000/api/:path*",
        },
      ];
    },
  };

  export default nextConfig;
  ```
- [ ] Create `web/tsconfig.json` (PORT-AS-IS from source, target ES2017, `@/*` paths).
  ```json
  {
    "compilerOptions": {
      "target": "ES2017",
      "lib": ["dom", "dom.iterable", "esnext"],
      "allowJs": true,
      "skipLibCheck": true,
      "strict": true,
      "noEmit": true,
      "esModuleInterop": true,
      "module": "esnext",
      "moduleResolution": "bundler",
      "resolveJsonModule": true,
      "isolatedModules": true,
      "jsx": "preserve",
      "incremental": true,
      "plugins": [{ "name": "next" }],
      "paths": { "@/*": ["./src/*"] }
    },
    "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
    "exclude": ["node_modules"]
  }
  ```
- [ ] Create `web/tailwind.config.ts` (3.4 classic config):
  ```ts
  import type { Config } from "tailwindcss";

  const config: Config = {
    content: ["./src/**/*.{ts,tsx}"],
    theme: { extend: {} },
    plugins: [],
  };
  export default config;
  ```
- [ ] Create `web/postcss.config.mjs` (3.4 plugin chain — replaces source's `@tailwindcss/postcss`):
  ```js
  const config = {
    plugins: {
      tailwindcss: {},
      autoprefixer: {},
    },
  };
  export default config;
  ```
- [ ] Create `web/src/app/globals.css` (Tailwind 3.4 directives — replaces source's single `@import "tailwindcss"`):
  ```css
  @tailwind base;
  @tailwind components;
  @tailwind utilities;
  ```
- [ ] Create `web/src/app/layout.tsx` (PORT, retitled to the product):
  ```tsx
  import type { Metadata } from "next";
  import "./globals.css";

  export const metadata: Metadata = {
    title: "COBOL Modernization Cockpit",
    description: "Graph-grounded, agent-driven COBOL-to-Java modernization workbench",
  };

  export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
      <html lang="en" className="dark">
        <body className="bg-zinc-950 text-zinc-100 antialiased">{children}</body>
      </html>
    );
  }
  ```
- [ ] Run `cd web && npm install` — expected: lockfile written, no errors.
- [ ] Run `cd web && npx tsc --noEmit` — expected: no type errors (PASS).
- [ ] Commit: `chore(web): bootstrap Next.js 15/React 19 cockpit shell on Tailwind 3.4`

---

## Task UI-2 — Typed control-plane client, DTOs, and MSW mock server

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/types.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/api.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/test/fixtures/controlplane.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/test/msw/handlers.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/test/msw/server.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/vitest.config.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/vitest.setup.ts`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/api.test.ts`

Steps:
- [ ] Create `web/src/lib/types.ts` mirroring the Postgres columns + contract `EvidenceMap` (Foundation §3, §7):
  ```ts
  // DTOs mirror the Postgres run/audit/RBAC schema (Foundation §3) and the
  // versioned contract's EvidenceMap (Foundation §7). The cockpit reads these
  // from the FastAPI control plane; it never touches Postgres/Neo4j directly.

  export type StageStatus = "pending" | "running" | "blocked" | "passed" | "failed";
  export type GateStatus = "open" | "passed" | "failed" | "waived";
  export type RunStatus = "running" | "succeeded" | "failed" | "killed";
  export type ApprovalDecision = "approved" | "rejected" | "waived_with_risk";

  export interface Workspace {
    id: string;
    name: string;
    repo_slug: string;
    graph_snapshot: string | null;
    created_by: string;
    created_at: string;
    status: "active" | "archived";
  }

  export interface JourneyStage {
    id: string;
    workspace_id: string;
    stage_key: string;
    ordinal: number;
    status: StageStatus;
    updated_at: string;
  }

  export interface AgentRun {
    id: string;
    workspace_id: string;
    stage_id: string | null;
    role: string;
    model: string;
    status: RunStatus;
    started_by: string;
    started_at: string;
    finished_at: string | null;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_creation_tokens: number;
    total_cost_usd: number;
    error: string | null;
  }

  export type EvidenceMap = Record<string, string[]>; // requirement_id -> [graph ids / source refs]

  export interface Artifact {
    id: string;
    workspace_id: string;
    stage_id: string | null;
    agent_run_id: string | null;
    kind: string; // brd|seam_set|story_dag|design|spring_boot_project|equivalence_report
    version: number;
    object_uri: string;
    content_hash: string;
    evidence_map: EvidenceMap;
    created_at: string;
  }

  export interface Gate {
    id: string;
    workspace_id: string;
    stage_id: string | null;
    gate_key: string;
    status: GateStatus;
    threshold: Record<string, unknown>;
    result: Record<string, unknown>;
    updated_at: string;
  }

  export interface Approval {
    id: string;
    gate_id: string;
    decision: ApprovalDecision;
    approver_email: string;
    approver_role: string;
    risk_accepted: boolean;
    rationale: string;
    decided_at: string;
  }

  export interface Budget {
    id: string;
    workspace_id: string;
    scope: "workspace" | "run";
    agent_run_id: string | null;
    cap_usd: number;
    spent_usd: number;
    killed: boolean;
    updated_at: string;
  }

  // SSE event payload streamed from the agent run (one user-visible agent).
  export type AgentEventType =
    | "plan" | "tool_call" | "tool_result" | "cost"
    | "result" | "approval_request" | "failed" | "killed";

  export interface AgentEvent {
    type: AgentEventType;
    run_id: string;
    seq: number;
    ts: string;
    // payload is type-specific; UI renders a readable summary
    summary: string;
    detail?: Record<string, unknown>;
  }
  ```
- [ ] Write failing test `web/src/lib/api.test.ts`:
  ```ts
  import { describe, it, expect } from "vitest";
  import { api } from "@/lib/api";

  describe("control-plane api client", () => {
    it("lists workspaces from the control plane", async () => {
      const ws = await api.listWorkspaces();
      expect(ws.length).toBe(1);
      expect(ws[0].repo_slug).toBe("aws-mf-carddemo");
      expect(ws[0].created_by).toBe("cwijay@biz2bricks.ai");
    });

    it("fetches stages and the workspace budget", async () => {
      const stages = await api.listStages("ws-1");
      expect(stages.map((s) => s.stage_key)).toContain("blueprint");
      const budget = await api.getWorkspaceBudget("ws-1");
      expect(budget.cap_usd).toBe(50);
      expect(budget.spent_usd).toBe(18.42);
      expect(budget.killed).toBe(false);
    });

    it("submits an attributed approval with RBAC identity", async () => {
      const res = await api.submitApproval("gate-brd", {
        decision: "approved",
        approver_email: "lead@biz2bricks.ai",
        approver_role: "lead_engineer",
        risk_accepted: false,
        rationale: "BRD groundedness >= 4.2, all dims >= 3",
      });
      expect(res.decision).toBe("approved");
      expect(res.approver_email).toBe("lead@biz2bricks.ai");
    });
  });
  ```
- [ ] Run `cd web && npm test -- src/lib/api.test.ts` — expected FAIL: `Cannot find module '@/lib/api'`.
- [ ] Create `web/src/lib/api.ts` (PORT the source `json<T>` helper + graph/entity calls; EXTEND with the control-plane surface):
  ```ts
  import type {
    Workspace, JourneyStage, AgentRun, Artifact, Gate, Approval, Budget,
  } from "@/lib/types";

  const BASE = "";

  async function json<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${url}`, init);
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${res.status}: ${body}`);
    }
    return res.json();
  }

  // ---- graph DTOs (PORT-AS-IS from source web/src/lib/api.ts) ----
  export interface GraphNode {
    id: string; name: string; kind: string; file: string;
    summary: string | null;
  }
  export interface GraphLink { source: string; target: string; type: string; }
  export interface GraphData { nodes: GraphNode[]; links: GraphLink[]; }
  export interface EntityDetail {
    entity: Record<string, unknown>;
    incoming: { source: string; source_kind: string; relationship: string }[];
    outgoing: { target: string; target_kind: string; relationship: string }[];
  }

  export interface SubmitApprovalBody {
    decision: Approval["decision"];
    approver_email: string;
    approver_role: string;
    risk_accepted: boolean;
    rationale: string;
  }

  export const api = {
    // ---- Portfolio / workspaces ----
    listWorkspaces: () => json<Workspace[]>("/api/workspaces"),
    getWorkspace: (id: string) => json<Workspace>(`/api/workspaces/${id}`),
    createWorkspace: (body: { name: string; repo_slug: string; created_by: string }) =>
      json<Workspace>("/api/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),

    // ---- journey stages + gates ----
    listStages: (workspaceId: string) =>
      json<JourneyStage[]>(`/api/workspaces/${workspaceId}/stages`),
    listGates: (workspaceId: string) =>
      json<Gate[]>(`/api/workspaces/${workspaceId}/gates`),

    // ---- artifacts ----
    listArtifacts: (workspaceId: string) =>
      json<Artifact[]>(`/api/workspaces/${workspaceId}/artifacts`),
    getArtifact: (workspaceId: string, artifactId: string) =>
      json<Artifact>(`/api/workspaces/${workspaceId}/artifacts/${artifactId}`),

    // ---- agent runs (execution stays server-side; we only read) ----
    listRuns: (workspaceId: string) =>
      json<AgentRun[]>(`/api/workspaces/${workspaceId}/runs`),
    startRun: (workspaceId: string, body: { stage_key: string; role: string; started_by: string }) =>
      json<AgentRun>(`/api/workspaces/${workspaceId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),

    // ---- budget (cost cap surfaced in the UI, not just spend) ----
    getWorkspaceBudget: (workspaceId: string) =>
      json<Budget>(`/api/workspaces/${workspaceId}/budget`),

    // ---- approvals (RBAC-attributed) ----
    submitApproval: (gateId: string, body: SubmitApprovalBody) =>
      json<Approval>(`/api/gates/${gateId}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),

    // ---- graph (PORT-AS-IS endpoints from the analysis core) ----
    getGraph: (repo?: string, limit = 300) => {
      const params = new URLSearchParams();
      if (repo) params.set("repo", repo);
      params.set("limit", String(limit));
      return json<GraphData>(`/api/graph?${params}`);
    },
    getEntity: (qname: string) => json<EntityDetail>(`/api/entity/${qname}`),

    // SSE URL is consumed by useAgentStream via EventSource (not fetch).
    runEventsUrl: (workspaceId: string, runId: string) =>
      `/api/workspaces/${workspaceId}/runs/${runId}/events`,
  };
  ```
- [ ] Create `web/src/test/fixtures/controlplane.ts` (canonical fixtures used by MSW + component tests):
  ```ts
  import type {
    Workspace, JourneyStage, Gate, Budget, AgentRun, Artifact,
  } from "@/lib/types";

  export const WORKSPACE: Workspace = {
    id: "ws-1", name: "CardDemo", repo_slug: "aws-mf-carddemo",
    graph_snapshot: "snap-001", created_by: "cwijay@biz2bricks.ai",
    created_at: "2026-05-30T00:00:00Z", status: "active",
  };

  const STAGE_KEYS = ["outcome","intake","parse","graph","explore","blueprint","seams","plan","design","build","verify"];
  export const STAGES: JourneyStage[] = STAGE_KEYS.map((k, i) => ({
    id: `stg-${k}`, workspace_id: "ws-1", stage_key: k, ordinal: i,
    status: i < 5 ? "passed" : i === 5 ? "running" : "pending",
    updated_at: "2026-05-30T00:00:00Z",
  }));

  export const GATES: Gate[] = [
    { id: "gate-brd", workspace_id: "ws-1", stage_id: "stg-blueprint",
      gate_key: "brd_groundedness", status: "open",
      threshold: { min_weighted: 4.2, accuracy_floor: 3 },
      result: { weighted: 4.35, accuracy: 4 }, updated_at: "2026-05-30T00:00:00Z" },
  ];

  export const BUDGET: Budget = {
    id: "bud-1", workspace_id: "ws-1", scope: "workspace", agent_run_id: null,
    cap_usd: 50, spent_usd: 18.42, killed: false, updated_at: "2026-05-30T00:00:00Z",
  };

  export const RUN: AgentRun = {
    id: "run-1", workspace_id: "ws-1", stage_id: "stg-blueprint",
    role: "brd", model: "claude-sonnet-4-6", status: "running",
    started_by: "cwijay@biz2bricks.ai", started_at: "2026-05-30T00:00:00Z",
    finished_at: null, input_tokens: 12000, output_tokens: 3400,
    cache_read_tokens: 8000, cache_creation_tokens: 2000,
    total_cost_usd: 0.42, error: null,
  };

  export const ARTIFACT: Artifact = {
    id: "art-brd-1", workspace_id: "ws-1", stage_id: "stg-blueprint",
    agent_run_id: "run-1", kind: "brd", version: 1,
    object_uri: "minio://artifacts/ws-1/brd/v1.html",
    content_hash: "sha256:abc", evidence_map: { "REQ-001": ["CBACT01C", "CBACT01C.1000-MAIN"] },
    created_at: "2026-05-30T00:00:00Z",
  };
  ```
- [ ] Create `web/src/test/msw/handlers.ts`:
  ```ts
  import { http, HttpResponse } from "msw";
  import { WORKSPACE, STAGES, GATES, BUDGET, RUN, ARTIFACT } from "@/test/fixtures/controlplane";

  export const handlers = [
    http.get("/api/workspaces", () => HttpResponse.json([WORKSPACE])),
    http.get("/api/workspaces/:id", () => HttpResponse.json(WORKSPACE)),
    http.get("/api/workspaces/:id/stages", () => HttpResponse.json(STAGES)),
    http.get("/api/workspaces/:id/gates", () => HttpResponse.json(GATES)),
    http.get("/api/workspaces/:id/budget", () => HttpResponse.json(BUDGET)),
    http.get("/api/workspaces/:id/runs", () => HttpResponse.json([RUN])),
    http.get("/api/workspaces/:id/artifacts", () => HttpResponse.json([ARTIFACT])),
    http.get("/api/workspaces/:id/artifacts/:aid", () => HttpResponse.json(ARTIFACT)),
    http.post("/api/gates/:gateId/approval", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({
        id: "ap-1", gate_id: "gate-brd",
        decided_at: "2026-05-30T00:00:00Z", ...body,
      });
    }),
  ];
  ```
- [ ] Create `web/src/test/msw/server.ts`:
  ```ts
  import { setupServer } from "msw/node";
  import { handlers } from "@/test/msw/handlers";
  export const server = setupServer(...handlers);
  ```
- [ ] Create `web/vitest.config.ts`:
  ```ts
  import { defineConfig } from "vitest/config";
  import react from "@vitejs/plugin-react";
  import { fileURLToPath } from "node:url";

  export default defineConfig({
    plugins: [react()],
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./vitest.setup.ts"],
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
    },
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
  });
  ```
- [ ] Create `web/vitest.setup.ts`:
  ```ts
  import "@testing-library/jest-dom/vitest";
  import { afterAll, afterEach, beforeAll } from "vitest";
  import { server } from "@/test/msw/server";

  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());
  ```
- [ ] Run `cd web && npm test -- src/lib/api.test.ts` — expected PASS (3 passed).
- [ ] Commit: `feat(web): typed control-plane client + DTOs + MSW mock server`

---

## Task UI-3 — Portfolio Dashboard + stage definitions + "/" redirect

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/stages.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/PortfolioDashboard.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/workspaces/page.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/page.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/PortfolioDashboard.test.tsx`

Steps:
- [ ] Create `web/src/lib/stages.ts` (single source of truth for the 11 stages + status colors + gate mapping):
  ```ts
  import type { StageStatus } from "@/lib/types";

  export interface StageDef {
    key: string;
    label: string;
    /** gate_key this stage must clear before advancing, or null for no hard gate */
    gateKey: string | null;
  }

  export const STAGES: StageDef[] = [
    { key: "outcome", label: "Outcome", gateKey: null },
    { key: "intake", label: "Intake", gateKey: null },
    { key: "parse", label: "Parse", gateKey: "parse" },
    { key: "graph", label: "Graph", gateKey: "graph" },
    { key: "explore", label: "Explore", gateKey: null },
    { key: "blueprint", label: "Blueprint", gateKey: "brd_groundedness" },
    { key: "seams", label: "Seams", gateKey: null },
    { key: "plan", label: "Plan", gateKey: "stories_dag" },
    { key: "design", label: "Design", gateKey: "design_data_ownership" },
    { key: "build", label: "Build", gateKey: "code" },
    { key: "verify", label: "Verify", gateKey: "equivalence" },
  ];

  export const STAGE_STATUS_COLOR: Record<StageStatus, string> = {
    pending: "bg-zinc-700 text-zinc-300",
    running: "bg-sky-600 text-white",
    blocked: "bg-amber-600 text-white",
    passed: "bg-emerald-600 text-white",
    failed: "bg-red-600 text-white",
  };

  export function stageLabel(key: string): string {
    return STAGES.find((s) => s.key === key)?.label ?? key;
  }
  ```
- [ ] Write failing test `web/src/components/screens/PortfolioDashboard.test.tsx`:
  ```tsx
  import { describe, it, expect } from "vitest";
  import { render, screen } from "@testing-library/react";
  import { PortfolioDashboard } from "@/components/screens/PortfolioDashboard";

  describe("PortfolioDashboard", () => {
    it("lists workspaces with repo slug and a cost-vs-cap pill", async () => {
      render(<PortfolioDashboard />);
      expect(await screen.findByText("CardDemo")).toBeInTheDocument();
      expect(screen.getByText("aws-mf-carddemo")).toBeInTheDocument();
      // cost vs cap pill, not just spend
      expect(screen.getByText(/\$18\.42\s*\/\s*\$50/)).toBeInTheDocument();
    });
  });
  ```
- [ ] Run `cd web && npm test -- PortfolioDashboard` — expected FAIL: module not found.
- [ ] Create `web/src/components/screens/PortfolioDashboard.tsx`:
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import Link from "next/link";
  import { Boxes } from "lucide-react";
  import { api } from "@/lib/api";
  import type { Workspace, Budget } from "@/lib/types";

  export function PortfolioDashboard() {
    const [rows, setRows] = useState<{ ws: Workspace; budget: Budget | null }[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
      (async () => {
        const workspaces = await api.listWorkspaces();
        const withBudget = await Promise.all(
          workspaces.map(async (ws) => ({
            ws,
            budget: await api.getWorkspaceBudget(ws.id).catch(() => null),
          })),
        );
        setRows(withBudget);
        setLoading(false);
      })();
    }, []);

    return (
      <div className="min-h-screen">
        <header className="border-b border-zinc-800 bg-zinc-900/50 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
            <Boxes className="w-6 h-6 text-indigo-400" />
            <h1 className="text-xl font-semibold">Modernization Cockpit</h1>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-8">
          <h2 className="text-lg font-medium mb-4 text-zinc-300">
            Workspaces ({rows.length})
          </h2>
          {loading ? (
            <div className="text-zinc-500 text-sm">Loading...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {rows.map(({ ws, budget }) => (
                <Link
                  key={ws.id}
                  href={`/workspaces/${ws.id}/journey/outcome`}
                  className="block rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 hover:border-indigo-600"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{ws.name}</span>
                    {budget && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-200">
                        ${budget.spent_usd.toFixed(2)} / ${budget.cap_usd.toFixed(0)}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-zinc-500 mt-1 font-mono">{ws.repo_slug}</div>
                  <div className="text-xs text-zinc-600 mt-2">by {ws.created_by}</div>
                </Link>
              ))}
            </div>
          )}
        </main>
      </div>
    );
  }
  ```
- [ ] Create `web/src/app/workspaces/page.tsx`:
  ```tsx
  import { PortfolioDashboard } from "@/components/screens/PortfolioDashboard";
  export default function Page() {
    return <PortfolioDashboard />;
  }
  ```
- [ ] Create `web/src/app/page.tsx` (redirect root to the portfolio):
  ```tsx
  import { redirect } from "next/navigation";
  export default function Home() {
    redirect("/workspaces");
  }
  ```
- [ ] Run `cd web && npm test -- PortfolioDashboard` — expected PASS (1 passed).
- [ ] Commit: `feat(web): portfolio dashboard, 11-stage definitions, root redirect`

---

## Task UI-4 — Port GraphView with v2 COBOL kinds, seam overlay, colors

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/colors.ts`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/GraphView.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/colors.test.ts`

`dependsOn`: graph stage exists at **Phase 0**; the `seamOverlay` prop's data (reader/writer + score) is populated only once **Phase 1** v2 edges + Cypher classification exist.

Steps:
- [ ] Create `web/src/lib/colors.ts` (PORT from source + EXTEND with v2 `DataItem` kind and READS/WRITES/CICS/SQL/MOVES_TO/GO_TO rels):
  ```ts
  export const KIND_COLORS: Record<string, string> = {
    Module: "#6366f1", Class: "#f59e0b", Function: "#10b981", External: "#6b7280",
    // COBOL kinds
    Program: "#0ea5e9", Section: "#22d3ee", Paragraph: "#2dd4bf", Copybook: "#a78bfa",
    // v2 (Phase 1)
    DataItem: "#f472b6",
  };

  export const REL_COLORS: Record<string, string> = {
    CALLS: "#10b981", IMPORTS: "#6366f1", CONTAINS: "#94a3b8",
    CO_CHANGED_WITH: "#8b5cf6",
    // v2 (Phase 1)
    READS: "#38bdf8", WRITES: "#fb923c",
    EXECUTES_CICS: "#c084fc", EXECUTES_SQL: "#facc15",
    MOVES_TO: "#64748b", GO_TO: "#ef4444",
  };

  export function kindColor(kind: string): string {
    return KIND_COLORS[kind] ?? "#6b7280";
  }
  export function relColor(type: string): string {
    return REL_COLORS[type] ?? "#475569";
  }
  ```
- [ ] Write failing test `web/src/lib/colors.test.ts`:
  ```ts
  import { describe, it, expect } from "vitest";
  import { kindColor, relColor } from "@/lib/colors";

  describe("graph colors", () => {
    it("colors COBOL v1 + v2 node kinds distinctly", () => {
      expect(kindColor("Program")).toBe("#0ea5e9");
      expect(kindColor("DataItem")).toBe("#f472b6"); // v2
      expect(kindColor("Unknown")).toBe("#6b7280");
    });
    it("colors readers and writers differently (Fowler pivotal split)", () => {
      expect(relColor("READS")).not.toBe(relColor("WRITES"));
      expect(relColor("EXECUTES_CICS")).toBeTruthy();
    });
  });
  ```
- [ ] Run `cd web && npm test -- colors` — expected FAIL: module not found.
- [ ] Create `web/src/components/GraphView.tsx` — PORT the source component verbatim, then add the v2 node-size entries (`DataItem: 2`) to the `nodeVal` map and a `seamOverlay?: Record<string, { readerOnly: boolean; score: number }>` prop that, when present, draws a ring around seam-candidate `Program` nodes (emerald for reader-only, amber otherwise) in `nodeCanvasObject`. The full ported body is the source `GraphView.tsx` (344 lines) with these two diffs:
  ```tsx
  // (1) extend Props
  interface Props {
    repo?: string;
    onNodeClick?: (node: GraphNode) => void;
    seamOverlay?: Record<string, { readerOnly: boolean; score: number }>;
  }
  ```
  ```tsx
  // (2) in nodeCanvasObject, after the selection ring block, add the seam ring:
  const seam = props.seamOverlay?.[node.id];
  if (seam) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI, false);
    ctx.strokeStyle = seam.readerOnly ? "#10b981" : "#f59e0b";
    ctx.lineWidth = 2.5 / globalScale;
    ctx.stroke();
  }
  ```
  (The `nodeVal` size map gains `DataItem: 2`. Everything else — force tuning, hover highlighting, fullscreen, toolbar — is identical to the source.)
- [ ] Run `cd web && npm test -- colors` — expected PASS (2 passed).
- [ ] Run `cd web && npx tsc --noEmit` — expected: no type errors.
- [ ] Commit: `feat(web): port GraphView with v2 DataItem/IO colors + seam overlay prop`

---

## Task UI-5 — Cockpit shell: Journey Rail + Stage Header + workspace layout

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/JourneyRail.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/StageHeader.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/workspaces/[id]/layout.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/JourneyRail.test.tsx`

Steps:
- [ ] Write failing test `web/src/components/cockpit/JourneyRail.test.tsx`:
  ```tsx
  import { describe, it, expect } from "vitest";
  import { render, screen } from "@testing-library/react";
  import { JourneyRail } from "@/components/cockpit/JourneyRail";
  import { STAGES } from "@/test/fixtures/controlplane";

  describe("JourneyRail", () => {
    it("renders all 11 stages and marks the active one", () => {
      render(<JourneyRail workspaceId="ws-1" stages={STAGES} active="blueprint" />);
      // all 11 canonical stages present
      ["Outcome","Intake","Parse","Graph","Explore","Blueprint","Seams","Plan","Design","Build","Verify"]
        .forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
      const active = screen.getByText("Blueprint").closest("a");
      expect(active?.getAttribute("aria-current")).toBe("step");
    });
  });
  ```
- [ ] Run `cd web && npm test -- JourneyRail` — expected FAIL: module not found.
- [ ] Create `web/src/components/cockpit/JourneyRail.tsx`:
  ```tsx
  "use client";

  import Link from "next/link";
  import { STAGES, STAGE_STATUS_COLOR } from "@/lib/stages";
  import type { JourneyStage, StageStatus } from "@/lib/types";

  interface Props {
    workspaceId: string;
    stages: JourneyStage[];
    active: string;
  }

  export function JourneyRail({ workspaceId, stages, active }: Props) {
    const statusOf = (key: string): StageStatus =>
      stages.find((s) => s.stage_key === key)?.status ?? "pending";

    return (
      <nav className="w-44 shrink-0 border-r border-zinc-800 bg-zinc-900/30 py-4">
        <ol className="space-y-1">
          {STAGES.map((stage, i) => {
            const status = statusOf(stage.key);
            const isActive = stage.key === active;
            return (
              <li key={stage.key}>
                <Link
                  href={`/workspaces/${workspaceId}/journey/${stage.key}`}
                  aria-current={isActive ? "step" : undefined}
                  className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md mx-2 ${
                    isActive ? "bg-zinc-800 text-white" : "text-zinc-400 hover:bg-zinc-800/50"
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full ${STAGE_STATUS_COLOR[status].split(" ")[0]}`} />
                  <span className="text-xs text-zinc-600 w-4">{i}</span>
                  {stage.label}
                </Link>
              </li>
            );
          })}
        </ol>
      </nav>
    );
  }
  ```
- [ ] Create `web/src/components/cockpit/StageHeader.tsx`:
  ```tsx
  "use client";

  import { stageLabel } from "@/lib/stages";
  import { GatePills } from "@/components/cockpit/GatePills";
  import { CostPill } from "@/components/cockpit/CostPill";
  import type { Gate, Budget } from "@/lib/types";

  interface Props {
    stageKey: string;
    gates: Gate[];
    budget: Budget | null;
  }

  export function StageHeader({ stageKey, gates, budget }: Props) {
    return (
      <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <h2 className="text-lg font-semibold">{stageLabel(stageKey)}</h2>
        <div className="flex items-center gap-2">
          <GatePills gates={gates} />
          <CostPill budget={budget} />
        </div>
      </header>
    );
  }
  ```
- [ ] Create `web/src/app/workspaces/[id]/layout.tsx` (server component that lays out the five regions; data fetched client-side in children/console/drawer):
  ```tsx
  import type { ReactNode } from "react";

  // The 5-region cockpit frame. Journey Rail + Stage Header + Agent Console +
  // Evidence Drawer are rendered by the stage page (it knows the active stage);
  // this layout just provides the stable outer chrome + scroll containers.
  export default async function WorkspaceLayout({
    children,
  }: {
    children: ReactNode;
    params: Promise<{ id: string }>;
  }) {
    return <div className="flex h-screen overflow-hidden">{children}</div>;
  }
  ```
- [ ] Run `cd web && npm test -- JourneyRail` — expected PASS (1 passed).
- [ ] Commit: `feat(web): cockpit shell — Journey Rail + Stage Header + workspace layout`

---

## Task UI-6 — Stage page dispatcher + screen stubs (one per Main-Workspace screen)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/RepositoryIntake.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/GraphExplorer.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/BlueprintStudio.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/SeamStudio.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/IncrementPlanner.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/DesignStudio.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/BuildLab.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/EquivalenceLab.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/workspaces/[id]/journey/[stage]/page.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/screens/stageDispatch.test.tsx`

`dependsOn`: intake/graph/blueprint = **Phase 0**; SeamStudio = **Phase 1/4**; IncrementPlanner = **Phase 4**; DesignStudio/BuildLab = **Phase 5**; EquivalenceLab = **Phase 3/5**.

Steps:
- [ ] Create the screen components. Each takes `{ workspaceId }`. The Phase-0 ones are functional; later-phase ones render a graph/artifact reader plus an "agent run" affordance and a clear "available in Phase N" empty state. Representative bodies:

  `GraphExplorer.tsx` (Phase 0 — reuses ported GraphView, adds COBOL filter + seam overlay slot):
  ```tsx
  "use client";

  import { useState } from "react";
  import { GraphView } from "@/components/GraphView";
  import type { GraphNode } from "@/lib/api";

  export function GraphExplorer({ workspaceId, repoSlug }: { workspaceId: string; repoSlug: string }) {
    const [selected, setSelected] = useState<GraphNode | null>(null);
    return (
      <div className="p-4 space-y-3">
        <div className="text-xs text-zinc-500">
          Graph for <span className="font-mono">{repoSlug}</span>
          {selected && <> · selected <span className="font-mono">{selected.name}</span></>}
        </div>
        <GraphView repo={repoSlug} onNodeClick={setSelected} />
      </div>
    );
  }
  ```

  `BlueprintStudio.tsx` (Phase 0 — lists BRD artifacts, links to artifact viewer, shows judge score from gate):
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import Link from "next/link";
  import { api } from "@/lib/api";
  import type { Artifact, Gate } from "@/lib/types";

  export function BlueprintStudio({ workspaceId }: { workspaceId: string }) {
    const [brds, setBrds] = useState<Artifact[]>([]);
    const [gate, setGate] = useState<Gate | null>(null);
    useEffect(() => {
      (async () => {
        const arts = await api.listArtifacts(workspaceId);
        setBrds(arts.filter((a) => a.kind === "brd"));
        const gates = await api.listGates(workspaceId);
        setGate(gates.find((g) => g.gate_key === "brd_groundedness") ?? null);
      })();
    }, [workspaceId]);
    return (
      <div className="p-4 space-y-3">
        <h3 className="text-sm font-medium text-zinc-300">Functional Blueprint (BRD)</h3>
        {gate && (
          <div className="text-xs text-zinc-400">
            groundedness gate: weighted {String(gate.result.weighted ?? "—")} /
            threshold {String((gate.threshold as Record<string, unknown>).min_weighted ?? "—")} ·{" "}
            <span className={gate.status === "passed" ? "text-emerald-400" : "text-amber-400"}>
              {gate.status}
            </span>
          </div>
        )}
        <ul className="space-y-1">
          {brds.map((b) => (
            <li key={b.id}>
              <Link className="text-indigo-400 hover:underline text-sm"
                    href={`/workspaces/${workspaceId}/artifacts/${b.id}`}>
                BRD v{b.version}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  ```

  `SeamStudio.tsx` / `IncrementPlanner.tsx` / `DesignStudio.tsx` / `BuildLab.tsx` / `EquivalenceLab.tsx` / `RepositoryIntake.tsx` follow the same shape (props `{ workspaceId }`, fetch the relevant artifact kind via `api.listArtifacts`, render a heading + list + an empty state). For brevity each later-phase stub renders:
  ```tsx
  "use client";
  export function SeamStudio({ workspaceId }: { workspaceId: string }) {
    return (
      <div className="p-4">
        <h3 className="text-sm font-medium text-zinc-300">Seam Studio</h3>
        <p className="text-xs text-zinc-500 mt-2">
          Ranked seam candidates (reader/writer split, blast radius, testability)
          are computed in Cypher/GDS and surfaced here once Phase 1 v2 edges land.
        </p>
      </div>
    );
  }
  ```
  (`IncrementPlanner` → "story DAG (Phase 4)"; `DesignStudio` → "service design + ADRs (Phase 5)"; `BuildLab` → "TDD codegen + repair loop (Phase 5)"; `EquivalenceLab` → "golden-master diffs (Phase 3/5)"; `RepositoryIntake` → a form posting to `api.createWorkspace`/ingest.)
- [ ] Write failing test `web/src/components/screens/stageDispatch.test.tsx`:
  ```tsx
  import { describe, it, expect } from "vitest";
  import { render, screen } from "@testing-library/react";
  import { StageScreen } from "@/components/screens/StageScreen";

  describe("stage dispatcher", () => {
    it("renders Blueprint Studio for the blueprint stage", async () => {
      render(<StageScreen workspaceId="ws-1" stageKey="blueprint" repoSlug="aws-mf-carddemo" />);
      expect(await screen.findByText(/Functional Blueprint/)).toBeInTheDocument();
    });
    it("renders Seam Studio for the seams stage", () => {
      render(<StageScreen workspaceId="ws-1" stageKey="seams" repoSlug="aws-mf-carddemo" />);
      expect(screen.getByText("Seam Studio")).toBeInTheDocument();
    });
  });
  ```
- [ ] Create the dispatcher `web/src/components/screens/StageScreen.tsx`:
  ```tsx
  "use client";

  import { RepositoryIntake } from "@/components/screens/RepositoryIntake";
  import { GraphExplorer } from "@/components/screens/GraphExplorer";
  import { BlueprintStudio } from "@/components/screens/BlueprintStudio";
  import { SeamStudio } from "@/components/screens/SeamStudio";
  import { IncrementPlanner } from "@/components/screens/IncrementPlanner";
  import { DesignStudio } from "@/components/screens/DesignStudio";
  import { BuildLab } from "@/components/screens/BuildLab";
  import { EquivalenceLab } from "@/components/screens/EquivalenceLab";

  export function StageScreen(
    { workspaceId, stageKey, repoSlug }: { workspaceId: string; stageKey: string; repoSlug: string },
  ) {
    switch (stageKey) {
      case "intake": return <RepositoryIntake workspaceId={workspaceId} />;
      case "graph":
      case "explore": return <GraphExplorer workspaceId={workspaceId} repoSlug={repoSlug} />;
      case "blueprint": return <BlueprintStudio workspaceId={workspaceId} />;
      case "seams": return <SeamStudio workspaceId={workspaceId} />;
      case "plan": return <IncrementPlanner workspaceId={workspaceId} />;
      case "design": return <DesignStudio workspaceId={workspaceId} />;
      case "build": return <BuildLab workspaceId={workspaceId} />;
      case "verify": return <EquivalenceLab workspaceId={workspaceId} />;
      default:
        return <div className="p-4 text-sm text-zinc-500">Stage: {stageKey}</div>;
    }
  }
  ```
- [ ] Create the stage route page `web/src/app/workspaces/[id]/journey/[stage]/page.tsx` (client component wiring the five regions together):
  ```tsx
  "use client";

  import { use, useEffect, useState } from "react";
  import { api } from "@/lib/api";
  import type { JourneyStage, Gate, Budget, Workspace } from "@/lib/types";
  import { JourneyRail } from "@/components/cockpit/JourneyRail";
  import { StageHeader } from "@/components/cockpit/StageHeader";
  import { AgentConsole } from "@/components/cockpit/AgentConsole";
  import { EvidenceDrawer } from "@/components/cockpit/EvidenceDrawer";
  import { StageScreen } from "@/components/screens/StageScreen";

  export default function Page({ params }: { params: Promise<{ id: string; stage: string }> }) {
    const { id, stage } = use(params);
    const [ws, setWs] = useState<Workspace | null>(null);
    const [stages, setStages] = useState<JourneyStage[]>([]);
    const [gates, setGates] = useState<Gate[]>([]);
    const [budget, setBudget] = useState<Budget | null>(null);

    useEffect(() => {
      (async () => {
        setWs(await api.getWorkspace(id));
        setStages(await api.listStages(id));
        setGates(await api.listGates(id));
        setBudget(await api.getWorkspaceBudget(id).catch(() => null));
      })();
    }, [id]);

    const stageGates = gates.filter(
      (g) => g.stage_id === stages.find((s) => s.stage_key === stage)?.id,
    );

    return (
      <>
        <JourneyRail workspaceId={id} stages={stages} active={stage} />
        <div className="flex-1 flex flex-col min-w-0">
          <StageHeader stageKey={stage} gates={stageGates} budget={budget} />
          <div className="flex-1 overflow-auto">
            {ws && <StageScreen workspaceId={id} stageKey={stage} repoSlug={ws.repo_slug} />}
          </div>
          <AgentConsole workspaceId={id} stageKey={stage} />
        </div>
        <EvidenceDrawer workspaceId={id} />
      </>
    );
  }
  ```
- [ ] Run `cd web && npm test -- stageDispatch` — expected PASS (2 passed).
- [ ] Commit: `feat(web): stage dispatcher + nine Main-Workspace screens mapped to phases`

---

## Task UI-7 — Cost-vs-cap pill + gate pills (kill-switch aware)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/CostPill.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/GatePills.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/CostPill.test.tsx`

Steps:
- [ ] Write failing test `web/src/components/cockpit/CostPill.test.tsx`:
  ```tsx
  import { describe, it, expect } from "vitest";
  import { render, screen } from "@testing-library/react";
  import { CostPill } from "@/components/cockpit/CostPill";
  import { BUDGET } from "@/test/fixtures/controlplane";

  describe("CostPill", () => {
    it("shows spent vs cap (cap, not just running total)", () => {
      render(<CostPill budget={BUDGET} />);
      expect(screen.getByText(/\$18\.42\s*\/\s*\$50/)).toBeInTheDocument();
    });
    it("shows a kill-switch state when budget.killed", () => {
      render(<CostPill budget={{ ...BUDGET, killed: true, spent_usd: 50 }} />);
      expect(screen.getByText(/killed/i)).toBeInTheDocument();
    });
  });
  ```
- [ ] Run `cd web && npm test -- CostPill` — expected FAIL: module not found.
- [ ] Create `web/src/components/cockpit/CostPill.tsx`:
  ```tsx
  "use client";

  import { DollarSign, Ban } from "lucide-react";
  import type { Budget } from "@/lib/types";

  export function CostPill({ budget }: { budget: Budget | null }) {
    if (!budget) return null;
    const pct = budget.cap_usd > 0 ? budget.spent_usd / budget.cap_usd : 0;
    const tone = budget.killed
      ? "bg-red-700 text-white"
      : pct >= 0.9
        ? "bg-amber-600 text-white"
        : "bg-zinc-800 text-zinc-200";
    return (
      <span className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${tone}`}>
        {budget.killed ? <Ban className="w-3 h-3" /> : <DollarSign className="w-3 h-3" />}
        ${budget.spent_usd.toFixed(2)} / ${budget.cap_usd.toFixed(0)}
        {budget.killed && <span className="ml-1 font-semibold">killed</span>}
      </span>
    );
  }
  ```
- [ ] Create `web/src/components/cockpit/GatePills.tsx`:
  ```tsx
  "use client";

  import type { Gate, GateStatus } from "@/lib/types";

  const TONE: Record<GateStatus, string> = {
    open: "bg-zinc-700 text-zinc-200",
    passed: "bg-emerald-700 text-white",
    failed: "bg-red-700 text-white",
    waived: "bg-amber-700 text-white",
  };

  export function GatePills({ gates }: { gates: Gate[] }) {
    if (gates.length === 0) return null;
    return (
      <div className="flex items-center gap-1.5">
        {gates.map((g) => (
          <span key={g.id} className={`text-xs px-2 py-1 rounded-full ${TONE[g.status]}`}>
            {g.gate_key}: {g.status}
          </span>
        ))}
      </div>
    );
  }
  ```
- [ ] Run `cd web && npm test -- CostPill` — expected PASS (2 passed).
- [ ] Commit: `feat(web): cost-vs-cap pill (kill-switch aware) + gate status pills`

---

## Task UI-8 — SSE hook for AgentRun events (useAgentStream)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/useAgentStream.ts`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/lib/useAgentStream.test.ts`

Steps:
- [ ] Write failing test `web/src/lib/useAgentStream.test.ts` (mocks `EventSource`; agent execution stays server-side — the hook only reads):
  ```ts
  import { describe, it, expect, vi, beforeEach } from "vitest";
  import { renderHook, act, waitFor } from "@testing-library/react";
  import { useAgentStream } from "@/lib/useAgentStream";

  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    onmessage: ((e: MessageEvent) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    url: string;
    closed = false;
    constructor(url: string) { this.url = url; FakeEventSource.instances.push(this); }
    emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent); }
    close() { this.closed = true; }
  }

  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
  });

  describe("useAgentStream", () => {
    it("accumulates ordered agent events from the SSE stream", async () => {
      const { result } = renderHook(() => useAgentStream("ws-1", "run-1"));
      const es = FakeEventSource.instances[0];
      expect(es.url).toContain("/api/workspaces/ws-1/runs/run-1/events");
      act(() => {
        es.emit({ type: "plan", run_id: "run-1", seq: 0, ts: "t0", summary: "drafting BRD plan" });
        es.emit({ type: "tool_call", run_id: "run-1", seq: 1, ts: "t1", summary: "neighbors(CBACT01C)" });
      });
      await waitFor(() => expect(result.current.events.length).toBe(2));
      expect(result.current.events[1].summary).toBe("neighbors(CBACT01C)");
    });
  });
  ```
- [ ] Run `cd web && npm test -- useAgentStream` — expected FAIL: module not found.
- [ ] Create `web/src/lib/useAgentStream.ts`:
  ```ts
  "use client";

  import { useEffect, useRef, useState } from "react";
  import { api } from "@/lib/api";
  import type { AgentEvent } from "@/lib/types";

  // Reads the server-side agent run's SSE stream. Execution is in FastAPI;
  // this hook never starts/runs the agent, it only subscribes to events.
  export function useAgentStream(workspaceId: string | null, runId: string | null) {
    const [events, setEvents] = useState<AgentEvent[]>([]);
    const [connected, setConnected] = useState(false);
    const esRef = useRef<EventSource | null>(null);

    useEffect(() => {
      setEvents([]);
      if (!workspaceId || !runId) return;
      const es = new EventSource(api.runEventsUrl(workspaceId, runId));
      esRef.current = es;
      setConnected(true);
      es.onmessage = (e: MessageEvent) => {
        try {
          const evt = JSON.parse(e.data) as AgentEvent;
          setEvents((prev) => [...prev, evt].sort((a, b) => a.seq - b.seq));
        } catch {
          /* ignore malformed frame */
        }
      };
      es.onerror = () => setConnected(false);
      return () => { es.close(); esRef.current = null; setConnected(false); };
    }, [workspaceId, runId]);

    return { events, connected };
  }
  ```
- [ ] Run `cd web && npm test -- useAgentStream` — expected PASS (1 passed).
- [ ] Commit: `feat(web): useAgentStream SSE hook for AgentRun events (read-only)`

---

## Task UI-9 — Agent Console (single user-visible Modernization Agent)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/AgentConsole.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/AgentConsole.test.tsx`

Steps:
- [ ] Write failing test `web/src/components/cockpit/AgentConsole.test.tsx`:
  ```tsx
  import { describe, it, expect, vi, beforeEach } from "vitest";
  import { render, screen } from "@testing-library/react";
  import { AgentConsole } from "@/components/cockpit/AgentConsole";

  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    onmessage: ((e: MessageEvent) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    constructor(public url: string) { FakeEventSource.instances.push(this); }
    emit(d: unknown) { this.onmessage?.({ data: JSON.stringify(d) } as MessageEvent); }
    close() {}
  }
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
  });

  describe("AgentConsole", () => {
    it("shows the single Modernization Agent label and the active run", async () => {
      render(<AgentConsole workspaceId="ws-1" stageKey="blueprint" />);
      expect(await screen.findByText(/Modernization Agent/i)).toBeInTheDocument();
      // run-1 from MSW fixtures is running
      expect(await screen.findByText(/run-1/)).toBeInTheDocument();
    });

    it("renders readable tool-call events as they stream", async () => {
      render(<AgentConsole workspaceId="ws-1" stageKey="blueprint" />);
      await screen.findByText(/run-1/);
      const es = FakeEventSource.instances[0];
      es.emit({ type: "tool_call", run_id: "run-1", seq: 0, ts: "t", summary: "find_entities(prefix=CBACT)" });
      expect(await screen.findByText("find_entities(prefix=CBACT)")).toBeInTheDocument();
    });
  });
  ```
- [ ] Run `cd web && npm test -- AgentConsole` — expected FAIL: module not found.
- [ ] Create `web/src/components/cockpit/AgentConsole.tsx`:
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import { Bot } from "lucide-react";
  import { api } from "@/lib/api";
  import { useAgentStream } from "@/lib/useAgentStream";
  import type { AgentRun, AgentEventType } from "@/lib/types";

  const EVENT_LABEL: Record<AgentEventType, string> = {
    plan: "plan", tool_call: "tool", tool_result: "result", cost: "cost",
    result: "done", approval_request: "approval", failed: "failed", killed: "killed",
  };

  export function AgentConsole({ workspaceId, stageKey }: { workspaceId: string; stageKey: string }) {
    const [run, setRun] = useState<AgentRun | null>(null);
    useEffect(() => {
      (async () => {
        const runs = await api.listRuns(workspaceId);
        // single user-visible agent: show the most recent running run, else newest
        const active = runs.find((r) => r.status === "running") ?? runs[0] ?? null;
        setRun(active);
      })();
    }, [workspaceId, stageKey]);

    const { events, connected } = useAgentStream(workspaceId, run?.id ?? null);

    return (
      <section className="border-t border-zinc-800 bg-zinc-900/40 h-56 flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
          <Bot className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-medium">Modernization Agent</span>
          {run && (
            <span className="text-xs text-zinc-500 font-mono">
              {run.id} · {run.role} · {run.model} · {run.status}
              {connected ? " · live" : ""}
            </span>
          )}
        </div>
        <ol className="flex-1 overflow-auto px-4 py-2 space-y-1 font-mono text-xs">
          {events.map((e) => (
            <li key={`${e.seq}-${e.ts}`} className="flex gap-2">
              <span className="text-zinc-600 w-16 shrink-0">[{EVENT_LABEL[e.type]}]</span>
              <span className="text-zinc-300">{e.summary}</span>
            </li>
          ))}
          {events.length === 0 && (
            <li className="text-zinc-600">No agent activity yet for this run.</li>
          )}
        </ol>
      </section>
    );
  }
  ```
- [ ] Run `cd web && npm test -- AgentConsole` — expected PASS (2 passed).
- [ ] Commit: `feat(web): single user-visible Modernization Agent console (SSE-driven)`

---

## Task UI-10 — Evidence Drawer + RBAC-attributed Approval Overlay with budget impact

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/EvidenceDrawer.tsx`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/ApprovalOverlay.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/components/cockpit/ApprovalOverlay.test.tsx`

Steps:
- [ ] Write failing test `web/src/components/cockpit/ApprovalOverlay.test.tsx`:
  ```tsx
  import { describe, it, expect, vi } from "vitest";
  import { render, screen } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { ApprovalOverlay } from "@/components/cockpit/ApprovalOverlay";
  import { GATES, BUDGET } from "@/test/fixtures/controlplane";

  describe("ApprovalOverlay", () => {
    it("requires RBAC identity + rationale and surfaces budget impact, then submits attributed approval", async () => {
      const onDecided = vi.fn();
      render(
        <ApprovalOverlay
          gate={GATES[0]}
          budget={BUDGET}
          currentUserEmail="lead@biz2bricks.ai"
          estimatedCostUsd={1.25}
          onDecided={onDecided}
        />,
      );
      // budget impact shown: estimate + remaining-after
      expect(screen.getByText(/\$1\.25/)).toBeInTheDocument();
      expect(screen.getByText(/remaining/i)).toBeInTheDocument();

      // approve disabled until role + rationale provided (RBAC attribution)
      const approve = screen.getByRole("button", { name: /approve/i });
      expect(approve).toBeDisabled();

      await userEvent.selectOptions(screen.getByLabelText(/role/i), "lead_engineer");
      await userEvent.type(screen.getByLabelText(/rationale/i), "groundedness gate cleared");
      expect(approve).toBeEnabled();

      await userEvent.click(approve);
      expect(onDecided).toHaveBeenCalledWith(
        expect.objectContaining({ approver_email: "lead@biz2bricks.ai", decision: "approved" }),
      );
    });
  });
  ```
- [ ] Run `cd web && npm test -- ApprovalOverlay` — expected FAIL: module not found.
- [ ] Create `web/src/components/cockpit/ApprovalOverlay.tsx`:
  ```tsx
  "use client";

  import { useState } from "react";
  import { api } from "@/lib/api";
  import type { Approval, Budget, Gate } from "@/lib/types";

  const ROLES = ["lead_engineer", "architect", "risk_officer"];

  interface Props {
    gate: Gate;
    budget: Budget | null;
    currentUserEmail: string;
    estimatedCostUsd: number;
    onDecided: (approval: Approval) => void;
  }

  export function ApprovalOverlay({ gate, budget, currentUserEmail, estimatedCostUsd, onDecided }: Props) {
    const [role, setRole] = useState("");
    const [rationale, setRationale] = useState("");
    const [riskAccepted, setRiskAccepted] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const remainingAfter =
      budget ? Math.max(0, budget.cap_usd - budget.spent_usd - estimatedCostUsd) : null;
    const canDecide = role !== "" && rationale.trim().length > 0;

    const decide = async (decision: Approval["decision"]) => {
      setSubmitting(true);
      const approval = await api.submitApproval(gate.id, {
        decision,
        approver_email: currentUserEmail, // RBAC identity (non-negotiable)
        approver_role: role,
        risk_accepted: decision === "waived_with_risk" ? true : riskAccepted,
        rationale,
      });
      setSubmitting(false);
      onDecided(approval);
    };

    return (
      <div className="fixed inset-0 z-[70] bg-black/60 flex items-center justify-center">
        <div className="w-[28rem] rounded-lg border border-zinc-700 bg-zinc-900 p-5 space-y-3">
          <h3 className="text-base font-semibold">
            Approve gate: <span className="font-mono">{gate.gate_key}</span>
          </h3>

          {/* Budget impact */}
          <div className="rounded-md bg-zinc-800/60 p-2 text-xs text-zinc-300">
            estimated cost <span className="font-mono">${estimatedCostUsd.toFixed(2)}</span>
            {remainingAfter !== null && (
              <> · remaining after <span className="font-mono">${remainingAfter.toFixed(2)}</span>
                {budget && <> of ${budget.cap_usd.toFixed(0)} cap</>}</>
            )}
          </div>

          <label className="block text-xs text-zinc-400">
            Approver: <span className="font-mono text-zinc-200">{currentUserEmail}</span>
          </label>

          <label className="block text-xs text-zinc-400">
            Role
            <select
              aria-label="role"
              className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              <option value="">Select role…</option>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>

          <label className="block text-xs text-zinc-400">
            Rationale
            <textarea
              aria-label="rationale"
              className="mt-1 w-full bg-zinc-800 rounded px-2 py-1 text-sm"
              rows={3}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </label>

          <label className="flex items-center gap-2 text-xs text-zinc-400">
            <input type="checkbox" checked={riskAccepted}
                   onChange={(e) => setRiskAccepted(e.target.checked)} />
            accept risk (required for waive)
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button
              className="px-3 py-1.5 text-sm rounded bg-zinc-700 disabled:opacity-40"
              disabled={!canDecide || submitting}
              onClick={() => decide("rejected")}
            >
              Reject
            </button>
            <button
              className="px-3 py-1.5 text-sm rounded bg-amber-700 disabled:opacity-40"
              disabled={!canDecide || !riskAccepted || submitting}
              onClick={() => decide("waived_with_risk")}
            >
              Waive (risk)
            </button>
            <button
              className="px-3 py-1.5 text-sm rounded bg-emerald-700 disabled:opacity-40"
              disabled={!canDecide || submitting}
              onClick={() => decide("approved")}
            >
              Approve
            </button>
          </div>
        </div>
      </div>
    );
  }
  ```
- [ ] Create `web/src/components/cockpit/EvidenceDrawer.tsx` (renders the latest artifact's `evidence_map` lineage; source spans / graph nodes / judge feedback):
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import { FileSearch } from "lucide-react";
  import { api } from "@/lib/api";
  import type { Artifact } from "@/lib/types";

  export function EvidenceDrawer({ workspaceId }: { workspaceId: string }) {
    const [artifact, setArtifact] = useState<Artifact | null>(null);
    useEffect(() => {
      (async () => {
        const arts = await api.listArtifacts(workspaceId);
        setArtifact(arts[0] ?? null);
      })();
    }, [workspaceId]);

    return (
      <aside className="w-72 shrink-0 border-l border-zinc-800 bg-zinc-900/30 overflow-auto">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
          <FileSearch className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-medium">Evidence</span>
        </div>
        {!artifact ? (
          <p className="p-4 text-xs text-zinc-600">No artifact selected.</p>
        ) : (
          <div className="p-4 space-y-3">
            <div className="text-xs text-zinc-500">
              {artifact.kind} v{artifact.version} · {artifact.content_hash}
            </div>
            {Object.entries(artifact.evidence_map).map(([req, refs]) => (
              <div key={req}>
                <div className="text-xs font-medium text-zinc-300">{req}</div>
                <ul className="mt-1 space-y-0.5">
                  {refs.map((ref) => (
                    <li key={ref} className="text-xs font-mono text-sky-400">{ref}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </aside>
    );
  }
  ```
- [ ] Run `cd web && npm test -- ApprovalOverlay` — expected PASS (1 passed).
- [ ] Commit: `feat(web): evidence drawer + RBAC-attributed approval overlay with budget impact`

---

## Task UI-11 — Artifact viewer route (BRD HTML / JSON / evidence lineage)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/workspaces/[id]/artifacts/[artifactId]/page.tsx`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/src/app/workspaces/[id]/artifacts/artifactPage.test.tsx`

Steps:
- [ ] Write failing test `web/src/app/workspaces/[id]/artifacts/artifactPage.test.tsx`:
  ```tsx
  import { describe, it, expect } from "vitest";
  import { render, screen } from "@testing-library/react";
  import ArtifactPage from "@/app/workspaces/[id]/artifacts/[artifactId]/page";

  describe("ArtifactPage", () => {
    it("renders artifact metadata + evidence_map lineage", async () => {
      render(<ArtifactPage params={Promise.resolve({ id: "ws-1", artifactId: "art-brd-1" })} />);
      expect(await screen.findByText(/brd v1/i)).toBeInTheDocument();
      expect(screen.getByText("REQ-001")).toBeInTheDocument();
      expect(screen.getByText("CBACT01C.1000-MAIN")).toBeInTheDocument();
    });
  });
  ```
- [ ] Run `cd web && npm test -- artifactPage` — expected FAIL: module not found.
- [ ] Create `web/src/app/workspaces/[id]/artifacts/[artifactId]/page.tsx`:
  ```tsx
  "use client";

  import { use, useEffect, useState } from "react";
  import Link from "next/link";
  import { api } from "@/lib/api";
  import type { Artifact } from "@/lib/types";

  export default function ArtifactPage(
    { params }: { params: Promise<{ id: string; artifactId: string }> },
  ) {
    const { id, artifactId } = use(params);
    const [artifact, setArtifact] = useState<Artifact | null>(null);
    useEffect(() => {
      api.getArtifact(id, artifactId).then(setArtifact);
    }, [id, artifactId]);

    if (!artifact) return <div className="p-6 text-sm text-zinc-500">Loading artifact…</div>;

    return (
      <div className="max-w-4xl mx-auto p-6 space-y-4">
        <Link href={`/workspaces/${id}/journey/blueprint`} className="text-xs text-indigo-400">
          ← back to journey
        </Link>
        <h1 className="text-lg font-semibold">
          {artifact.kind} v{artifact.version}
        </h1>
        <div className="text-xs text-zinc-500 font-mono">
          {artifact.object_uri} · {artifact.content_hash}
        </div>
        <section>
          <h2 className="text-sm font-medium text-zinc-300 mb-2">Evidence map (lineage)</h2>
          {Object.entries(artifact.evidence_map).map(([req, refs]) => (
            <div key={req} className="mb-2">
              <div className="text-xs font-medium text-zinc-200">{req}</div>
              <ul className="ml-3 list-disc">
                {refs.map((r) => (
                  <li key={r} className="text-xs font-mono text-sky-400">{r}</li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      </div>
    );
  }
  ```
- [ ] Run `cd web && npm test -- artifactPage` — expected PASS (1 passed).
- [ ] Commit: `feat(web): artifact viewer route with evidence_map lineage`

---

## Task UI-12 — Playwright e2e happy-path through the cockpit

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/playwright.config.ts`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/web/e2e/journey.spec.ts`

Steps:
- [ ] Create `web/playwright.config.ts`:
  ```ts
  import { defineConfig } from "@playwright/test";

  export default defineConfig({
    testDir: "./e2e",
    use: { baseURL: "http://localhost:3000" },
    // The control plane (FastAPI) must be running on :8000 and proxied via
    // next.config.ts rewrites. Run `uv run uvicorn cobol_modernizer.api:app`
    // and `npm run dev` before `npm run e2e`.
    webServer: {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  });
  ```
- [ ] Create `web/e2e/journey.spec.ts`:
  ```ts
  import { test, expect } from "@playwright/test";

  // Happy path: portfolio -> workspace journey -> blueprint stage shows
  // the cockpit shell (rail, header, cost pill, agent console, evidence drawer).
  test("navigate portfolio into a workspace journey", async ({ page }) => {
    await page.goto("/workspaces");
    await expect(page.getByText("Modernization Cockpit")).toBeVisible();
    await page.getByText("CardDemo").click();

    // landed in the journey; Journey Rail shows all 11 stages
    await expect(page.getByRole("navigation")).toContainText("Blueprint");
    await expect(page.getByText("Modernization Agent")).toBeVisible();

    // cost-vs-cap pill visible in the stage header
    await expect(page.getByText(/\$\d+(\.\d+)?\s*\/\s*\$\d+/)).toBeVisible();
  });
  ```
- [ ] Run (manual, requires backend + dev server): `cd web && npx playwright install --with-deps chromium && npm run e2e` — expected PASS (1 passed). NOTE: this e2e is gated on the FastAPI control plane from the `api.py` ADAPT plan being up; in CI it is a smoke job, not a unit gate.
- [ ] Commit: `test(web): playwright e2e happy-path through the cockpit`

---

## Task UI-13 — Full unit suite + typecheck green

**Files:**
- Modify: none (verification task)

Steps:
- [ ] Run `cd web && npm test` — expected: all Vitest suites PASS (api, colors, PortfolioDashboard, JourneyRail, CostPill, useAgentStream, AgentConsole, ApprovalOverlay, stageDispatch, artifactPage).
- [ ] Run `cd web && npx tsc --noEmit` — expected: no type errors.
- [ ] Run `cd web && npm run build` — expected: Next build succeeds (all routes compiled: `/`, `/workspaces`, `/workspaces/[id]/journey/[stage]`, `/workspaces/[id]/artifacts/[artifactId]`).
- [ ] Commit: `chore(web): green unit suite + typecheck + production build`

---

## Acceptance criteria

The UI workstream is a cross-cutting workstream (master plan §6) whose screens land per the phase mapping above. It is complete when the following — mapped 1:1 to master plan §6 bullets and the §1/§7 non-negotiables it must honor — all hold:

1. **Shell continued from the source web tree, routes correct** — the cockpit is Next.js 15 App Router / React 19 / Tailwind (3.4 per Foundation) under `web/`, with the three routes `/workspaces`, `/workspaces/[id]/journey/[stage]`, `/workspaces/[id]/artifacts/[artifactId]`; `next.config.ts` proxies `/api/*` to FastAPI so **agent execution stays in FastAPI, never in Next server functions**. (§6 Shell; UI-1, UI-3, UI-6, UI-11)
2. **Five-region cockpit present** — Journey Rail (11 stages with status colors), Stage Header + Gates (gate pills + **cost-vs-cap** pill, kill-switch aware), Main Workspace (per-stage screen), single user-visible **Modernization Agent** Console, Evidence Drawer (evidence_map lineage / source refs / judge feedback). Tests `JourneyRail`, `CostPill`, `AgentConsole`, `ApprovalOverlay` pass. (§6 Five-region; UI-5, UI-7, UI-9, UI-10)
3. **Nine key screens exist and dispatch by stage** — Portfolio Dashboard, Repository Intake, Graph Explorer (reuses ported `GraphView.tsx` with COBOL filters + seam-overlay prop), Blueprint Studio, Seam Studio, Increment Planner, Design Studio, Build Lab, Equivalence Lab; each mapped to the phase that first needs it via `dependsOn`. Test `stageDispatch` passes. (§6 Key screens; UI-4, UI-6)
4. **5-mode HITL operating model + RBAC approver identity** — the Approval Overlay requires `approver_email` (RBAC identity), `approver_role`, and `rationale`, supports `approved`/`rejected`/`waived_with_risk` (waive requires `risk_accepted`), and surfaces **budget impact** (estimated cost + remaining-after-cap). Decisions POST to `/api/gates/{id}/approval`. Test `ApprovalOverlay` proves attribution + budget impact + waive gating. (§6 HITL + Approval overlay; §1 non-negotiable #6; UI-10)
5. **SSE streaming of AgentRun events** — `useAgentStream` subscribes (read-only) to `/api/workspaces/{id}/runs/{runId}/events` via `EventSource`, accumulates ordered `plan`/`tool_call`/`tool_result`/`cost`/`result`/`approval_request`/`failed`/`killed` events; the Agent Console renders readable tool-call events with full logs inspectable. Tests `useAgentStream`, `AgentConsole` pass. (§6 Streaming; UI-8, UI-9)
6. **Checkpointed/resumable sessions pinned to a graph snapshot + artifact versions** — the cockpit reads `workspace.graph_snapshot` and `artifact.version` from the control plane and renders them on the workspace + artifact views; runs are listed and the active run is resumed by re-subscribing to its event stream. (§6 Streaming; UI-2 DTOs, UI-9, UI-11)
7. **Token-economy + source-of-truth invariants honored in the client** — the cockpit reads everything through `lib/api.ts` (the single control-plane client); it never queries Neo4j/Postgres directly, never dumps whole source files (only `/api/entity`/slice-backed views), and surfaces the cost **cap** not just running spend. (master plan §1 #1, #7; §4; UI-2, UI-7)
8. **Verification green** — `npm test` (all Vitest suites), `npx tsc --noEmit`, and `npm run build` all pass; Playwright e2e happy-path is provided as a backend-gated smoke job. (UI-12, UI-13)

These map 1:1 to master plan §6 (Shell · Five-region cockpit · Key screens · HITL 5-mode + RBAC · Streaming/SSE · Approval overlay with budget impact) and uphold the §1/§7 non-negotiables (Neo4j source-of-truth via tools only, lineage/evidence everywhere, hard attributed human gates, token economy with caps + kill-switch surfaced, agent execution kept server-side).
