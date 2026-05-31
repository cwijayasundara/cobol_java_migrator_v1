import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ArtifactPage from "@/app/workspaces/[id]/artifacts/[artifactId]/page";

describe("ArtifactPage", () => {
  it("renders artifact metadata + evidence_map lineage", async () => {
    render(<ArtifactPage params={Promise.resolve({ id: "ws-1", artifactId: "art-brd-1" })} />);
    expect(await screen.findByText(/brd v1/i)).toBeInTheDocument();
    expect(screen.getByText("REQ-001")).toBeInTheDocument();
    expect(screen.getByText("CBACT01C.1000-MAIN")).toBeInTheDocument();
  });
});
