import { describe, it, expect } from "vitest";
import { api } from "@/lib/api";

describe("enrichment api", () => {
  it("exposes enrich + enrichment helpers per stage", () => {
    expect(typeof api.startSeamsEnrich).toBe("function");
    expect(typeof api.getSeamsEnrichment).toBe("function");
    expect(typeof api.startPlanEnrich).toBe("function");
    expect(typeof api.getPlanEnrichment).toBe("function");
    expect(typeof api.startDesignEnrich).toBe("function");
    expect(typeof api.getDesignEnrichment).toBe("function");
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
