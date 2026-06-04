import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { DesignStudio } from "@/components/screens/DesignStudio";

describe("DesignStudio", () => {
  it("renders the Technical Design heading on mount", () => {
    render(<DesignStudio workspaceId="ws-1" />);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(/Technical Design/i);
  });

  it("renders technical design status with service count after generate", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    // The component polls on mount — MSW GET /technical-design returns "done" with result.
    await waitFor(() => expect(screen.getByText(/services/i)).toBeInTheDocument());
    expect(screen.getByText(/3 services/i)).toBeInTheDocument();
  });

  it("disables the Generate technical design button while a run is in flight", async () => {
    server.use(
      http.post("/api/workspaces/:id/technical-design", () =>
        HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
      http.get("/api/workspaces/:id/technical-design", () =>
        HttpResponse.json({ status: "running", result: null, error: null })),
    );
    render(<DesignStudio workspaceId="ws-1" />);
    const button = screen.getByRole("button", { name: /generate technical design/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
  });

  it("renders the component diagram, package tree, and database design when done", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    await waitFor(() => expect(screen.getByText(/Spring Boot microservices component diagram/i)).toBeInTheDocument());
    expect(screen.getAllByText("posting").length).toBeGreaterThan(0);
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByText("ACCTFILE")).toBeInTheDocument();
    expect(screen.getByText("acctfile")).toBeInTheDocument();
    expect(screen.getByText(/Table schema/i)).toBeInTheDocument();
    expect(screen.getByText("legacy_payload")).toBeInTheDocument();
  });

  it("shows an error banner when the job fails", async () => {
    server.use(
      http.get("/api/workspaces/:id/technical-design", () =>
        HttpResponse.json({ status: "failed", result: null, error: "LLM timeout" })),
    );
    render(<DesignStudio workspaceId="ws-1" />);
    await waitFor(() => expect(screen.getByText(/LLM timeout/i)).toBeInTheDocument());
  });
});
