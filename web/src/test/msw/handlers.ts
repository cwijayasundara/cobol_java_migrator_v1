import { http, HttpResponse } from "msw";
import { WORKSPACE, STAGES, GATES, BUDGET, RUN, ARTIFACT, REPOS } from "@/test/fixtures/controlplane";

export const handlers = [
  http.get("/api/repos", () => HttpResponse.json(REPOS)),
  http.get("/api/workspaces", () => HttpResponse.json([WORKSPACE])),
  http.post("/api/workspaces", async ({ request }) => {
    const body = (await request.json()) as { name: string; repo_slug: string; created_by: string };
    return HttpResponse.json({
      id: `ws-${body.repo_slug}`, graph_snapshot: null,
      created_at: "2026-05-30T00:00:00Z", status: "active", ...body,
    });
  }),
  http.get("/api/workspaces/:id", () => HttpResponse.json(WORKSPACE)),
  http.get("/api/workspaces/:id/stages", () => HttpResponse.json(STAGES)),
  http.get("/api/workspaces/:id/gates", () => HttpResponse.json(GATES)),
  http.get("/api/workspaces/:id/budget", () => HttpResponse.json(BUDGET)),
  http.get("/api/workspaces/:id/graph-summary", () => HttpResponse.json({
    repo_slug: "aws-mf-carddemo", entities: 40, relationships: 29,
    by_kind: { Program: 3, Paragraph: 13, DataItem: 20, Copybook: 1, External: 3 },
  })),
  http.post("/api/workspaces/:id/parse", () => HttpResponse.json({
    repo_slug: "carddemo-mini", programs: 3, copybooks: 1, parse_errors: 0,
    entities: 38, relationships: 30,
  })),
  http.post("/api/workspaces/:id/ask", async ({ request }) => {
    const body = (await request.json()) as { question: string };
    return HttpResponse.json({
      answer: `Re: ${body.question} — CBPOST1M writes ACCTFILE.`,
      grounded: true, model: "claude-haiku-4-5-20251001", context_entities: 38,
    });
  }),
  http.post("/api/workspaces/:id/seams", () => HttpResponse.json({
    repo_slug: "carddemo-mini", count: 2,
    candidates: [
      { program: "CBVALDTM", seam_type: "db_reader",
        score: { weighted: 0.53, normalized: {} }, signals: {},
        transition: { name: "cdc_read_replica", summary: "" },
        identity_drift_writer: false, evidence_map: {} },
      { program: "CBPOST1M", seam_type: "db_writer",
        score: { weighted: 0.27, normalized: {} }, signals: {},
        transition: { name: "extract_product_lines", summary: "" },
        identity_drift_writer: true, evidence_map: {} },
    ],
  })),
  http.post("/api/workspaces/:id/plan", () => HttpResponse.json({
    repo_slug: "carddemo-mini", acyclic: true, topo_order: ["S1", "S2"],
    stories: [
      { id: "S1", title: "Migrate CBVALDTM", seam: "CBVALDTM", depends_on: [], evidence_map: {} },
      { id: "S2", title: "Migrate CBPOST1M", seam: "CBPOST1M", depends_on: ["S1"], evidence_map: {} },
    ],
  })),
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
