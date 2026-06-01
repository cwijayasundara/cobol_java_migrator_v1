import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ParseStudio } from "@/components/screens/ParseStudio";

describe("ParseStudio", () => {
  it("runs parse and shows the ingest result + a link to the graph", async () => {
    render(<ParseStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /run parse/i }));
    expect(await screen.findByText(/Parsed carddemo-mini/)).toBeInTheDocument();
    expect(screen.getByText(/entities: 38/)).toBeInTheDocument();
    expect(screen.getByText(/relationships: 30/)).toBeInTheDocument();
    const graphLink = screen.getByRole("link", { name: /view graph/i });
    expect(graphLink.getAttribute("href")).toBe("/workspaces/ws-1/journey/graph");
  });
});
