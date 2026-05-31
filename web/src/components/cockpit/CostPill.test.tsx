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
