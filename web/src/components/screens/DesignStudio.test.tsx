import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { DesignStudio } from "@/components/screens/DesignStudio";
import { STAGES } from "@/test/fixtures/controlplane";

describe("DesignStudio", () => {
  it("designs writer slices with context, ownership gate, and ADRs", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /design services/i }));
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();
    expect(screen.getByText("transaction_processing")).toBeInTheDocument();
    expect(screen.getByText(/ownership clean/i)).toBeInTheDocument();
    expect(screen.getByText(/ACCTFILE, TRANFILE/)).toBeInTheDocument();
    expect(screen.getByText(/ADR-3: Legacy Mimic for parity/)).toBeInTheDocument();
  });

  it("merges LLM elaboration into design cards after clicking Improve", async () => {
    render(<DesignStudio workspaceId="ws-1" />);
    // load the deterministic designs first
    await userEvent.click(screen.getByRole("button", { name: /design services/i }));
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();

    // trigger enrichment
    await userEvent.click(screen.getByRole("button", { name: /improve/i }));

    // api_surface from the enrichment result should appear
    expect(await screen.findByText(/POST \/accounts/i)).toBeInTheDocument();
  });

  it("auto-loads designs and shows Improve button when design stage is already passed", async () => {
    // Override /stages so the design stage is already passed
    server.use(http.get("/api/workspaces/:id/stages", () =>
      HttpResponse.json(
        STAGES.map((s) => s.stage_key === "design" ? { ...s, status: "passed" } : s),
      ),
    ));

    render(<DesignStudio workspaceId="ws-1" />);

    // Design content should appear without any button click
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();

    // The Improve button must be visible
    expect(screen.getByRole("button", { name: /improve/i })).toBeInTheDocument();
  });
});
