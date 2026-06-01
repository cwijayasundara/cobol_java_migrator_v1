import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StageScreen } from "@/components/screens/StageScreen";

describe("stage dispatcher", () => {
  it("renders Blueprint Studio for the blueprint stage", async () => {
    render(<StageScreen workspaceId="ws-1" stageKey="blueprint" repoSlug="aws-mf-carddemo" />);
    expect(await screen.findByText(/Functional Blueprint/)).toBeInTheDocument();
  });
  it("renders the Seams screen for the seams stage", () => {
    render(<StageScreen workspaceId="ws-1" stageKey="seams" repoSlug="aws-mf-carddemo" />);
    expect(screen.getByText("Seam candidates")).toBeInTheDocument();
  });
});
