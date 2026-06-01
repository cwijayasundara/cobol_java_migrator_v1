import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { IncrementPlanner } from "@/components/screens/IncrementPlanner";
import { STAGES } from "@/test/fixtures/controlplane";

describe("IncrementPlanner", () => {
  it("builds an acyclic plan and lists stories in topo order with deps", async () => {
    render(<IncrementPlanner workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(await screen.findByText("acyclic")).toBeInTheDocument();
    expect(screen.getByText("CBVALDTM")).toBeInTheDocument();
    expect(screen.getByText("CBPOST1M")).toBeInTheDocument();
    expect(screen.getByText((content, element) =>
      element?.tagName !== "SCRIPT" && /after/i.test(content) && !!element?.textContent?.includes("S1")
    )).toBeInTheDocument();
  });

  it("renders delivery waves after building the plan", async () => {
    render(<IncrementPlanner workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(await screen.findByText(/wave 1/i)).toBeInTheDocument();
  });

  it("merges wave narrative and per-story enrichment after clicking Improve", async () => {
    render(<IncrementPlanner workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(await screen.findByText(/wave 1/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /improve/i }));
    expect(await screen.findByText(/ship readers first/i)).toBeInTheDocument();
  });

  it("auto-loads the plan and shows Improve button when plan stage is already passed", async () => {
    // Override /stages so the plan stage is already passed
    server.use(http.get("/api/workspaces/:id/stages", () =>
      HttpResponse.json(
        STAGES.map((s) => s.stage_key === "plan" ? { ...s, status: "passed" } : s),
      ),
    ));

    render(<IncrementPlanner workspaceId="ws-1" />);

    // Plan content should appear without any button click
    expect(await screen.findByText("CBVALDTM")).toBeInTheDocument();

    // The Improve button must be visible
    expect(screen.getByRole("button", { name: /improve/i })).toBeInTheDocument();
  });

  it("falls back to the flat numbered render when delivery_waves is absent", async () => {
    // Pre-existing deterministic behavior: with no delivery_waves the plan renders
    // as a flat, numbered topo-ordered list (the fallback branch).
    server.use(http.post("/api/workspaces/:id/plan", () => HttpResponse.json({
      repo_slug: "carddemo-mini", acyclic: true, topo_order: ["S1", "S2"],
      delivery_waves: [],
      stories: [
        { id: "S1", title: "Migrate CBVALDTM", seam: "CBVALDTM", depends_on: [], evidence_map: {} },
        { id: "S2", title: "Migrate CBPOST1M", seam: "CBPOST1M", depends_on: ["S1"], evidence_map: {} },
      ],
    })));

    render(<IncrementPlanner workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(await screen.findByText("acyclic")).toBeInTheDocument();

    // No wave headers in the flat fallback.
    expect(screen.queryByText(/wave 1/i)).not.toBeInTheDocument();
    // Flat numbered markers are present (1. , 2.).
    expect(screen.getByText("1.")).toBeInTheDocument();
    expect(screen.getByText("2.")).toBeInTheDocument();
    expect(screen.getByText("CBVALDTM")).toBeInTheDocument();
    expect(screen.getByText("CBPOST1M")).toBeInTheDocument();
    // depends_on still rendered as a single "after S1" node in the flat branch.
    expect(screen.getByText("after S1")).toBeInTheDocument();
  });
});
