import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BuildLab } from "@/components/screens/BuildLab";

describe("BuildLab", () => {
  it("generates a slice and lists test-first files with evidence", async () => {
    render(<BuildLab workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate code/i }));
    expect(await screen.findByText("carddemo-mini-posting")).toBeInTheDocument();
    expect(screen.getByText("com.cobolmodernizer.carddemomini")).toBeInTheDocument();
    expect(screen.getByText(/1 test/)).toBeInTheDocument();
    expect(screen.getByText(/PostingServiceTest\.java/)).toBeInTheDocument();
    expect(screen.getByText(/CBPOST1M\.WRITE-ACCT/)).toBeInTheDocument();
  });
});
