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
