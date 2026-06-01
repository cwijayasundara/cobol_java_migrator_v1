import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RepositoryIntake } from "@/components/screens/RepositoryIntake";

describe("RepositoryIntake", () => {
  it("shows the selected repo's summary and a Next: Parse link", async () => {
    render(<RepositoryIntake workspaceId="ws-1" repoSlug="carddemo-mini" />);
    // path is unique (name == slug in the fixture), so anchor the load on it
    expect(await screen.findByText(/source_code_to_analyse\/carddemo-mini/)).toBeInTheDocument();
    expect(screen.getAllByText("carddemo-mini").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/3 programs/)).toBeInTheDocument();
    expect(screen.getByText(/1 copybooks/)).toBeInTheDocument();
    const next = screen.getByRole("link", { name: /next: parse/i });
    expect(next.getAttribute("href")).toBe("/workspaces/ws-1/journey/parse");
  });

  it("warns when the repo slug has no matching folder", async () => {
    render(<RepositoryIntake workspaceId="ws-1" repoSlug="aws-mf-carddemo" />);
    expect(await screen.findByText(/isn’t a folder under/)).toBeInTheDocument();
  });
});
