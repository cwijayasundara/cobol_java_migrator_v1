import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { SeamStudio } from "@/components/screens/SeamStudio";
import { STAGES } from "@/test/fixtures/controlplane";

describe("SeamStudio", () => {
  it("ranks seam candidates and flags identity-drift writers", async () => {
    render(<SeamStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /find seams/i }));
    expect(await screen.findByText("CBVALDTM")).toBeInTheDocument();
    expect(screen.getByText("db_writer")).toBeInTheDocument();
    expect(screen.getByText("0.530")).toBeInTheDocument();
    expect(screen.getByText(/identity-drift writer/)).toBeInTheDocument();
  });

  it("merges LLM rationale into candidate rows after clicking Improve", async () => {
    render(<SeamStudio workspaceId="ws-1" />);
    // load the deterministic candidates first
    await userEvent.click(screen.getByRole("button", { name: /find seams/i }));
    expect(await screen.findByText("CBVALDTM")).toBeInTheDocument();

    // trigger enrichment
    await userEvent.click(screen.getByRole("button", { name: /improve/i }));

    // rationale for CBVALDTM should appear
    expect(await screen.findByText("reader, low risk")).toBeInTheDocument();
  });

  it("auto-loads candidates and shows Improve button when seams stage is already passed", async () => {
    // Override /stages so the seams stage is already passed
    server.use(http.get("/api/workspaces/:id/stages", () =>
      HttpResponse.json(
        STAGES.map((s) => s.stage_key === "seams" ? { ...s, status: "passed" } : s),
      ),
    ));

    render(<SeamStudio workspaceId="ws-1" />);

    // Candidates should appear without any button click
    expect(await screen.findByText("CBVALDTM")).toBeInTheDocument();

    // The Improve button must be visible
    expect(screen.getByRole("button", { name: /improve/i })).toBeInTheDocument();
  });
});
