import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SeamStudio } from "@/components/screens/SeamStudio";

describe("SeamStudio", () => {
  it("ranks seam candidates and flags identity-drift writers", async () => {
    render(<SeamStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /find seams/i }));
    expect(await screen.findByText("CBVALDTM")).toBeInTheDocument();
    expect(screen.getByText("db_writer")).toBeInTheDocument();
    expect(screen.getByText("0.530")).toBeInTheDocument();
    expect(screen.getByText(/identity-drift writer/)).toBeInTheDocument();
  });
});
