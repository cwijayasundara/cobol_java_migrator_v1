import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EquivalenceLab } from "@/components/screens/EquivalenceLab";

describe("EquivalenceLab", () => {
  it("runs equivalence and shows the verdict + seam-linked defect", async () => {
    render(<EquivalenceLab workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /run equivalence/i }));
    expect(await screen.findByText("fail")).toBeInTheDocument();
    expect(screen.getByText(/1 compared · 1 defect/)).toBeInTheDocument();
    expect(screen.getByText("BAL")).toBeInTheDocument();
    expect(screen.getByText(/CBPOST1M\.1300-POST \(MOVES_TO\)/)).toBeInTheDocument();
    expect(screen.getByText(/golden=1234\.56 candidate=1234\.50/)).toBeInTheDocument();
  });
});
