import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DomainStudio } from "./DomainStudio";

describe("DomainStudio", () => {
  it("runs decomposition and shows contexts + topology", async () => {
    render(<DomainStudio workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button", { name: /decompose/i }));
    // "Posting" appears in the context card and the class-diagram caption.
    await waitFor(() => expect(screen.getAllByText(/Posting/).length).toBeGreaterThan(0));
    expect(screen.getByText(/microservice/i)).toBeInTheDocument();
    expect(screen.getByText(/POST \/transactions/)).toBeInTheDocument();
    // The context-map diagram is rendered (stubbed mermaid in tests).
    expect(screen.getByText(/Context map/)).toBeInTheDocument();
  });
});
