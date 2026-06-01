import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExploreChat } from "@/components/screens/ExploreChat";

describe("ExploreChat", () => {
  it("sends a question and shows the grounded answer", async () => {
    render(<ExploreChat workspaceId="ws-1" repoSlug="carddemo-mini" />);
    await userEvent.type(screen.getByLabelText(/question/i), "which programs write ACCTFILE?");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));
    // user's question echoed + the assistant answer (from MSW)
    expect(await screen.findByText(/CBPOST1M writes ACCTFILE/)).toBeInTheDocument();
    expect(screen.getByText("which programs write ACCTFILE?")).toBeInTheDocument();
  });
});
