import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BlueprintStudio } from "@/components/screens/BlueprintStudio";

describe("BlueprintStudio", () => {
  it("generates a BRD and shows rating, score, and an inline HTML frame", async () => {
    render(<BlueprintStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate blueprint/i }));
    expect(await screen.findByText("BRD v1")).toBeInTheDocument();
    expect(screen.getByText(/high · score 4\.40/)).toBeInTheDocument();
    expect(screen.getByText(/1 attempt/)).toBeInTheDocument();
    const frame = screen.getByTitle("BRD v1") as HTMLIFrameElement;
    expect(frame.src).toContain("/api/workspaces/ws-1/blueprint/html");
  });
});
