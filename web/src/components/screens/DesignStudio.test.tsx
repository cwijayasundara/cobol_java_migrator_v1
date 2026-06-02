import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { DesignStudio } from "@/components/screens/DesignStudio";
import { STAGES } from "@/test/fixtures/controlplane";

// A Domain Design result whose bounded context owns the design fixture's writer program
// (CBPOST1M), so the Improve overlay can map the slice -> context DDD.
const DOMAIN_DONE = {
  status: "done",
  error: null,
  result: {
    repo_slug: "aws-mf-carddemo",
    version: 1,
    rating: "high",
    contexts: [{
      name: "Posting", business_capability: "Post transactions",
      member_programs: ["CBPOST1M"], owned_resources: ["TRANFILE"], depends_on: [],
      topology: { deployment: "microservice", score: 0.7, inputs: {}, rationale: "" },
      extraction_rank: 1, identity_drift: false,
    }],
    designs: [{
      context: "Posting",
      aggregates: [{ name: "Posting", root_entity: "Posting", invariants: ["amount != 0"],
                     entities: [], value_objects: [], methods: ["post"] }],
      value_objects: [], domain_services: [], repositories: [], domain_events: [],
      api_surface: "POST /accounts", cobol_mapping: [],
    }],
  },
};

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

  it("Improve overlays the Domain Design DDD onto each slice (no fresh LLM call)", async () => {
    server.use(http.get("/api/workspaces/:id/domain-design", () => HttpResponse.json(DOMAIN_DONE)));
    render(<DesignStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /design services/i }));
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /improve/i }));

    // The slice now shows its bounded context + that context's API surface from Domain Design.
    expect(await screen.findByText(/Bounded context:/)).toBeInTheDocument();
    expect(screen.getByText(/POST \/accounts/)).toBeInTheDocument();
  });

  it("Improve tells you to run Domain Design first when none exists", async () => {
    server.use(http.get("/api/workspaces/:id/domain-design", () =>
      HttpResponse.json({ status: "idle", result: null, error: null })));
    render(<DesignStudio workspaceId="ws-1" />);
    await userEvent.click(screen.getByRole("button", { name: /design services/i }));
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /improve/i }));
    expect(await screen.findByText(/run the Domain Design stage/i)).toBeInTheDocument();
  });

  it("auto-loads designs and shows the Improve button when the design stage is already passed", async () => {
    server.use(http.get("/api/workspaces/:id/stages", () =>
      HttpResponse.json(
        STAGES.map((s) => s.stage_key === "design" ? { ...s, status: "passed" } : s),
      ),
    ));
    render(<DesignStudio workspaceId="ws-1" />);
    expect(await screen.findByText("CBPOST1M-slice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /improve/i })).toBeInTheDocument();
  });
});
