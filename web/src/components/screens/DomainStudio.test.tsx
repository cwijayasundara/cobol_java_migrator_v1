import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DomainStudio } from "./DomainStudio";

describe("DomainStudio", () => {
  it("runs decomposition and shows contexts + topology", async () => {
    render(<DomainStudio workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button", { name: /decompose/i }));
    await waitFor(() => expect(screen.getByText(/Posting/)).toBeInTheDocument());
    expect(screen.getByText(/microservice/i)).toBeInTheDocument();
    expect(screen.getByText(/POST \/transactions/)).toBeInTheDocument();
  });
});
