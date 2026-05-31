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
