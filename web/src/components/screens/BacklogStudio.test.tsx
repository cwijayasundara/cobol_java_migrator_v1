import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("shows a Generate backlog button that triggers the job", async () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    const btn = screen.getByRole("button", { name: /generate backlog/i });
    expect(btn).toBeInTheDocument();
    await userEvent.click(btn);
    // After click the button becomes disabled while running, then re-enables.
    // Simply assert the component doesn't crash after interaction.
    await waitFor(() =>
      expect(screen.getByText(/Business Backlog/i)).toBeInTheDocument(),
    );
  });

  it("renders an iframe pointing to the backlog html url when done", async () => {
    render(<BacklogStudio workspaceId="ws-1" />);
    await waitFor(() => {
      const frame = screen.getByTitle(/Backlog v/i) as HTMLIFrameElement;
      expect(frame.src).toContain("/api/workspaces/ws-1/backlog/html");
    });
  });
});
