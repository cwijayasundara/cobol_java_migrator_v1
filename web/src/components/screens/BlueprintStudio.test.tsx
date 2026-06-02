import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
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

  it("improves the BRD: types an instruction, clicks Improve, gets a new version", async () => {
    render(<BlueprintStudio workspaceId="w1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate blueprint/i }));
    // wait for the generated BRD to appear (textarea gated on result existing)
    const box = await screen.findByPlaceholderText(/how should we improve/i);
    fireEvent.change(box, { target: { value: "expand NFRs" } });
    fireEvent.click(screen.getByRole("button", { name: /^improve$/i }));
    expect(await screen.findByText(/v2/i)).toBeInTheDocument();
  });

  it("disables the button while a run is in flight (incl. on remount)", async () => {
    // backend reports an in-flight job for this workspace
    server.use(http.get("/api/workspaces/:id/blueprint", () => HttpResponse.json(
      { status: "running", result: null, error: null, started_at: 1, finished_at: null })));
    render(<BlueprintStudio workspaceId="ws-1" />);
    // mount sync sees 'running' -> the action is disabled without any click here
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generating/i })).toBeDisabled());
  });
});
