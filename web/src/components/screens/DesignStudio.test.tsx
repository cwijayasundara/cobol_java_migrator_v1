import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DesignStudio } from "@/components/screens/DesignStudio";

describe("DesignStudio", () => {
  it("designs writer slices with context, ownership gate, and ADRs", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /design services/i }));
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();
    expect(screen.getByText("transaction_processing")).toBeInTheDocument();
    expect(screen.getByText(/ownership clean/i)).toBeInTheDocument();
    expect(screen.getByText(/ACCTFILE, TRANFILE/)).toBeInTheDocument();
    expect(screen.getByText(/ADR-3: Legacy Mimic for parity/)).toBeInTheDocument();
  });
});
