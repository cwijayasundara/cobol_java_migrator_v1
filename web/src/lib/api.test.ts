import { afterEach, describe, it, expect, vi } from "vitest";
import { api } from "@/lib/api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("enrichment api", () => {
  it("exposes enrich + enrichment helpers per stage", () => {
    expect(typeof api.startSeamsEnrich).toBe("function");
    expect(typeof api.getSeamsEnrichment).toBe("function");
    expect(typeof api.startPlanEnrich).toBe("function");
    expect(typeof api.getPlanEnrichment).toBe("function");
    expect(typeof api.startDesignEnrich).toBe("function");
    expect(typeof api.getDesignEnrichment).toBe("function");
  });

  it("can force-refresh seams and plan enrichment jobs", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ status: "running", result: null, error: null }),
    } as Response);

    await api.startSeamsEnrich("ws-1", true);
    await api.startPlanEnrich("ws-1", true);

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1, "/api/workspaces/ws-1/seams/enrich?refresh=true",
      { method: "POST" });
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2, "/api/workspaces/ws-1/plan/enrich?refresh=true",
      { method: "POST" });
  });
});

describe("domain-design api", () => {
  it("exposes start/refine/get helpers", () => {
    expect(typeof api.startDomainDesign).toBe("function");
    expect(typeof api.refineDomainDesign).toBe("function");
    expect(typeof api.getDomainDesign).toBe("function");
  });
});

describe("blueprint improve api", () => {
  it("exposes improve helpers", () => {
    expect(typeof api.startBlueprintImprove).toBe("function");
    expect(typeof api.getBlueprintImproveStatus).toBe("function");
  });
});

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
