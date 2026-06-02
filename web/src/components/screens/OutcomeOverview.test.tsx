import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OutcomeOverview } from "@/components/screens/OutcomeOverview";

describe("OutcomeOverview", () => {
  it("shows journey progress, graph stats, budget, and a next-step link", async () => {
    render(<OutcomeOverview workspaceId="ws-1" repoSlug="aws-mf-carddemo" />);
    // journey progress (fixture: 5 stages passed of 12 canonical stages)
    expect(await screen.findByText(/5 \/ 12 stages passed/)).toBeInTheDocument();
    // graph stats from graph-summary
    expect(screen.getByText(/40 entities · 29 relationships/)).toBeInTheDocument();
    // budget vs cap
    expect(screen.getByText(/\$18\.42 \/ \$50/)).toBeInTheDocument();
    // next actionable stage (first non-passed after outcome) -> a journey link
    const next = screen.getByRole("link", { name: /next:/i });
    expect(next.getAttribute("href")).toMatch(/^\/workspaces\/ws-1\/journey\/\w+$/);
  });
});
