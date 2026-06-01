import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IncrementPlanner } from "@/components/screens/IncrementPlanner";

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

  it("merges wave narrative and per-story enrichment after clicking Add detail", async () => {
    render(<IncrementPlanner workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(await screen.findByText(/wave 1/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /add detail/i }));
    expect(await screen.findByText(/ship readers first/i)).toBeInTheDocument();
  });
});
