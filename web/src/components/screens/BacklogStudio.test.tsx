import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { BacklogStudio } from "@/components/screens/BacklogStudio";

describe("BacklogStudio", () => {
  it("renders the Business Backlog heading on mount", () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    expect(screen.getByText(/Business Backlog/i)).toBeInTheDocument();
  });

  it("renders backlog status with epic/story counts and coverage after generate", async () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    // The component polls on mount — MSW GET /backlog returns "done" with result.
    await waitFor(() => expect(screen.getByText(/BRD coverage 86%/i)).toBeInTheDocument());
    expect(screen.getAllByText(/epics/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/stor/i).length).toBeGreaterThan(0);
  });

  it("disables the Generate backlog button while a run is in flight", async () => {
    // Keep the job running so the button settles into the busy/disabled state.
    server.use(
      http.post("/api/workspaces/:id/backlog", () =>
        HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
      http.get("/api/workspaces/:id/backlog", () =>
        HttpResponse.json({ status: "running", result: null, error: null })),
    );
    render(<BacklogStudio workspaceId="ws-1" />);
    const button = screen.getByRole("button", { name: /generate backlog/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
  });

  it("renders an iframe pointing to the backlog html url when done", async () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    await waitFor(() => {
      const frame = screen.getByTitle(/Backlog v/i) as HTMLIFrameElement;
      expect(frame.src).toContain("/api/workspaces/ws-1/backlog/html");
    });
  });
});
